"""Versioned, non-destructive clip drafts and deterministic render instructions.

Editor files live beside generated media on the shared temp volume. Originals are
never modified. A file lock and revision check protect concurrent API workers.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Literal
import hashlib
import json
import os
import re
import subprocess
import time
import uuid

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .media.common import DENOISE_FILTER
from .media.diarization import MAX_SPEAKERS, SPEAKER_COLORS

HexColor = Field(pattern=r"^#[0-9a-fA-F]{6}$")


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Segment(Model):
    id: str = Field(min_length=1, max_length=100)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    speed: float = Field(default=1, ge=0.25, le=1)  # below 1 plays the segment in slow motion

    @model_validator(mode="after")
    def ordered(self):
        if self.end - self.start < 0.04:
            raise ValueError("Each segment must be at least one frame long")
        return self

    @property
    def length(self) -> float:
        """Seconds the segment lasts in the edited clip."""
        return (self.end - self.start) / self.speed


class Punch(Model):
    """A snap zoom on the picture between two source times."""

    id: str = Field(min_length=1, max_length=100)
    start: float = Field(ge=0)
    end: float = Field(gt=0)

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start:
            raise ValueError("A punch-in must end after it starts")
        return self


class Word(Model):
    id: str = Field(min_length=1, max_length=100)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str = Field(max_length=120)
    highlight: bool = False
    bleep: bool = False  # beep over the word and star it out in the caption
    speaker: int = Field(default=0, ge=0, lt=MAX_SPEAKERS)  # 0 talks most; picks the caption colour

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start:
            raise ValueError("Caption end must follow its start")
        return self


class CaptionStyle(Model):
    enabled: bool = True
    # Bundled fonts (file stems in backend/fonts); keep in sync with CAPTION_FONTS in document.ts.
    font: Literal[
        "TikTokSans-Regular",
        "TikTokSans-Bold",
        "Poppins-ExtraBold",
        "THEBOLDFONT",
        "Anton-Regular",
        "BebasNeue-Regular",
        "ArchivoBlack-Regular",
        "Bangers-Regular",
    ] = "Poppins-ExtraBold"
    size: int = Field(default=54, ge=20, le=100)
    color: str = Field(default="#FFFFFF", pattern=r"^#[0-9a-fA-F]{6}$")
    accent: str = Field(default="#FACC15", pattern=r"^#[0-9a-fA-F]{6}$")
    y: float = Field(default=0.78, ge=0.1, le=0.9)
    background: bool = True
    wordsPerLine: int = Field(default=4, ge=1, le=8)
    uppercase: bool = False
    outline: float = Field(default=4, ge=0, le=12)  # % of the font size
    active: bool = False  # colour the word being spoken
    # Colours of speakers 1, 2, ... (speaker 0 uses `color`).
    speakerColors: list[Annotated[str, HexColor]] = Field(
        default_factory=lambda: list(SPEAKER_COLORS), max_length=MAX_SPEAKERS - 1
    )

    def word_color(self, word: dict) -> str:
        speaker = word.get("speaker") or 0
        return self.speakerColors[speaker - 1] if 0 < speaker <= len(self.speakerColors) else self.color


class Region(Model):
    """Part of the source frame, normalised 0..1."""

    x: float = Field(default=0, ge=0, le=1)
    y: float = Field(default=0.6, ge=0, le=1)
    w: float = Field(default=0.3, ge=0.05, le=1)
    h: float = Field(default=0.4, ge=0.05, le=1)


class Framing(Model):
    aspect: Literal["vertical", "square", "original"] = "vertical"
    fit: Literal["contain", "cover"] = "cover"
    zoom: float = Field(default=1, ge=1, le=3)
    x: float = Field(default=0.5, ge=0, le=1)
    y: float = Field(default=0.5, ge=0, le=1)
    # crop: one crop of the frame. The others stack or float the facecam (`cam`) with the gameplay.
    layout: Literal["crop", "cam_top", "cam_bottom", "floating"] = "crop"
    cam: Region = Field(default_factory=Region)
    sharpCam: bool = False  # AI-upscale the facecam for the export (slow; needs Real-ESRGAN)


class Effects(Model):
    brightness: float = Field(default=100, ge=40, le=180)
    contrast: float = Field(default=100, ge=40, le=180)
    saturation: float = Field(default=100, ge=0, le=220)
    blur: float = Field(default=0, ge=0, le=8)
    hue: float = Field(default=0, ge=-180, le=180)


def censor(text: str) -> str:
    """f*** : keep the first letter of each word, star the rest."""
    return re.sub(r"(?<=\w)\w", "*", text)


class EditDocument(Model):
    version: Literal[1] = 1
    segments: list[Segment] = Field(min_length=1, max_length=100)
    words: list[Word] = Field(default_factory=list, max_length=5000)
    captions: CaptionStyle = Field(default_factory=CaptionStyle)
    framing: Framing = Field(default_factory=Framing)
    effects: Effects = Field(default_factory=Effects)
    volume: float = Field(default=1, ge=0, le=2)
    muted: bool = False
    title: str = Field(default="", max_length=80)  # hook title at the top; empty for none
    titleSeconds: float = Field(default=0, ge=0, le=600)  # how long the title stays; 0 for the whole clip
    cleanVoice: bool = False  # take rumble and steady hiss out of the sound
    punches: list[Punch] = Field(default_factory=list, max_length=50)
    gameVolume: float = Field(default=1, ge=0, le=2)  # game and music under the voice; 1 leaves the mix alone

    @property
    def duration(self) -> float:
        return sum(s.length for s in self.segments)

    def validate_duration(self, duration: float):
        if any(s.end > duration + 0.05 for s in self.segments):
            raise ValueError("An edit extends past the original clip")
        if any(w.end > duration + 0.05 for w in self.words):
            raise ValueError("A caption extends past the original clip")
        if len({s.id for s in self.segments}) != len(self.segments) or len(
            {w.id for w in self.words}
        ) != len(self.words):
            raise ValueError("Editor item IDs must be unique")
        return self


def editor_dir(temp_dir: str, task_id: str, clip_id: str, filename: str) -> Path:
    # No request-controlled string is ever used as a path component.
    key = hashlib.sha256(f"{task_id}:{clip_id}:{filename}".encode()).hexdigest()
    return Path(temp_dir) / "editor" / key


def atomic_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}")
    try:
        temporary.write_text(json.dumps(value, allow_nan=False))
        for attempt in range(20):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                # Windows refuses to replace a file while a status poll is reading it.
                if attempt == 19:
                    raise
                time.sleep(0.05)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def editor_lock(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".lock").open("a") as handle:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            while True:
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                    break
                except OSError:  # LK_LOCK gives up after ~10 s; keep waiting like flock does
                    pass
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            return
        import fcntl

        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


class RevisionConflict(ValueError):
    pass


def save_document(
    directory: Path, document: EditDocument, revision: int, duration: float
):
    document.validate_duration(duration)
    with editor_lock(directory):
        path = directory / "draft.json"
        current = json.loads(path.read_text()) if path.exists() else {"revision": 0}
        if revision != current["revision"]:
            raise RevisionConflict(
                "This clip was edited in another tab. Reload the saved draft before continuing."
            )
        payload = {"revision": revision + 1, "document": document.model_dump()}
        atomic_json(path, payload)
        return payload


def output_size(document: EditDocument, width: int, height: int):
    if document.framing.aspect == "square":
        return 1080, 1080
    if document.framing.aspect == "vertical":
        return 1080, 1920
    scale = min(1, 1920 / max(width, height))
    return max(2, int(width * scale) // 2 * 2), max(2, int(height * scale) // 2 * 2)


def mapped(document: EditDocument, items) -> list[dict]:
    """Items with source `start`/`end` times, moved onto the edited timeline (cut, repeated, slowed)."""
    result = []
    cursor = 0.0
    ordered = sorted(items, key=lambda item: item.start)
    for segment in document.segments:
        for item in ordered:
            start, end = max(segment.start, item.start), min(segment.end, item.end)
            if end > start:
                result.append(
                    {
                        **item.model_dump(),
                        "start": cursor + (start - segment.start) / segment.speed,
                        "end": cursor + (end - segment.start) / segment.speed,
                    }
                )
        cursor += segment.length
    return result


def mapped_words(document: EditDocument):
    return mapped(document, [w for w in document.words if w.text.strip()])


PUNCH_ZOOM = 1.25  # how far a punch-in zooms; same in render.ts
# Height of the point a punch-in zooms towards: the face, or the facecam pane. Same in render.ts.
PUNCH_Y = {"crop": 0.4, "cam_top": 0.2, "cam_bottom": 0.8, "floating": 0.3}


def punch_filter(document: EditDocument, width: int, height: int) -> str:
    """filter_complex from [framed] to [punched]: the picture zoomed while a punch-in is on."""
    spans = mapped(document, document.punches)
    if not spans:
        return "[framed]null[punched]"
    framing = document.framing
    y = PUNCH_Y["crop" if framing.aspect == "original" else framing.layout]
    zw, zh = _even(width * PUNCH_ZOOM), _even(height * PUNCH_ZOOM)
    on = "+".join(f"between(t,{p['start']:.3f},{p['end']:.3f})" for p in spans)
    return (
        f"[framed]split[punch0][punch1];"
        f"[punch1]scale={zw}:{zh},crop={width}:{height}:{(zw - width) / 2}:{(zh - height) * y}[punchz];"
        f"[punch0][punchz]overlay=enable='{on}'[punched]"
    )


def caption_groups(words: list[dict], count: int):
    groups, group = [], []
    for word in words:
        if group and (len(group) >= count or word["start"] - group[-1]["end"] > 0.6):
            groups.append(group)
            group = []
        group.append(word)
    if group:
        groups.append(group)
    return groups


def _em_scale(font_path) -> float:
    """libass sizes a font by its line height (OS/2 win ascent + descent); the preview's canvas sizes
    it by the em square. This factor makes an ASS Fontsize draw glyphs as large as the preview does."""
    import struct

    try:
        data = Path(font_path).read_bytes()
        tables = {
            data[12 + i * 16 : 16 + i * 16]: struct.unpack(">I", data[20 + i * 16 : 24 + i * 16])[0]
            for i in range(struct.unpack(">H", data[4:6])[0])
        }
        units = struct.unpack(">H", data[tables[b"head"] + 18 : tables[b"head"] + 20])[0]
        ascent, descent = struct.unpack(">HH", data[tables[b"OS/2"] + 74 : tables[b"OS/2"] + 78])
        return (ascent + descent) / units
    except Exception:  # not a plain TrueType/OpenType file: keep libass's own sizing
        return 1.0


TITLE_Y = 0.14  # where the hook title sits; same in render.ts
CAM_SHARE = 0.4  # facecam band height in the stacked layouts (same as the stream templates)


def _even(value: float) -> int:
    return max(2, round(value / 2) * 2)


def cam_crop(framing: Framing, sw: int, sh: int, width: int, height: int) -> str | None:
    """The facecam's part of the source frame as ffmpeg's w:h:x:y, or None for a layout without a facecam pane."""
    layout = "crop" if framing.aspect == "original" else framing.layout
    if layout == "crop":
        return None
    pw = _even(width * 0.6) if layout == "floating" else width
    ph = _even(pw * 460 / 648) if layout == "floating" else _even(height * CAM_SHARE)
    r, aspect = framing.cam, pw / ph
    w, h = r.w * sw, r.h * sh
    w, h = (h * aspect, h) if w / h < aspect else (w, w / aspect)
    if w > sw:
        w, h = sw, sw / aspect
    if h > sh:
        w, h = sh * aspect, sh
    w, h = int(w) // 2 * 2, int(h) // 2 * 2
    x = min(max((r.x + r.w / 2) * sw - w / 2, 0), sw - w)
    y = min(max((r.y + r.h / 2) * sh - h / 2, 0), sh - h)
    return f"{w}:{h}:{int(x)}:{int(y)}"


def layout_filter(framing: Framing, sw: int, sh: int, width: int, height: int, cam_video: bool = False) -> str:
    """filter_complex from [video] (source size) to [framed] (output size); mirrors drawLayout in render.ts.

    With `cam_video`, the facecam comes ready-cropped (and upscaled) from [camvideo] instead.
    """
    layout = "crop" if framing.aspect == "original" else framing.layout
    cam_in = "[camvideo]" if cam_video else "[c0]"

    def scaled(pw: int, ph: int, fit=max):
        scale = fit(pw / sw, ph / sh) * framing.zoom
        return _even(sw * scale), _even(sh * scale)

    def cover(pw: int, ph: int) -> str:
        rw, rh = scaled(pw, ph)
        return f"scale={rw}:{rh},crop={pw}:{ph}:{(rw - pw) * framing.x}:{(rh - ph) * framing.y}"

    def cam(pw: int, ph: int) -> str:
        if cam_video:
            return f"scale={pw}:{ph}:flags=lanczos"
        return f"crop={cam_crop(framing, sw, sh, width, height)},scale={pw}:{ph}"

    bw, bh = _even(width / 4), _even(height / 4)
    blur = f"scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh},gblur=sigma=8,scale={width}:{height}"
    if layout == "crop":
        rw, rh = scaled(width, height, max if framing.fit == "cover" else min)
        cw, ch = min(width, rw), min(height, rh)
        crop = f"scale={rw}:{rh},crop={cw}:{ch}:{(rw - cw) * framing.x}:{(rh - ch) * framing.y}"
        if (cw, ch) == (width, height):
            return f"[video]{crop},setsar=1[framed]"
        return (
            f"[video]split[bg0][fg0];[bg0]{blur}[bg];[fg0]{crop}[fg];"
            f"[bg][fg]overlay={(width - cw) * framing.x}:{(height - ch) * framing.y},setsar=1[framed]"
        )
    if layout == "floating":
        band = min(height, _even(width * sh / sw))
        top = (height - band) / 2
        cw = _even(width * 0.6)
        ch = _even(cw * 460 / 648)
        return (
            f"[video]split{'' if cam_video else '=3'}[bg0][g0]{'' if cam_video else '[c0]'};"
            f"[bg0]{blur}[bg];[g0]scale={width}:{band}[g];"
            f"{cam_in}{cam(cw, ch)}[c];[bg][g]overlay=0:{top}[t];"
            f"[t][c]overlay={(width - cw) / 2}:{max(0, top - ch - height / 80)},setsar=1[framed]"
        )
    cam_h = _even(height * CAM_SHARE)
    order = "[c][g]" if layout == "cam_top" else "[g][c]"
    return (
        f"{'[video]' if cam_video else '[video]split[g0][c0];[g0]'}{cover(width, height - cam_h)}[g];"
        f"{cam_in}{cam(width, cam_h)}[c];{order}vstack,setsar=1[framed]"
    )


def ass_header(style: CaptionStyle, width: int, height: int, name: str = "Default") -> tuple[str, str]:
    """(script header, style line) for one caption/text style; sizes match the canvas preview."""
    from .clip_editor import _ass_color
    from .font_registry import get_font_family_name, find_font_path

    font_path = find_font_path(style.font)
    em = style.size * width / 1080
    size = em * (_em_scale(font_path) if font_path else 1)
    font = (get_font_family_name(font_path) if font_path else None) or "Arial"
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
"""
    line = f"Style: {name},{font},{size},{_ass_color(style.color)},&H000000FF,&H00101010,&H80101010,0,0,0,0,100,100,0,0,{3 if style.background else 1},{max(1, em * 0.1) if style.background else em * style.outline / 100},0,5,{int(width * 0.08)},{int(width * 0.08)},0,1\n"
    return header, line


