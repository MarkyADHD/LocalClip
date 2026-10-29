"""Ffmpeg helpers for the video pipeline."""

from functools import lru_cache
from typing import List
from typing import Optional
from pathlib import Path
from typing import Tuple
from ..clip_source_map import normalize_source_ranges
from ..config import get_config
import json
import os
import re
import subprocess
from .common import (
    AUDIO_BITRATE,
    CROSSFADE_MAX_SECONDS,
    FINAL_VIDEO_CRF,
    FINAL_VIDEO_PRESET,
    INTERMEDIATE_CRF,
    LOUDNORM_FILTER,
    OUTPUT_FPS,
    logger,
)


def round_to_even(value: int) -> int:
    """Round integer to nearest even number for H.264 compatibility."""
    return value - (value % 2)


def clamp_even(value: int, minimum: int, maximum: int) -> int:
    """Clamp an integer to an even value within inclusive bounds."""
    if maximum < minimum:
        return round_to_even(minimum)
    return round_to_even(max(minimum, min(value, maximum)))


def run_ffmpeg_command(command: List[str], timeout: int = 900) -> subprocess.CompletedProcess:
    """Run ffmpeg/ffprobe and log stderr on failure.

    A failed GPU (NVENC) encode is retried once with the CPU encoder, so a busy
    or missing GPU never costs a clip.
    """
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0 and "h264_nvenc" in command:
        logger.warning("GPU encode failed, retrying on the CPU:\n%s", result.stderr[-2000:])
        return run_ffmpeg_command(cpu_encode_fallback(command), timeout)
    if result.returncode != 0:
        logger.error("Command failed: %s\n%s", " ".join(command), result.stderr[-4000:])
    return result


@lru_cache(maxsize=1)
def nvenc_available() -> bool:
    """True when ffmpeg can encode H.264 on an NVIDIA GPU (checked once).

    VIDEO_ENCODER=cpu forces libx264."""
    if os.getenv("VIDEO_ENCODER", "auto").strip().lower() == "cpu":
        return False
    try:
        probe = subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=s=256x256:d=0.2",
             "-c:v", "h264_nvenc", "-f", "null", "-"],
            capture_output=True,
            timeout=30,
        )
    except Exception:
        return False
    logger.info("Video encoder: %s", "NVENC (GPU)" if probe.returncode == 0 else "libx264 (CPU)")
    return probe.returncode == 0


def _nvenc_args(quality: int, preset: str) -> List[str]:
    # Constant-quality VBR; -cq tracks libx264's -crf closely enough at these levels.
    return ["-c:v", "h264_nvenc", "-preset", preset, "-tune", "hq", "-rc", "vbr",
            "-cq", str(quality), "-b:v", "0"]


def _x264_args(quality: int, preset: str) -> List[str]:
    return ["-c:v", "libx264", "-preset", preset, "-crf", str(quality)]


def cpu_encode_fallback(command: List[str]) -> List[str]:
    """Swap the NVENC video args in an ffmpeg command for libx264 equivalents."""
    i = command.index("h264_nvenc") - 1
    quality = command[command.index("-cq", i) + 1]
    preset = FINAL_VIDEO_PRESET if command[i + 3] != "p1" else "veryfast"
    return command[:i] + _x264_args(int(quality), preset) + command[i + len(_nvenc_args(0, "")):]


def intermediate_video_encode_args() -> List[str]:
    """Video args for the near-lossless cut that later passes read from."""
    if nvenc_available():
        return _nvenc_args(INTERMEDIATE_CRF, "p1") + ["-pix_fmt", "yuv420p"]
    return _x264_args(INTERMEDIATE_CRF, "veryfast") + ["-pix_fmt", "yuv420p"]


def ffprobe_has_audio(video_path: Path) -> bool:
    result = run_ffmpeg_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            str(video_path),
        ],
        timeout=60,
    )
    return result.returncode == 0 and "audio" in result.stdout


