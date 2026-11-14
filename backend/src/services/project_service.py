"""Worker jobs for long-form projects: prepare an imported file, export the timeline."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import logging
import shutil
import subprocess
import tempfile
import time

from ..editor_document import atomic_json
from ..project_document import (
    ProjectDocument,
    asset_dir,
    chunk_bounds,
    chunk_command,
    chunk_key,
    project_dir,
    read_assets,
    read_json,
    read_words,
    timeline_words,
    write_chunk_ass,
)
from ..utils.async_helpers import run_in_thread

logger = logging.getLogger(__name__)

WAVE_RATE = 20  # waveform peaks per second
THUMB = (160, 90, 30)  # tile width, height, tiles per row
QUALITY = {"high": 19, "standard": 23, "small": 27}


class Cancelled(Exception):
    pass


def run_ffmpeg(command: list[str], duration: float = 0, progress=None, cancelled=None) -> None:
    """Run ffmpeg to the end, reporting 0..1 progress and stopping when `cancelled()` turns true."""
    with tempfile.TemporaryFile("w+") as log:
        process = subprocess.Popen(
            command[:1] + ["-progress", "pipe:1", "-nostats"] + command[1:],
            stdout=subprocess.PIPE,
            stderr=log,
            text=True,
        )
        try:
            for line in process.stdout:
                if cancelled and cancelled():
                    raise Cancelled()
                if progress and duration and line.startswith("out_time_us="):
                    try:
                        progress(min(1.0, int(line.split("=", 1)[1]) / 1_000_000 / duration))
                    except ValueError:
                        pass
            if process.wait():
                log.seek(0)
                raise RuntimeError("ffmpeg failed: " + log.read()[-1500:])
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()


def probe(path: str) -> dict:
    """Kind, size, frame rate, duration and audio of a media file."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise ValueError("This file is not a video, audio or image file LocalClip can read.")
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    video = next(
        (s for s in streams if s["codec_type"] == "video" and not s.get("disposition", {}).get("attached_pic")),
        None,
    )
    audio = any(s["codec_type"] == "audio" for s in streams)
    duration = float(data.get("format", {}).get("duration") or 0)
    if not video and not audio:
        raise ValueError("This file has no video or audio in it.")
    info = {"hasAudio": audio, "duration": duration, "width": 0, "height": 0, "fps": 0.0}
    if not video:
        return {**info, "kind": "audio"}
    num, den = (video.get("avg_frame_rate") or "0/1").split("/")
    fps = float(num) / float(den) if float(den) else 0.0
    width, height = int(video["width"]), int(video["height"])
    rotation = abs(int(next((d.get("rotation", 0) for d in video.get("side_data_list", []) if "rotation" in d), 0)))
    if rotation in (90, 270):
        width, height = height, width
    still = "image" in data.get("format", {}).get("format_name", "") or "_pipe" in data.get("format", {}).get(
        "format_name", ""
    )
    if still or not duration or not fps:
        return {**info, "kind": "image", "width": width, "height": height, "duration": 0, "hasAudio": False}
    return {**info, "kind": "video", "width": width, "height": height, "fps": round(fps, 3)}


def write_waveform(source: str, target: Path) -> None:
    """One byte per 1/WAVE_RATE s: the loudest sample in that slice, 0..255."""
    import numpy as np

    rate = 4000
    step = rate // WAVE_RATE
    process = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", source, "-vn", "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    with target.open("wb") as out:
        rest = b""
        while True:
            data = process.stdout.read(step * 2 * 4096)
            if not data:
                break
            data = rest + data
            usable = len(data) // (step * 2) * step * 2
            rest = data[usable:]
            if usable:
                samples = np.frombuffer(data[:usable], dtype="<i2").astype(np.int32).reshape(-1, step)
                out.write((np.abs(samples).max(axis=1) >> 7).clip(0, 255).astype(np.uint8).tobytes())
    process.wait()


def write_thumbnails(source: str, target: Path, duration: float) -> dict:
    """A sprite of frames taken every `step` seconds, read by the timeline."""
    width, height, columns = THUMB
    step = max(5.0, duration / 600)
    count = max(1, int(duration / step))
    rows = -(-count // columns)
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y", "-i", source, "-an",
            "-vf",
            f"fps=1/{step:.4f},scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,tile={columns}x{rows}",
            "-frames:v", "1", "-q:v", "5", str(target),
        ],
        capture_output=True,
        check=True,
    )
    return {"step": step, "columns": columns, "width": width, "height": height, "count": count}