ASS_EVENTS = "\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"


def ass_event(style: CaptionStyle, width, height, start, end, y, words, accent, x=0.5, name="Default", tags=""):
    """One Dialogue line: `words` centred on (x, y); accent(i) lights word i."""
    from .clip_editor import _ass_color, _ass_timestamp, _escape_ass_text

    def text_of(word):
        text = censor(word["text"]) if word.get("bleep") else word["text"]
        text = text.upper() if style.uppercase else text
        return _escape_ass_text(text).replace("\n", " ").replace("\r", " ")

    text = " ".join(
        "{\\c" + _ass_color(style.accent if accent(i) else style.word_color(word)) + "}" + text_of(word)
        for i, word in enumerate(words)
    )
    return (
        f"Dialogue: 0,{_ass_timestamp(start)},{_ass_timestamp(end)},{name},,0,0,0,,"
        f"{{\\pos({width * x:.2f},{height * y:.2f}){tags}}}{text}\n"
    )


def caption_events(style: CaptionStyle, words: list[dict]):
    """(start, end, group, accent) for every caption on screen, from timeline-mapped words."""
    events = []
    for group in caption_groups(words, style.wordsPerLine):
        end = max(w["end"] for w in group)
        if not style.active:
            events.append((group[0]["start"], end, group, lambda i, g=group: g[i].get("highlight", False)))
            continue
        # One event per spoken word; it stays lit until the next word starts.
        for spoken, word in enumerate(group):
            until = group[spoken + 1]["start"] if spoken + 1 < len(group) else end
            if until > word["start"]:
                events.append(
                    (word["start"], until, group, lambda i, g=group, s=spoken: g[i].get("highlight", False) or i == s)
                )
    return events


