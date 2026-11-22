"""Splits a clip's sound into the voice and everything else (game, music), on this PC.

Spleeter's two-stem model through sherpa-onnx on the CPU: no torch, about a second per
half minute. The model (35 MB) is downloaded once into the state folder.
"""

from pathlib import Path
from typing import Tuple
import os
import subprocess
import tarfile
import threading
import wave

from ..config import get_config
from .diarization import _RELEASES, _fetch

# ponytail: Spleeter leaves a little music under the voice; a UVR MDX-Net model (also in
# sherpa-onnx) is cleaner but far slower on the CPU. Swap it in here if the bleed is audible.
_MODEL = "sherpa-onnx-spleeter-2stems-fp16"
_RATE = 44100
_lock = threading.Lock()
_separator = None


def _get_separator():
    global _separator
    if _separator is None:
        import sherpa_onnx

        directory = Path(get_config().temp_dir) / "models" / "stems"
        if not (directory / _MODEL / "vocals.fp16.onnx").exists():
            directory.mkdir(parents=True, exist_ok=True)
            archive = directory / "model.tar.bz2"
            _fetch(f"{_RELEASES}/source-separation-models/{_MODEL}.tar.bz2", archive)
            with tarfile.open(archive) as tar:
                tar.extractall(directory, filter="data")
            archive.unlink(missing_ok=True)
        _separator = sherpa_onnx.OfflineSourceSeparation(
            sherpa_onnx.OfflineSourceSeparationConfig(
                model=sherpa_onnx.OfflineSourceSeparationModelConfig(
                    spleeter=sherpa_onnx.OfflineSourceSeparationSpleeterModelConfig(
                        vocals=str(directory / _MODEL / "vocals.fp16.onnx"),
                        accompaniment=str(directory / _MODEL / "accompaniment.fp16.onnx"),
                    ),
                    num_threads=max(1, min(4, (os.cpu_count() or 2) // 2)),
                )
            )
        )
    return _separator


def split_voice(media_path: Path, directory: Path) -> Tuple[Path, Path]:
    """(voice.wav, game.wav) for the file's sound, made once and kept in `directory`."""
    import numpy as np

    voice, game = directory / "voice.wav", directory / "game.wav"
    with _lock:
        if voice.exists() and game.exists():
            return voice, game
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(media_path), "-vn", "-f", "f32le", "-ac", "2", "-ar", str(_RATE), "-"],
            capture_output=True, check=True,
        ).stdout
        samples = np.frombuffer(raw, np.float32).reshape(-1, 2).T
        stems = _get_separator().process(_RATE, np.ascontiguousarray(samples)).stems
        for path, stem in ((voice, stems[0]), (game, stems[1])):
            pcm = (np.clip(np.array(stem.data).T, -1, 1) * 32767).astype("<i2")
            partial = path.with_name(f".{path.name}.part")
            with wave.open(str(partial), "wb") as out:
                out.setnchannels(2)
                out.setsampwidth(2)
                out.setframerate(_RATE)
                out.writeframes(pcm.tobytes())
            os.replace(partial, path)
    return voice, game