def transcribe(source: str, directory: Path) -> None:
    """Word timings for the speech in `source`, written to transcript.json in the asset folder."""
    from ..config import get_config
    from ..media.ffmpeg import select_audio_stream_index
    from ..media.transcription import transcribe_with_whisper

    # transcribe_with_whisper looks for "<name>.transcription.mp3" beside the path it is given,
    # so the audio is extracted here and the recording's own folder is left alone.
    speech = directory / "speech.transcription.mp3"
    stream = select_audio_stream_index(Path(source))
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", source]
        + (["-map", f"0:a:{stream}"] if stream is not None else [])
        + ["-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k", str(speech)],
        capture_output=True,
        check=True,
    )
    config = get_config()
    try:
        result = transcribe_with_whisper(
            directory / "speech", config.whisper_model, config.transcription_language or None
        )
    finally:
        speech.unlink(missing_ok=True)
    words = [
        {"s": round(w["start"], 3), "e": round(max(w["end"], w["start"] + 0.01), 3), "t": w["word"].strip()}
        for segment in result["segments"]
        for w in segment["words"]
        if w["word"].strip()
    ]
    atomic_json(directory / "transcript.json", {"language": result.get("language"), "words": words})


def prepare_asset_files(directory: Path, asset_id: str) -> None:
    from ..media.ffmpeg import intermediate_video_encode_args, nvenc_available

    folder = asset_dir(directory, asset_id)
    meta_path = folder / "meta.json"
    meta = read_json(meta_path)

    def update(**values):
        meta.update(values)
        atomic_json(meta_path, meta)

    source = meta["path"]
    if not Path(source).is_file():
        raise ValueError("The file is no longer where it was. Add it to the project again.")
    update(**probe(source))
    if meta["kind"] == "video":
        encode = (
            ["-c:v", "h264_nvenc", "-preset", "p1", "-rc", "vbr", "-cq", "30", "-b:v", "0"]
            if nvenc_available()
            else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "27"]
        )
        # A small copy with a keyframe every half second, so the preview can jump between cuts smoothly.
        command = [
            "ffmpeg", "-y", "-v", "error", "-i", source,
            "-vf", "scale=-2:'min(720,ih)',fps=30", *encode, "-pix_fmt", "yuv420p", "-g", "15",
            "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-movflags", "+faststart", str(folder / "proxy.mp4"),
        ]
        report = lambda value: update(progress=int(value * 90))  # noqa: E731
        try:
            run_ffmpeg(command, meta["duration"], _throttle(report))
        except RuntimeError:
            if "h264_nvenc" not in command:
                raise
            i = command.index("h264_nvenc") - 1
            run_ffmpeg(
                command[:i] + ["-c:v", "libx264", "-preset", "veryfast", "-crf", "27"] + command[i + 10 :],
                meta["duration"],
                _throttle(report),
            )
        update(thumbs=write_thumbnails(str(folder / "proxy.mp4"), folder / "thumbs.jpg", meta["duration"]))
        if meta["hasAudio"]:
            write_waveform(str(folder / "proxy.mp4"), folder / "waveform.bin")
    elif meta["kind"] == "audio":
        run_ffmpeg(
            ["ffmpeg", "-y", "-v", "error", "-i", source, "-vn", "-c:a", "aac", "-b:a", "160k", "-ac", "2",
             "-movflags", "+faststart", str(folder / "audio.m4a")]
        )
        write_waveform(str(folder / "audio.m4a"), folder / "waveform.bin")
    wants_words = meta["kind"] == "video" and meta["hasAudio"]
    update(status="ready", progress=100, waveRate=WAVE_RATE, transcript="pending" if wants_words else "none")
    if wants_words:
        transcribe_asset_files(directory, asset_id)


def transcribe_asset_files(directory: Path, asset_id: str) -> None:
    folder = asset_dir(directory, asset_id)
    meta = read_json(folder / "meta.json")
    try:
        transcribe(meta["path"], folder)
        state = {"transcript": "ready"}
    except Exception:
        logger.exception("Transcription failed for asset %s", asset_id)
        state = {"transcript": "failed"}
    # Read again: the asset may have been renamed while Whisper ran.
    atomic_json(folder / "meta.json", {**(read_json(folder / "meta.json") or meta), **state})


def _throttle(callback, seconds: float = 1.0):
    last = [0.0]

    def wrapped(value):
        if time.monotonic() - last[0] >= seconds:
            last[0] = time.monotonic()
            callback(value)

    return wrapped


async def prepare_asset(ctx, project_id: str, asset_id: str):
    from ..config import get_config

    directory = project_dir(get_config().temp_dir, project_id)
    folder = asset_dir(directory, asset_id)
    meta = read_json(folder / "meta.json")
    if not meta:
        return
    try:
        if meta.get("url") and not meta.get("path"):
            from .video_service import VideoService

            path = await VideoService.download_video(meta["url"])
            if not path:
                raise ValueError("Could not download that link. Check it and try again.")
            meta["path"] = str(path)
            if meta.get("name") == meta["url"]:
                meta["name"] = await VideoService.get_video_title(meta["url"])
            atomic_json(folder / "meta.json", meta)
        await run_in_thread(prepare_asset_files, directory, asset_id)
    except Exception as error:
        logger.exception("Could not prepare asset %s", asset_id)
        message = str(error) if isinstance(error, ValueError) else "Could not read this file. Try another format."
        atomic_json(folder / "meta.json", {**(read_json(folder / "meta.json") or meta), "status": "failed", "error": message})