def write_ass(path: Path, document: EditDocument, width: int, height: int):
    style = document.captions
    header, line = ass_header(style, width, height)
    lines = []
    if document.title.strip():
        total = document.duration
        words = [{"text": text} for text in document.title.split()]
        until = min(total, document.titleSeconds or total)
        lines.append(ass_event(style, width, height, 0, until, TITLE_Y, words, lambda i: False))
    if style.enabled:
        for start, end, group, accent in caption_events(style, mapped_words(document)):
            lines.append(ass_event(style, width, height, start, end, style.y, group, accent))
    path.write_text(header + line + ASS_EVENTS + "".join(lines))


def run_render(
    command: list[str],
    directory: Path,
    job_id: str,
    duration: float,
    cancel_path: Path | None = None,
):
    """Poll a cancellable child without buffering unbounded ffmpeg logs."""
    status_path = directory / f"job-{job_id}.json"
    progress_path = directory / f"progress-{job_id}.txt"
    log_path = directory / f"log-{job_id}.txt"
    cancel_path = cancel_path or directory / f"cancel-{job_id}"
    try:
        with log_path.open("w+") as log:
            process = subprocess.Popen(
                command[:1]
                + ["-progress", str(progress_path), "-nostats"]
                + command[1:],
                stdout=subprocess.DEVNULL,
                stderr=log,
            )
            try:
                while process.poll() is None:
                    if cancel_path.exists():
                        raise InterruptedError("Export cancelled")
                    percent = 0
                    if progress_path.exists():
                        for line in progress_path.read_text().splitlines():
                            if line.startswith("out_time_us="):
                                try:
                                    percent = min(
                                        99,
                                        int(
                                            float(line.split("=", 1)[1])
                                            / 1_000_000
                                            / duration
                                            * 100
                                        ),
                                    )
                                except ValueError:
                                    pass
                    atomic_json(
                        status_path, {"status": "rendering", "progress": percent}
                    )
                    time.sleep(0.25)
                if process.returncode:
                    log.seek(0)
                    raise RuntimeError("Video rendering failed: " + log.read()[-1500:])
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
    finally:
        # Only after the log is closed: Windows cannot delete an open file.
        progress_path.unlink(missing_ok=True)
        log_path.unlink(missing_ok=True)