# ISO 639-1 → ISO 639-2 (B and T forms) for the languages container tags most
# often carry, so an explicit TRANSCRIPTION_LANGUAGE can pick the matching track.
_ISO_639_2_CODES = {
    "ar": {"ara"}, "bg": {"bul"}, "ca": {"cat"}, "cs": {"ces", "cze"},
    "da": {"dan"}, "de": {"deu", "ger"}, "el": {"ell", "gre"}, "en": {"eng"},
    "es": {"spa"}, "fa": {"fas", "per"}, "fi": {"fin"}, "fr": {"fra", "fre"},
    "he": {"heb"}, "hi": {"hin"}, "hr": {"hrv"}, "hu": {"hun"}, "id": {"ind"},
    "it": {"ita"}, "ja": {"jpn"}, "ko": {"kor"}, "ms": {"msa", "may"},
    "nl": {"nld", "dut"}, "no": {"nor", "nob", "nno"}, "pl": {"pol"},
    "pt": {"por"}, "ro": {"ron", "rum"}, "ru": {"rus"}, "sk": {"slk", "slo"},
    "sv": {"swe"}, "th": {"tha"}, "tr": {"tur"}, "uk": {"ukr"}, "ur": {"urd"},
    "vi": {"vie"}, "zh": {"zho", "chi"},
}
# Commentary, audio-description and dub tracks are never the primary dialogue.
_SECONDARY_AUDIO_DISPOSITIONS = ("comment", "visual_impaired", "hearing_impaired", "dub")


def _audio_language_matches(tag: str, preferred_language: str) -> bool:
    tag = tag.strip().lower()
    base = preferred_language.strip().lower().replace("-", "_").split("_", 1)[0]
    return tag == base or tag in _ISO_639_2_CODES.get(base, set())


def select_audio_stream_index(
    video_path: Path, preferred_language: Optional[str] = None
) -> Optional[int]:
    """Pick the dialogue audio track, as an index for ``0:a:N``, or None if silent.

    Transcription and every render of the source must read the same track;
    ffmpeg's implicit choice (most channels) and ``[0:a]`` (first track) can
    differ on multi-track uploads, desyncing captions from the audio.
    ``preferred_language`` defaults to the configured TRANSCRIPTION_LANGUAGE.
    """
    if preferred_language is None:
        preferred_language = get_config().transcription_language
    result = run_ffmpeg_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=index:stream_tags=language:stream_disposition",
            "-of",
            "json",
            str(video_path),
        ],
        timeout=60,
    )
    if result.returncode != 0:
        return None
    try:
        streams = json.loads(result.stdout or "{}").get("streams") or []
    except ValueError:
        return None
    if not streams:
        return None

    def rank(item: Tuple[int, dict]) -> Tuple[int, int, int, int]:
        position, stream = item
        disposition = stream.get("disposition") or {}
        language = (stream.get("tags") or {}).get("language") or ""
        language_miss = int(
            bool(preferred_language)
            and not _audio_language_matches(language, preferred_language or "")
        )
        secondary = int(any(disposition.get(key) for key in _SECONDARY_AUDIO_DISPOSITIONS))
        not_primary = int(not (disposition.get("default") or disposition.get("original")))
        return language_miss, secondary, not_primary, position

    return min(enumerate(streams), key=rank)[0]


def audio_stream_map_args(audio_stream: Optional[int]) -> List[str]:
    """Explicit ``-map`` args for the first video track plus the chosen audio."""
    args = ["-map", "0:v:0"]
    if audio_stream is not None:
        args += ["-map", f"0:a:{audio_stream}"]
    return args


def ffprobe_video_size(video_path: Path) -> Tuple[int, int]:
    result = run_ffmpeg_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=s=x:p=0",
            str(video_path),
        ],
        timeout=60,
    )
    if result.returncode != 0 or "x" not in result.stdout:
        raise RuntimeError(f"Unable to read video size for {video_path}")
    width, height = result.stdout.strip().split("x", 1)
    return int(width), int(height)


def ffprobe_duration(video_path: Path) -> float:
    result = run_ffmpeg_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Unable to read duration for {video_path}")
    try:
        return max(0.0, float(result.stdout.strip()))
    except ValueError as exc:
        raise RuntimeError(f"Invalid duration for {video_path}") from exc


def ffmpeg_escape_filter_value(value: str) -> str:
    """Escape a value for use as a filter option inside an ffmpeg filtergraph.

    ffmpeg unescapes filter arguments twice: once when splitting the
    filtergraph (special: backslash, quote, ``[ ] , ;``) and once when
    splitting a filter's ``key=value:...`` options (special: backslash,
    quote, colon). Escaping for both levels keeps Windows drive colons,
    backslashes, apostrophes and brackets in paths intact.
    """
    option_level = re.sub(r"([\\':])", r"\\\1", str(value))
    return re.sub(r"([\\'\[\],;])", r"\\\1", option_level)


