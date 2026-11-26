"""Takes the music out of a video's sound and keeps the voice and game sound, on this PC.

Two models split a soundtrack into speech, music and effects (trained on "Divide and Remaster"); the music is
subtracted from the original, so whatever the model is unsure of stays in.
- TIGER (Tsinghua, Apache-2.0) on the graphics card through DirectML: takes out about 4 dB more music than MRX and
  barely touches game sound. About a third of real time on an RTX 4070, far too slow on a CPU.
- MRX (MERL, MIT) on the CPU when no graphics card can run TIGER: about 8x faster than real time.
Both run with onnxruntime (onnxruntime-directml on Windows) and download once (7 and 31 MB) from the
"music-models-1" pre-release (.github/workflows/music-model.yml).

A source file is done in BLOCK-second pieces, kept as FLAC in `<asset folder>/music-free/<n>.flac`, so taking the
music out of one stretch of a two-hour stream only costs that stretch, and later edits reuse what is done.
"""

from pathlib import Path
from typing import Callable, Iterable, Optional
import hashlib
import logging
import os
import subprocess
import threading

import numpy as np

from ..config import get_config

logger = logging.getLogger(__name__)

_RELEASE = "https://github.com/MarkyADHD/LocalClip/releases/download/music-models-1"
_MODELS = {
    "tiger": ("tiger.int8.onnx", "2189859ac7e89cf4d9d284c6f393e737aaa2b3233ed7ee424ad622012bce7bca"),
    "mrx": ("mrx.int8.onnx", "d876c92d224f5d8cd2207d528b23369da895a6de71fb24132416fcb16f9f8424"),
}
RATE = 44100
BLOCK = 24  # seconds of source per stored piece: two TIGER segments
_SEGMENT = 12 * RATE  # TIGER's fixed input
# ponytail: TIGER segments do not overlap (upstream overlaps them 3x, at 3x the time) and MRX sees PAD seconds
# either side of a block with the edges cut hard; a faint change every 12 s is possible. Overlap them if it is heard.
PAD = 2
_lock = threading.Lock()
work_lock = threading.Lock()  # one music job at a time: it uses the whole graphics card or every core
_session = None


def _load(name: str, providers: list):
    import onnxruntime

    from .diarization import _fetch

    file, sha256 = _MODELS[name]
    directory = Path(get_config().temp_dir) / "models" / "music"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / file
    if not path.exists():
        _fetch(f"{_RELEASE}/{file}", path)
    if hashlib.sha256(path.read_bytes()).hexdigest() != sha256:
        path.unlink(missing_ok=True)
        raise RuntimeError("The music removal model did not download properly. Try again.")
    options = onnxruntime.SessionOptions()
    if "DmlExecutionProvider" in providers:
        options.enable_mem_pattern = False  # DirectML needs both of these
        options.execution_mode = onnxruntime.ExecutionMode.ORT_SEQUENTIAL
    return onnxruntime.InferenceSession(str(path), options, providers=providers)


def _get_session():
    """(model name, session): TIGER on the graphics card when there is one that works, MRX on the CPU otherwise."""
    global _session
    with _lock:
        if _session is None:
            import onnxruntime

            if "DmlExecutionProvider" in onnxruntime.get_available_providers() and os.environ.get("MUSIC_GPU") != "false":
                try:
                    session = _load("tiger", ["DmlExecutionProvider"])
                    session.run(None, {"mix_spec": np.zeros((1, 2, 1025, 1034), np.float32)})
                    _session = ("tiger", session)
                except Exception:
                    logger.exception("The graphics card could not run the music model; using the CPU")
            if _session is None:
                _session = ("mrx", _load("mrx", ["CPUExecutionProvider"]))
        return _session


