"""Who said which word, worked out on this PC (sherpa-onnx on the CPU, no torch, no cloud).

Run per clip, not per VOD: a clip is a minute of audio and takes a second or two.
Speaker numbers are per clip: 0 is whoever says the most words.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
import os
import subprocess
import tarfile
import threading
import urllib.request
import uuid

from ..config import get_config
from .common import logger

# Caption colours for the 2nd, 3rd, ... speaker (the 1st keeps the caption colour); same in document.ts.
SPEAKER_COLORS = ["#38BDF8", "#F472B6", "#4ADE80", "#FB923C", "#A78BFA"]
MAX_SPEAKERS = len(SPEAKER_COLORS) + 1
# Voices closer than this are one person. Raise it if one person gets two colours, lower it if two share one.
CLUSTER_THRESHOLD = 0.5
MIN_SPEAKER_SECONDS = 1.0  # shorter than this in a clip is a misfire, not a person

_RELEASES = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
_SEGMENTATION = "sherpa-onnx-pyannote-segmentation-3-0"
_EMBEDDING = "3dspeaker_speech_eres2net_sv_en_voxceleb_16k.onnx"
_lock = threading.Lock()
_diarizer = None


def _fetch(url: str, target: Path) -> None:
    partial = target.with_name(f".{target.name}.{uuid.uuid4().hex}")
    try:
        urllib.request.urlretrieve(url, partial)
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)


def _models() -> Tuple[Path, Path]:
    """The two model files (33 MB), downloaded once into the state folder."""
    directory = Path(get_config().temp_dir) / "models" / "speakers"
    directory.mkdir(parents=True, exist_ok=True)
    segmentation, embedding = directory / "segmentation.onnx", directory / _EMBEDDING
    if not segmentation.exists():
        archive = directory / "segmentation.tar.bz2"
        _fetch(f"{_RELEASES}/speaker-segmentation-models/{_SEGMENTATION}.tar.bz2", archive)
        with tarfile.open(archive) as tar:
            source = tar.extractfile(f"{_SEGMENTATION}/model.onnx")
            partial = directory / f".segmentation.{uuid.uuid4().hex}"
            partial.write_bytes(source.read())
            os.replace(partial, segmentation)
        archive.unlink(missing_ok=True)
    if not embedding.exists():
        _fetch(f"{_RELEASES}/speaker-recongition-models/{_EMBEDDING}", embedding)
    return segmentation, embedding


def _get_diarizer():
    global _diarizer
    if _diarizer is None:
        import sherpa_onnx

        segmentation, embedding = _models()
        threads = max(1, min(4, (os.cpu_count() or 2) // 2))
        _diarizer = sherpa_onnx.OfflineSpeakerDiarization(
            sherpa_onnx.OfflineSpeakerDiarizationConfig(
                segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
                    pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(segmentation)),
                    num_threads=threads,
                ),
                embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(embedding), num_threads=threads),
                clustering=sherpa_onnx.FastClusteringConfig(num_clusters=-1, threshold=CLUSTER_THRESHOLD),
                min_duration_on=0.3,
                min_duration_off=0.5,
            )
        )
    return _diarizer


def _decode(media_path: Path, ranges: Optional[Sequence[Tuple[float, float]]]):
    """16 kHz mono float32 samples of the ranges, back to back (the whole file without ranges)."""
    import numpy as np

    from .ffmpeg import select_audio_stream_index

    stream = select_audio_stream_index(media_path)  # the track the renderer cuts
    chunks = []
    for start, end in ranges or [(None, None)]:
        cut = ["-ss", str(start), "-t", str(end - start)] if start is not None else []
        result = subprocess.run(
            ["ffmpeg", "-v", "error", *cut, "-i", str(media_path),
             *(["-map", f"0:a:{stream}"] if stream is not None else []),
             "-vn", "-f", "f32le", "-ac", "1", "-ar", "16000", "-"],
            capture_output=True,
        )
        chunks.append(np.frombuffer(result.stdout, np.float32))
    return np.concatenate(chunks)


def assign_speakers(
    words: Sequence[Dict[str, Any]], turns: Sequence[Tuple[float, float, int]]
) -> List[int]:
    """A speaker number per word from (start, end, speaker) turns; 0 says the most words."""
    if not turns:
        return [0] * len(words)
    seconds: Dict[int, float] = {}
    for start, end, speaker in turns:
        seconds[speaker] = seconds.get(speaker, 0.0) + end - start
    real = [t for t in turns if seconds[t[2]] >= MIN_SPEAKER_SECONDS] or list(turns)

    def speaker_at(word) -> int:
        start, end = float(word["start"]), float(word["end"])
        middle = (start + end) / 2
        # Most overlap wins; a word in a gap goes to the nearest turn.
        return max(
            real,
            key=lambda t: (min(end, t[1]) - max(start, t[0]), -min(abs(middle - t[0]), abs(middle - t[1]))),
        )[2]

    raw = [speaker_at(word) for word in words]
    for i in range(1, len(raw) - 1):  # nobody cuts in for one word mid-sentence
        if raw[i - 1] == raw[i + 1] != raw[i]:
            raw[i] = raw[i - 1]
    by_count = sorted(set(raw), key=lambda s: (-raw.count(s), raw.index(s)))
    rank = {speaker: min(index, MAX_SPEAKERS - 1) for index, speaker in enumerate(by_count)}
    return [rank[speaker] for speaker in raw]


def label_speakers(
    media_path: Path,
    words: Sequence[Dict[str, Any]],
    ranges: Optional[Sequence[Tuple[float, float]]] = None,
) -> List[int]:
    """A speaker number (0 = talks most) for each word; all 0 if detection is off or fails.

    Word times are seconds on the timeline made of `ranges` of the file played back to
    back, or on the file itself without ranges.
    """
    if not words or not get_config().speaker_captions:
        return [0] * len(words)
    try:
        samples = _decode(Path(media_path), ranges)
        if samples.size < 16000:
            return [0] * len(words)
        with _lock:  # two clips render at once; the models are loaded once and used in turn
            result = _get_diarizer().process(samples).sort_by_start_time()
        return assign_speakers(words, [(t.start, t.end, t.speaker) for t in result])
    except Exception as exc:  # a missing model or DLL must never cost the clip its captions
        logger.warning("Speaker detection skipped: %s", exc)
        return [0] * len(words)