def ffmpeg_escape_filter_path(path: Path) -> str:
    """Escape a filesystem path for use as an ffmpeg filter option value."""
    return ffmpeg_escape_filter_value(str(path))


def build_final_video_encode_args(
    crf: int = FINAL_VIDEO_CRF,
    preset: str = FINAL_VIDEO_PRESET,
    fps: int = OUTPUT_FPS,
) -> List[str]:
    """Args for the quality-determining final pass (CFR, H.264 High): NVENC on
    an NVIDIA GPU, libx264 otherwise."""
    if nvenc_available():
        return _nvenc_args(crf, "p5") + [
            "-pix_fmt", "yuv420p",
            "-profile:v", "high",
            "-r", str(fps),
            "-g", "120",
        ]
    return _x264_args(crf, preset) + [
        "-pix_fmt", "yuv420p",
        "-profile:v", "high",
        "-level", "4.1",
        "-r", str(fps),
        "-x264-params", "keyint=120:min-keyint=30:scenecut=40",
    ]


def build_audio_output_args(has_audio: bool, loudnorm: bool = True) -> List[str]:
    """Audio encode args (with optional loudness normalisation) or `-an`."""
    if not has_audio:
        return ["-an"]
    args: List[str] = []
    if loudnorm:
        args += ["-af", LOUDNORM_FILTER]
    args += ["-c:a", "aac", "-b:a", AUDIO_BITRATE, "-ar", "48000"]
    return args


def subtitles_filter_fragment(
    ass_path: Path, fonts_dir: Optional[Path] = None
) -> str:
    """ffmpeg `subtitles` filter fragment burning an ASS file (with fonts dir)."""
    fragment = f"subtitles=filename={ffmpeg_escape_filter_path(ass_path)}"
    if fonts_dir:
        fragment += f":fontsdir={ffmpeg_escape_filter_path(fonts_dir)}"
    return fragment


def crossfade_fade_for_ranges(keep_ranges: List[Tuple[float, float]]) -> float:
    """Crossfade duration render_source_ranges will use, or 0.0 for hard concat.

    A single source of truth so caption timing (which compacts the same ranges)
    stays perfectly in sync with the crossfade-shortened video timeline.
    """
    ranges = normalize_source_ranges(keep_ranges)
    if len(ranges) < 2 or len(ranges) > 8:
        return 0.0
    # A hook teaser plays ranges out of source order; hard-cut out of the cold
    # open so persisted source maps (which assume concatenation) stay exact.
    if any(ranges[i + 1][0] < ranges[i][0] for i in range(len(ranges) - 1)):
        return 0.0
    durations = [end - start for start, end in ranges]
    if min(durations) < 0.45:
        return 0.0
    fade = min(CROSSFADE_MAX_SECONDS, min(durations) * 0.5)
    return fade if fade >= 0.06 else 0.0


def _seek_to_first_range(
    keep_ranges: List[Tuple[float, float]],
) -> Tuple[List[str], List[Tuple[float, float]]]:
    """Input-seek to just before the earliest range and shift the ranges to match.

    Without it, trim filters decode the source from 0:00, which costs minutes for
    a clip hours into a VOD. Input seeking is frame-accurate when transcoding.
    """
    offset = max(0.0, min(start for start, _ in keep_ranges) - 1.0)
    if offset <= 0:
        return [], keep_ranges
    return ["-ss", f"{offset:.3f}"], [(start - offset, end - offset) for start, end in keep_ranges]