async def transcribe_asset(ctx, project_id: str, asset_id: str):
    from ..config import get_config

    await run_in_thread(transcribe_asset_files, project_dir(get_config().temp_dir, project_id), asset_id)


# ---------------------------------------------------------------- export


def export_encode_args(quality: str, fps: float) -> list[str]:
    from ..media.ffmpeg import _nvenc_args, _x264_args, nvenc_available

    cq = QUALITY.get(quality, QUALITY["standard"])
    common = ["-pix_fmt", "yuv420p", "-profile:v", "high", "-g", str(max(1, round(fps * 2)))]
    return (_nvenc_args(cq, "p5") if nvenc_available() else _x264_args(cq, "veryfast")) + common


def render_project(directory: Path, job_id: str) -> None:
    from ..clip_editor import _escape_filter_path
    from ..media.ffmpeg import cpu_encode_fallback
    from ..video_utils import ass_fonts_dir

    exports = directory / "exports"
    chunks = exports / "chunks"
    chunks.mkdir(parents=True, exist_ok=True)
    status_path = exports / f"job-{job_id}.json"
    cancel_path = exports / f"cancel-{job_id}"
    request = read_json(exports / f"request-{job_id}.json")
    document = ProjectDocument.model_validate(request["document"])
    assets = read_assets(directory)
    if document.duration <= 0:
        raise ValueError("There is nothing on the timeline to export.")
    cache: dict[str, list[dict]] = {}
    words = timeline_words(document, lambda a: cache.setdefault(a, read_words(directory, a) if a in assets else []))
    fonts = ass_fonts_dir(document.captions.font)
    encode = export_encode_args(request.get("quality", "standard"), document.fps)
    bounds = chunk_bounds(document)
    cancelled = cancel_path.exists
    done = [0]

    def render(index: int) -> Path:
        c0, c1 = bounds[index]
        if cancelled():
            raise Cancelled()
        ass = chunks / f"{job_id}-{index}.ass"
        has_text = write_chunk_ass(ass, document, words, c0, c1)
        try:
            command = chunk_command(
                document, assets, c0, c1,
                _escape_filter_path(ass) if has_text else None,
                _escape_filter_path(fonts) if fonts else None,
                encode, "",
            )
            target = chunks / f"{chunk_key(command, ass.read_text(encoding='utf-8') if has_text else '')}.mkv"
            if not target.exists():
                # Rendered under a temporary name, so a cancelled chunk is never mistaken for a finished one.
                part = target.with_suffix(".part.mkv")
                command[-1] = str(part)
                try:
                    run_ffmpeg(command, cancelled=cancelled)
                except RuntimeError:
                    if "h264_nvenc" not in command:
                        raise
                    run_ffmpeg(cpu_encode_fallback(command), cancelled=cancelled)
                part.replace(target)
        finally:
            ass.unlink(missing_ok=True)
        done[0] += 1
        atomic_json(status_path, {"status": "rendering", "progress": int(done[0] / len(bounds) * 95)})
        return target

    atomic_json(status_path, {"status": "rendering", "progress": 0})
    # Two chunks at a time, like clip rendering.
    with ThreadPoolExecutor(max_workers=2) as pool:
        files = list(pool.map(render, range(len(bounds))))
    listing = exports / f"list-{job_id}.txt"
    listing.write_text("".join(f"file '{f.as_posix()}'\n" for f in files), encoding="utf-8")
    output = exports / f"{job_id}.mp4"
    try:
        run_ffmpeg(
            ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
             "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(output)],
            cancelled=cancelled,
        )
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    finally:
        listing.unlink(missing_ok=True)
    # The finished file replaces the chunks; they are only kept after a failure, to resume from.
    shutil.rmtree(chunks, ignore_errors=True)


async def export_project(ctx, project_id: str, job_id: str):
    from ..config import get_config

    directory = project_dir(get_config().temp_dir, project_id)
    status_path = directory / "exports" / f"job-{job_id}.json"
    try:
        await run_in_thread(render_project, directory, job_id)
        atomic_json(status_path, {"status": "completed", "progress": 100})
    except Cancelled:
        atomic_json(status_path, {"status": "cancelled", "progress": 0})
    except Exception as error:
        logger.exception("Project export failed")
        message = str(error) if isinstance(error, ValueError) else "Export failed. Your project is safe; try again."
        atomic_json(status_path, {"status": "failed", "progress": 0, "error": message})
