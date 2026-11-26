"""Laughs and screams in the stream's audio, so the clip picker hears a reaction and not just "loud".

sherpa-onnx audio tagging (CED-tiny, AudioSet classes) on the CPU, 2-second chunks of the small
transcription audio: about 11 s per stream hour. The model (6 MB) is downloaded once.
"""

from pathlib import Path
from typing import List, Tuple
import os
import tarfile
import uuid

from ..config import get_config
from .common import logger

LAUGH = {"Laughter", "Giggle", "Belly laugh", "Chuckle, chortle", "Snicker"}
SCREAM = {"Screaming", "Shout", "Yell", "Whoop"}
CHUNK_SECONDS = 2  # longer chunks found fewer laughs on a real 11-hour stream
# ponytail: tuned on one GTA stream (about 1 hit per stream hour at 0.25); game dialogue laughing counts too.
MIN_PROB = 0.25
QUIET_DB = -45.0  # skip near-silence

_NAME = "sherpa-onnx-ced-tiny-audio-tagging-2024-04-19"
_URL = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/audio-tagging-models/{_NAME}.tar.bz2"
_tagger = None


def _model() -> Tuple[Path, Path]:
    directory = Path(get_config().temp_dir) / "models" / "reactions"
    directory.mkdir(parents=True, exist_ok=True)
    model, labels = directory / "model.int8.onnx", directory / "class_labels_indices.csv"
    if not (model.exists() and labels.exists()):
        from .diarization import _fetch

        archive = directory / f".ced.{uuid.uuid4().hex}.tar.bz2"
        try:
            _fetch(_URL, archive)
            with tarfile.open(archive) as tar:
                for target in (labels, model):
                    partial = directory / f".{target.name}.{uuid.uuid4().hex}"
                    partial.write_bytes(tar.extractfile(f"{_NAME}/{target.name}").read())
                    os.replace(partial, target)
        finally:
            archive.unlink(missing_ok=True)
    return model, labels


def _get_tagger():
    global _tagger
    if _tagger is None:
        import sherpa_onnx

        model, labels = _model()
        _tagger = sherpa_onnx.AudioTagging(
            sherpa_onnx.AudioTaggingConfig(
                model=sherpa_onnx.AudioTaggingModelConfig(
                    ced=str(model), num_threads=max(1, min(4, (os.cpu_count() or 2) // 2))
                ),
                labels=str(labels),
                top_k=50,
            )
        )
    return _tagger


def merge_hits(hits: List[Tuple[float, str]]) -> List[Tuple[float, float, str]]:
    """(start, kind) chunk hits to (start, end, kind) spans; same-kind chunks up to 4 s apart join."""
    spans: List[Tuple[float, float, str]] = []
    for start, kind in sorted(hits):
        if spans and spans[-1][2] == kind and start - spans[-1][1] <= 2 * CHUNK_SECONDS:
            spans[-1] = (spans[-1][0], start + CHUNK_SECONDS, kind)
        else:
            spans.append((start, start + CHUNK_SECONDS, kind))
    return spans


def detect_reactions(video_path: Path) -> List[Tuple[float, float, str]]:
    """(start, end, "laughing" | "screaming") spans in seconds; [] when the audio can't be read.

    Kept beside the video (minutes for a long stream), so a resume or Find more doesn't listen again."""
    import json

    cache = video_path.with_name(f"{video_path.stem}.reactions.json")
    version = f"{_NAME}:{CHUNK_SECONDS}:{MIN_PROB}:{QUIET_DB}"
    try:
        kept = json.loads(cache.read_text(encoding="utf-8"))
        if kept["version"] == version:
            return [tuple(span) for span in kept["spans"]]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    spans = _detect_reactions(video_path)
    try:
        cache.write_text(json.dumps({"version": version, "spans": spans}), encoding="utf-8")
    except OSError:
        pass
    return spans


def _detect_reactions(video_path: Path) -> List[Tuple[float, float, str]]:
    import numpy as np

    from .transcription import WHISPER_CHUNK_SECONDS, _decode_audio_chunk

    audio_path = video_path.with_name(f"{video_path.stem}.transcription.mp3")
    if not audio_path.exists():
        audio_path = video_path
    tagger = _get_tagger()
    step = CHUNK_SECONDS * 16000
    hits: List[Tuple[float, str]] = []
    offset = 0
    while True:
        audio = _decode_audio_chunk(audio_path, offset)  # an hour at a time
        for i in range(0, len(audio) - step // 2, step):
            chunk = audio[i:i + step]
            if 20 * np.log10(np.sqrt(np.mean(chunk * chunk)) + 1e-9) < QUIET_DB:
                continue
            stream = tagger.create_stream()
            stream.accept_waveform(16000, chunk)
            events = tagger.compute(stream)
            laugh = max((e.prob for e in events if e.name in LAUGH), default=0.0)
            scream = max((e.prob for e in events if e.name in SCREAM), default=0.0)
            if max(laugh, scream) >= MIN_PROB:
                hits.append((offset + i / 16000, "laughing" if laugh >= scream else "screaming"))
        if len(audio) < WHISPER_CHUNK_SECONDS * 16000:
            break
        offset += WHISPER_CHUNK_SECONDS
    spans = merge_hits(hits)
    logger.info("Reactions: %d laughing, %d screaming spans", sum(s[2] == "laughing" for s in spans),
                sum(s[2] == "screaming" for s in spans))
    return spans