def _stft(x: np.ndarray, n: int, hop: int, scale: float) -> np.ndarray:
    """[channels, samples] -> [channels, n/2+1, frames]: Hann window, centred with reflect padding, divided by scale."""
    x = np.pad(x.astype(np.float32), ((0, 0), (n // 2, n // 2)), mode="reflect")
    frames = np.lib.stride_tricks.sliding_window_view(x, n, axis=1)[:, ::hop]
    window = np.hanning(n + 1)[:-1].astype(np.float32)
    return np.fft.rfft(frames * window, axis=2).transpose(0, 2, 1) / np.float32(scale)


def _istft(spec: np.ndarray, n: int, hop: int, scale: float, length: int) -> np.ndarray:
    """Inverse of _stft, back to [channels, length]."""
    window = np.hanning(n + 1)[:-1].astype(np.float32)
    frames = np.fft.irfft(spec.transpose(0, 2, 1) * np.float32(scale), n=n, axis=2).astype(np.float32) * window
    count = frames.shape[1]
    total = n + hop * (count - 1)
    out = np.zeros((spec.shape[0], total), np.float32)
    norm = np.zeros(total, np.float32)
    for i in range(count):
        out[:, i * hop : i * hop + n] += frames[:, i]
        norm[i * hop : i * hop + n] += window**2
    return (out / np.maximum(norm, 1e-8))[:, n // 2 : n // 2 + length]


def _tiger_music(session, audio: np.ndarray) -> np.ndarray:
    """TIGER's music stem, 12 s of one channel per run (n 2048, hop 512, unnormalised)."""
    music = np.zeros_like(audio)
    for channel in range(audio.shape[0]):
        for start in range(0, audio.shape[1], _SEGMENT):
            piece = audio[channel : channel + 1, start : start + _SEGMENT]
            segment = np.pad(piece, ((0, 0), (0, _SEGMENT - piece.shape[1])))
            spec = _stft(segment, 2048, 512, 1)
            stems = session.run(None, {"mix_spec": np.stack([spec.real, spec.imag], 1).astype(np.float32)})[0][0]
            # stems_spec: dialogue, music, effects, each as re and im.
            music[channel, start : start + piece.shape[1]] = _istft(
                (stems[2] + 1j * stems[3])[None], 2048, 512, 1, _SEGMENT
            )[0, : piece.shape[1]]
    return music


def _mrx_music(session, audio: np.ndarray) -> np.ndarray:
    """MRX's music stem: magnitudes at three resolutions (hop 256, / sqrt(n)) in, a mask per source out."""
    sizes = (1024, 2048, 8192)
    # The network was trained on mixes near -27 LUFS; plain RMS is close enough to set the level it hears.
    rms = float(np.sqrt(np.mean(audio**2))) or 1.0
    level = min(10 ** (-27 / 20) / rms, 100.0)
    specs = {n: _stft(audio * level, n, 256, np.sqrt(n)) for n in sizes}
    masks = session.run(None, {f"mag_{n}": np.abs(specs[n]).astype(np.float32) for n in sizes})
    # Masks are [channels, (music, speech, effects), bins, frames]; the sources add up across resolutions.
    return sum(_istft(masks[i][:, 0] * specs[n], n, 256, np.sqrt(n), audio.shape[1]) for i, n in enumerate(sizes)) / level


def read_audio(path: str, start: float, seconds: float) -> np.ndarray:
    """[2, samples] float32 at 44.1 kHz from `start`, zero-padded where the file has no sound."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{max(0.0, start):.4f}", "-t", f"{seconds:.4f}", "-i", path,
         "-vn", "-f", "f32le", "-ac", "2", "-ar", str(RATE), "-"],
        capture_output=True, check=True,
    ).stdout
    audio = np.frombuffer(raw, np.float32).reshape(-1, 2).T
    lead = round(max(0.0, -start) * RATE)
    want = round(seconds * RATE)
    return np.pad(audio, ((0, 0), (lead, max(0, want - lead - audio.shape[1]))))[:, :want]


def music_free_block(source: str, index: int, duration: float) -> np.ndarray:
    """Block `index` of the source's sound, [2, samples], with the music taken out."""
    name, session = _get_session()
    start = index * BLOCK
    keep = round(min(BLOCK, duration - start) * RATE)
    if name == "tiger":
        # Blocks are whole segments, so each block comes out as if the whole file had been done at once.
        audio = read_audio(source, start, BLOCK)
        return (audio - _tiger_music(session, audio))[:, :keep]
    audio = read_audio(source, start - PAD, BLOCK + 2 * PAD)
    return (audio - _mrx_music(session, audio))[:, round(PAD * RATE) :][:, :keep]


def block_path(folder: Path, index: int) -> Path:
    return folder / "music-free" / f"{index}.flac"


def blocks(start: float, end: float) -> range:
    """The blocks covering [start, end) seconds of a source."""
    return range(int(start // BLOCK), max(int(start // BLOCK) + 1, int(np.ceil(end / BLOCK))))


def make_blocks(source: str, folder: Path, indices: Iterable[int], duration: float,
                progress: Optional[Callable[[int, int], None]] = None,
                cancelled: Optional[Callable[[], bool]] = None) -> None:
    """Writes the music-free blocks that are missing. Safe to run twice at once: each file appears whole."""
    todo = [i for i in sorted(set(indices)) if i * BLOCK < duration and not block_path(folder, i).exists()]
    for done, index in enumerate(todo):
        if cancelled and cancelled():
            raise InterruptedError("Cancelled")
        if progress:
            progress(done, len(todo))
        clean = music_free_block(source, index, duration)
        target = block_path(folder, index)
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(f".{index}.{os.getpid()}.{threading.get_ident()}.flac")
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "f32le", "-ac", "2", "-ar", str(RATE), "-i", "-",
             "-c:a", "flac", "-sample_fmt", "s16", str(partial)],
            input=np.ascontiguousarray(np.clip(clean, -1, 1).T).tobytes(), check=True,
        )
        os.replace(partial, target)
    if progress:
        progress(len(todo), len(todo))