# ponytail: ffmpeg's motion interpolation is slow and can smear fast action; RIFE if it shows.
SLOWMO_MODE = os.getenv("SLOWMO_MODE", "mci")  # "blend" is quicker and softer


def _atempo(speed: float) -> str:
    """atempo only goes down to half speed per filter."""
    parts = []
    while speed < 0.5:
        parts.append("atempo=0.5")
        speed /= 0.5
    return ",".join(parts + [f"atempo={speed}"])


def render_document(
    directory: Path,
    job_id: str,
    document: EditDocument,
    preset: str,
    cancel_path: Path | None = None,
):
    from .clip_editor import _ffprobe_size, _escape_filter_path
    from .video_utils import ass_fonts_dir

    source = directory / "clean.mp4"
    sw, sh = _ffprobe_size(source)
    fps = json.loads((directory / "asset.json").read_text())["fps"] if (directory / "asset.json").exists() else 30
    width, height = output_size(document, sw, sh)
    fx = document.effects
    # CSS brightness/contrast use RGB multiplication followed by a midpoint shift.
    gain = fx.brightness / 100 * fx.contrast / 100
    offset = 128 * (1 - fx.contrast / 100)
    effects = f"lutrgb=r='clip(val*{gain}+{offset},0,255)':g='clip(val*{gain}+{offset},0,255)':b='clip(val*{gain}+{offset},0,255)',hue=h={fx.hue}:s={fx.saturation / 100}"
    if fx.blur:
        effects += f",gblur=sigma={fx.blur * width / 1080}"
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            str(source),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    audio = bool(probe.stdout.strip())
    filters, joins = [], []
    inputs = ["-i", str(source)]
    crop = cam_crop(document.framing, sw, sh, width, height) if document.framing.sharpCam else None
    if crop:
        # The facecam, upscaled once and kept beside the clip; cut and slowed exactly like the main video.
        from .media.upscale import UPSCALE_MODEL, upscale_video

        cam_path = directory / f"cam-{hashlib.sha256(f'{crop}:{UPSCALE_MODEL}'.encode()).hexdigest()[:12]}.mp4"
        if not cam_path.exists():
            cancel = cancel_path or directory / f"cancel-{job_id}"

            def tick(done: int, total: int):
                if cancel.exists():
                    raise InterruptedError("Export cancelled")
                atomic_json(
                    directory / f"job-{job_id}.json",
                    {"status": "rendering", "progress": min(99, done * 100 // max(1, total))},
                )

            upscale_video(source, cam_path, crop, fps, tick)
        inputs += ["-i", str(cam_path)]
    cam_joins = []
    sound = ["[0:a]"] * len(document.segments)
    if audio and document.gameVolume != 1 and not document.muted:
        # Voice and game sound apart, so the game and its music can be turned down under the voice.
        from .media.stems import split_voice

        first = len(inputs) // 2
        for stem in split_voice(source, directory):
            inputs += ["-i", str(stem)]
        sound = [f"[mix{index}]" for index in range(len(document.segments))]
        filters.append(
            f"[{first + 1}:a]volume={document.gameVolume}[game];[{first}:a][game]amix=inputs=2:normalize=0,"
            f"aresample=48000,asplit={len(sound)}" + "".join(sound)
        )
    for index, segment in enumerate(document.segments):
        slow = segment.speed < 1
        # Slow motion: stretch the frames in time, then draw the missing ones in between.
        filters.append(
            f"[0:v]trim=start={segment.start}:end={segment.end},setpts=(PTS-STARTPTS)/{segment.speed}"
            + (f",minterpolate=fps={fps}:mi_mode={SLOWMO_MODE}" if slow else "")
            + f"[v{index}]"
        )
        joins.append(f"[v{index}]")
        if crop:
            filters.append(filters[-1].replace("[0:v]", "[1:v]").replace(f"[v{index}]", f"[c{index}]"))
            cam_joins.append(f"[c{index}]")
        if audio:
            filters.append(
                f"{sound[index]}atrim=start={segment.start}:end={segment.end},asetpts=PTS-STARTPTS"
                + (f",{_atempo(segment.speed)}" if slow else "")
                + f"[a{index}]"
            )
            joins.append(f"[a{index}]")
    filters.append(
        "".join(joins)
        + f"concat=n={len(document.segments)}:v=1:a={int(audio)}[video]"
        + ("[audio]" if audio else "")
    )
    ass = directory / f"captions-{job_id}.ass"
    write_ass(ass, document, width, height)
    fonts = ass_fonts_dir(document.captions.font)
    if crop:
        filters.append("".join(cam_joins) + f"concat=n={len(cam_joins)}:v=1:a=0[camvideo]")
    filters.append(layout_filter(document.framing, sw, sh, width, height, cam_video=bool(crop)))
    filters.append(punch_filter(document, width, height))
    filters.append(
        f"[punched]{effects},ass={_escape_filter_path(ass)}:fontsdir={_escape_filter_path(fonts or Path('fonts'))}[outv]"
    )
    total = document.duration
    tracks = []
    if audio:
        voice = "[audio]" + (f"{DENOISE_FILTER}," if document.cleanVoice else "")
        voice += f"volume={0 if document.muted else document.volume}"
        bleeps = "+".join(
            f"between(t,{max(0, w['start'] - 0.05):.3f},{w['end'] + 0.05:.3f})"
            for w in mapped_words(document)
            if w["bleep"]
        )
        if bleeps and not document.muted:
            # Silence the word and put a 1 kHz tone over it (sine is 1/8 scale, so x2 = a clear -12 dB beep).
            voice += f",volume=0:enable='{bleeps}'"
            filters.append(
                f"sine=frequency=1000:sample_rate=48000:duration={total:.3f},"
                f"volume=2,volume=0:enable='not({bleeps})'[beep]"
            )
            tracks.append("[beep]")
        filters.append(voice + "[voice]")
        tracks.append("[voice]")
    if len(tracks) > 1:
        filters.append(
            "".join(tracks) + f"amix=inputs={len(tracks)}:normalize=0[outa]"
        )
    elif tracks:
        filters.append(f"{tracks[0]}anull[outa]")
    output = directory / f"export-{job_id}.mp4"
    command = [
        "ffmpeg",
        "-y",
        *inputs,
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[outv]",
    ]
    if tracks:
        command += ["-map", "[outa]", "-c:a", "aac", "-b:a", "192k"]
    command += [
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "18",
        "-maxrate",
        "12M" if preset == "reels" else "10M",
        "-bufsize",
        "24M",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output),
    ]
    try:
        cancel_path = cancel_path or directory / f"cancel-{job_id}"
        run_render(command, directory, job_id, total, cancel_path)
        if cancel_path.exists():
            raise InterruptedError("Export cancelled")
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    finally:
        ass.unlink(missing_ok=True)