def render_ranges_crossfade_ffmpeg(
    video_path: Path,
    keep_ranges: List[Tuple[float, float]],
    output_path: Path,
    audio_stream: Optional[int],
    transition: str = "fade",
) -> bool:
    """Stitch kept ranges together with short crossfades instead of hard cuts.

    Turns the abrupt jump cuts left by pause/filler removal into quick, smooth
    dissolves (video xfade + audio acrossfade), which read as intentional,
    polished transitions.
    """
    keep_ranges = normalize_source_ranges(keep_ranges)
    n = len(keep_ranges)
    if n < 2:
        return False
    durations = [end - start for start, end in keep_ranges]
    fade = crossfade_fade_for_ranges(keep_ranges)
    if fade <= 0:
        return False
    has_audio = audio_stream is not None
    seek, keep_ranges = _seek_to_first_range(keep_ranges)

    parts: List[str] = []
    for idx, (start, end) in enumerate(keep_ranges):
        parts.append(
            f"[0:v]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS,"
            f"fps={OUTPUT_FPS},format=yuv420p,setsar=1[v{idx}]"
        )
        if has_audio:
            parts.append(
                f"[0:a:{audio_stream}]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS[a{idx}]"
            )

    cur_v = "[v0]"
    cumulative = durations[0]
    for i in range(1, n):
        offset = cumulative - fade
        out = f"[vx{i}]"
        parts.append(
            f"{cur_v}[v{i}]xfade=transition={transition}:duration={fade:.3f}:"
            f"offset={offset:.3f}{out}"
        )
        cumulative = cumulative + durations[i] - fade
        cur_v = out

    map_args = ["-map", cur_v]
    if has_audio:
        cur_a = "[a0]"
        for i in range(1, n):
            out = f"[ax{i}]"
            parts.append(f"{cur_a}[a{i}]acrossfade=d={fade:.3f}{out}")
            cur_a = out
        map_args += ["-map", cur_a]

    command = [
        "ffmpeg", "-y", *seek, "-i", str(video_path),
        "-filter_complex", ";".join(parts),
        *map_args,
        *intermediate_video_encode_args(),
    ]
    if has_audio:
        command += ["-c:a", "aac", "-b:a", "192k"]
    command += ["-movflags", "+faststart", str(output_path)]
    return run_ffmpeg_command(command, timeout=1800).returncode == 0


def render_source_ranges_ffmpeg(
    video_path: Path,
    keep_ranges: List[Tuple[float, float]],
    output_path: Path,
) -> bool:
    """Render source ranges into one intermediate clip using ffmpeg only."""
    keep_ranges = normalize_source_ranges(keep_ranges)
    if not keep_ranges:
        return False

    audio_stream = select_audio_stream_index(video_path)
    has_audio = audio_stream is not None

    if len(keep_ranges) == 1:
        start, end = keep_ranges[0]
        command = [
            "ffmpeg",
            "-y",
            "-ss",
            f"{start:.3f}",
            "-i",
            str(video_path),
            *audio_stream_map_args(audio_stream),
            "-t",
            f"{end - start:.3f}",
            *intermediate_video_encode_args(),
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        return run_ffmpeg_command(command).returncode == 0

    # Smooth a handful of substantial internal cuts with crossfades; fall back to
    # a hard concat for many tiny fragments (heavy filler edits) or on failure.
    if crossfade_fade_for_ranges(keep_ranges) > 0:
        if render_ranges_crossfade_ffmpeg(
            video_path, keep_ranges, output_path, audio_stream
        ):
            return True
        logger.info("Crossfade stitch failed; falling back to hard concat")

    seek, keep_ranges = _seek_to_first_range(keep_ranges)
    filter_parts: List[str] = []
    concat_inputs: List[str] = []
    for idx, (start, end) in enumerate(keep_ranges):
        filter_parts.append(
            f"[0:v]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS[v{idx}]"
        )
        concat_inputs.append(f"[v{idx}]")
        if has_audio:
            filter_parts.append(
                f"[0:a:{audio_stream}]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS[a{idx}]"
            )
            concat_inputs.append(f"[a{idx}]")

    if has_audio:
        filter_parts.append(
            f"{''.join(concat_inputs)}concat=n={len(keep_ranges)}:v=1:a=1[v][a]"
        )
        map_args = ["-map", "[v]", "-map", "[a]"]
    else:
        filter_parts.append(
            f"{''.join(concat_inputs)}concat=n={len(keep_ranges)}:v=1:a=0[v]"
        )
        map_args = ["-map", "[v]"]

    command = [
        "ffmpeg",
        "-y",
        *seek,
        "-i",
        str(video_path),
        "-filter_complex",
        ";".join(filter_parts),
        *map_args,
        *intermediate_video_encode_args(),
    ]
    if has_audio:
        command.extend(["-c:a", "aac", "-b:a", "192k"])
    command.extend(["-movflags", "+faststart", str(output_path)])
    return run_ffmpeg_command(command, timeout=1800).returncode == 0


def burn_ass_subtitles_ffmpeg(
    input_path: Path,
    ass_path: Path,
    output_path: Path,
    fonts_dir: Optional[Path] = None,
) -> bool:
    video_filter = f"{subtitles_filter_fragment(ass_path, fonts_dir)},setsar=1"

    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-vf",
        video_filter,
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    return run_ffmpeg_command(command).returncode == 0
