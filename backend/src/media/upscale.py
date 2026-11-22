"""AI upscaling of the facecam with Real-ESRGAN (the portable ncnn/Vulkan build, on the GPU).

Optional: nothing is installed until a clip asks for it. On Windows the official release is
downloaded once into the state folder; elsewhere put `realesrgan-ncnn-vulkan` on the PATH or
point REALESRGAN_PATH at it.
"""

from pathlib import Path
from typing import Callable, Optional
import hashlib
import os
import shutil
import subprocess
import tempfile
import time
import zipfile

from ..config import get_config
from .diarization import _fetch

_URL = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-windows.zip"
_SHA256 = "abc02804e17982a3be33675e4d471e91ea374e65b70167abc09e31acb412802d"
# realesrgan-x4plus is the one trained on real faces: sharp, but seconds per frame on a slow GPU.
# realesr-animevideov3 is about ten times quicker and smoother-looking. Both are in the download.
UPSCALE_MODEL = os.getenv("UPSCALE_MODEL", "realesrgan-x4plus")


def find_upscaler() -> Optional[Path]:
    """The Real-ESRGAN program, downloading it on Windows the first time."""
    name = "realesrgan-ncnn-vulkan" + (".exe" if os.name == "nt" else "")
    custom = os.getenv("REALESRGAN_PATH") or shutil.which(name)
    if custom:
        return Path(custom)
    directory = Path(get_config().temp_dir) / "tools" / "realesrgan"
    if (directory / name).exists():
        return directory / name
    if os.name != "nt":
        return None
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / "download.zip"
    try:
        _fetch(_URL, archive)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != _SHA256:
            raise RuntimeError("The Real-ESRGAN download did not match its checksum")
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(directory)
    finally:
        archive.unlink(missing_ok=True)
    return directory / name


def upscale_video(
    source: Path,
    output: Path,
    crop: str,
    fps: float,
    tick: Callable[[int, int], None] = lambda done, total: None,
) -> None:
    """Writes `output`: the `crop` (w:h:x:y) of `source`, upscaled, frame for frame, without sound.

    `tick(done, total)` is called while frames are upscaled; raise from it to stop.
    """
    program = find_upscaler()
    if not program:
        raise RuntimeError(
            "Facecam sharpening needs Real-ESRGAN. Install realesrgan-ncnn-vulkan or set REALESRGAN_PATH."
        )
    with tempfile.TemporaryDirectory(prefix="upscale_", dir=output.parent) as temp:
        small, big = Path(temp) / "in", Path(temp) / "out"
        small.mkdir()
        big.mkdir()
        # ponytail: frames are numbered, not timestamped, so a variable-frame-rate source would drift;
        # the editor's clean.mp4 is our own constant-rate encode.
        subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(source), "-vf", f"crop={crop}", "-fps_mode", "passthrough",
             str(small / "%06d.png")],
            check=True, capture_output=True,
        )
        total = len(list(small.iterdir()))
        scale = "4" if UPSCALE_MODEL.startswith("realesrgan") else "2"
        process = subprocess.Popen(
            [str(program), "-i", str(small), "-o", str(big), "-n", UPSCALE_MODEL, "-s", scale, "-f", "png",
             "-m", str(program.parent / "models")],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
        )
        try:
            while process.poll() is None:
                tick(len(os.listdir(big)), total)
                time.sleep(0.5)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
        if process.returncode or len(os.listdir(big)) < total:
            raise RuntimeError("Facecam sharpening failed: " + (process.stderr.read() or "")[-800:])
        partial = output.with_name(f".{output.name}.part.mp4")
        try:
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-framerate", str(fps), "-i", str(big / "%06d.png"),
                 "-c:v", "libx264", "-preset", "fast", "-crf", "14", "-pix_fmt", "yuv420p", str(partial)],
                check=True, capture_output=True,
            )
            os.replace(partial, output)
        finally:
            partial.unlink(missing_ok=True)
