"""Long-form projects: a multi-track timeline document, its files, and the ffmpeg plan that renders it.

A project is a folder under TEMP_DIR/projects/<id>/:
  project.json            id, owner, name
  document.json           {revision, document}
  assets/<asset>/         meta.json, proxy.mp4 | audio.m4a | image.png, waveform.bin, thumbs.jpg, transcript.json
  exports/                job-<id>.json, request-<id>.json, <id>.mp4, chunks/
Source files stay where they are on disk; only preview copies live here.

The timeline is rendered in chunks so a two-hour edit never becomes one enormous ffmpeg command.
The browser preview (frontend/src/lib/project) draws the same picture; change both together.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional
import hashlib
import json
import re

from pydantic import Field, model_validator

from .editor_document import (
    ASS_EVENTS,
    CaptionStyle,
    Model,
    RevisionConflict,
    ass_event,
    ass_header,
    atomic_json,
    caption_events,
    editor_lock,
)

ID = r"^[A-Za-z0-9_-]{1,64}$"
CHUNK_SECONDS = 60.0
MAX_PIECES = 24  # video inputs per ffmpeg command; busier stretches are split further
CUT_FADE = 0.008  # audio micro-fade at every clip edge so hard cuts do not click


class Track(Model):
    id: str = Field(pattern=ID)
    kind: Literal["video", "audio", "text"]
    name: str = Field(default="", max_length=40)
    muted: bool = False
    hidden: bool = False
    locked: bool = False


class TextStyle(Model):
    content: str = Field(default="Text", max_length=300)
    font: str = CaptionStyle.model_fields["font"].default
    size: int = Field(default=60, ge=10, le=300)
    color: str = Field(default="#FFFFFF", pattern=r"^#[0-9a-fA-F]{6}$")
    background: bool = False
    outline: float = Field(default=4, ge=0, le=12)
    uppercase: bool = False


class Keyframe(Model):
    """A value of the animated properties at `t` seconds into the clip; linear between keys."""

    t: float = Field(ge=0)
    x: float = Field(ge=-2, le=3)
    y: float = Field(ge=-2, le=3)
    scale: float = Field(gt=0, le=10)
    opacity: float = Field(ge=0, le=1)


class Clip(Model):
    id: str = Field(pattern=ID)
    track: str = Field(pattern=ID)
    start: float = Field(ge=0)  # on the timeline, seconds
    duration: float = Field(gt=0)  # on the timeline, seconds
    asset: Optional[str] = Field(default=None, pattern=ID)  # None for text clips
    offset: float = Field(default=0, ge=0)  # where in the source the clip begins
    speed: float = Field(default=1, ge=0.25, le=4)
    x: float = Field(default=0.5, ge=-2, le=3)  # centre, as a share of the frame
    y: float = Field(default=0.5, ge=-2, le=3)
    scale: float = Field(default=1, gt=0, le=10)  # 1 = fits inside the frame
    opacity: float = Field(default=1, ge=0, le=1)
    volume: float = Field(default=1, ge=0, le=4)
    muted: bool = False
    fadeIn: float = Field(default=0, ge=0, le=30)
    fadeOut: float = Field(default=0, ge=0, le=30)
    text: Optional[TextStyle] = None
    keys: list[Keyframe] = Field(default_factory=list, max_length=50)
    link: Optional[str] = Field(default=None, pattern=ID)

    @model_validator(mode="after")
    def minimum(self):
        if self.duration < 0.03:
            raise ValueError("Each clip must be at least one frame long")
        return self


class Cut(Model):
    """A removed stretch of a source, kept so it can be shown struck through and restored."""

    asset: str = Field(pattern=ID)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    reason: Literal["manual", "silence", "filler", "ai"] = "manual"


class Chapter(Model):
    time: float = Field(ge=0)
    title: str = Field(max_length=120)


def _project_captions() -> CaptionStyle:
    return CaptionStyle(size=30, y=0.88, wordsPerLine=7)


class ProjectDocument(Model):
    version: Literal[1] = 1
    width: int = Field(default=1920, ge=16, le=3840)
    height: int = Field(default=1080, ge=16, le=3840)
    fps: float = Field(default=30, ge=1, le=120)
    tracks: list[Track] = Field(min_length=1, max_length=24)
    clips: list[Clip] = Field(default_factory=list, max_length=20000)
    captions: CaptionStyle = Field(default_factory=_project_captions)
    # Corrected caption text: {asset: {word index: text}}; an empty string hides the word.
    wordEdits: dict[str, dict[str, str]] = Field(default_factory=dict)
    cuts: list[Cut] = Field(default_factory=list, max_length=20000)
    chapters: list[Chapter] = Field(default_factory=list, max_length=200)
    title: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=5000)

    @model_validator(mode="after")
    def consistent(self):
        if self.width % 2 or self.height % 2:
            raise ValueError("The frame size must be even")
        tracks = {t.id for t in self.tracks}
        if len(tracks) != len(self.tracks):
            raise ValueError("Track ids must be unique")
        if any(c.track not in tracks for c in self.clips):
            raise ValueError("A clip is on a track that does not exist")
        return self

    @property
    def duration(self) -> float:
        return max((c.start + c.duration for c in self.clips), default=0.0)


def new_document() -> ProjectDocument:
    return ProjectDocument(
        tracks=[
            Track(id="v1", kind="video", name="Main"),
            Track(id="v2", kind="video", name="Overlay"),
            Track(id="t1", kind="text", name="Text"),
            Track(id="a1", kind="audio", name="Music"),
        ]
    )


# ---------------------------------------------------------------- files


def projects_root(temp_dir: str) -> Path:
    return Path(temp_dir) / "projects"


def project_dir(temp_dir: str, project_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", project_id):
        raise FileNotFoundError(project_id)
    return projects_root(temp_dir) / project_id


def asset_dir(directory: Path, asset_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{12}", asset_id):
        raise FileNotFoundError(asset_id)
    return directory / "assets" / asset_id


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def read_assets(directory: Path) -> dict[str, dict]:
    result = {}
    for meta in sorted((directory / "assets").glob("*/meta.json")):
        data = read_json(meta)
        if data:
            result[data["id"]] = data
    return result


def read_draft(directory: Path) -> dict:
    return read_json(directory / "document.json") or {
        "revision": 0,
        "document": new_document().model_dump(),
    }


def save_draft(directory: Path, document: ProjectDocument, revision: int) -> dict:
    with editor_lock(directory):
        if read_draft(directory)["revision"] != revision:
            raise RevisionConflict(
                "This project was edited in another tab. Reload it before continuing."
            )
        payload = {"revision": revision + 1, "document": document.model_dump()}
        atomic_json(directory / "document.json", payload)
        return payload


def read_words(directory: Path, asset_id: str) -> list[dict]:
    """[{s, e, t}] in source seconds, or [] while the transcript is not ready."""
    data = read_json(asset_dir(directory, asset_id) / "transcript.json") or {}
    return data.get("words") or []


# ---------------------------------------------------------------- captions


def timeline_words(document: ProjectDocument, words_of) -> list[dict]:
    """Spoken words of every audible clip, placed on the timeline (mirrors timelineWords in document.ts)."""
    tracks = {t.id: t for t in document.tracks}
    result = []
    for clip in document.clips:
        track = tracks[clip.track]
        if not clip.asset or clip.muted or track.muted or track.kind == "text":
            continue
        edits = document.wordEdits.get(clip.asset, {})
        end = clip.offset + clip.duration * clip.speed
        for index, word in enumerate(words_of(clip.asset)):
            if not clip.offset <= word["s"] < end:
                continue
            text = edits.get(str(index), word["t"]).strip()
            if text:
                result.append(
                    {
                        "text": text,
                        "start": clip.start + (word["s"] - clip.offset) / clip.speed,
                        "end": clip.start + (min(word["e"], end) - clip.offset) / clip.speed,
                    }
                )
    result.sort(key=lambda w: w["start"])
    return result


def project_words(directory: Path, document: ProjectDocument) -> list[dict]:
    """The timeline's spoken words, read from the project's transcripts."""
    assets = read_assets(directory)
    cache: dict[str, list[dict]] = {}
    return timeline_words(document, lambda a: cache.setdefault(a, read_words(directory, a) if a in assets else []))


def _ass_time_tags(clip: Clip, a: float, b: float) -> str:
    """Fade a text clip in and out with libass's own timing (ms from the event's start)."""
    if not (clip.fadeIn or clip.fadeOut):
        return ""
    s, e = clip.start, clip.start + clip.duration
    ms = lambda v: int(round((v - a) * 1000))  # noqa: E731
    return f"\\fade(255,0,255,{ms(s)},{ms(s + clip.fadeIn)},{ms(e - clip.fadeOut)},{ms(e)})"


def write_chunk_ass(path: Path, document: ProjectDocument, words: list[dict], c0: float, c1: float) -> bool:
    """Captions and text clips visible in [c0, c1), with times relative to c0. False when there are none."""
    width, height = document.width, document.height
    header, style_line = ass_header(document.captions, width, height)
    styles, lines = [style_line], []
    tracks = {t.id: t for t in document.tracks}
    for clip in document.clips:
        a, b = max(clip.start, c0), min(clip.start + clip.duration, c1)
        if not clip.text or b <= a or tracks[clip.track].hidden or not clip.text.content.strip():
            continue
        style = CaptionStyle(
            font=clip.text.font if clip.text.font in CaptionStyle.model_fields["font"].annotation.__args__ else "Poppins-ExtraBold",
            size=20,
            color=clip.text.color,
            background=clip.text.background,
            outline=clip.text.outline,
            uppercase=clip.text.uppercase,
        )
        # CaptionStyle caps its size for clips; titles go larger, so set it past validation.
        style = style.model_copy(update={"size": clip.text.size * clip.scale})
        name = f"T{len(styles)}"
        styles.append(ass_header(style, width, height, name)[1])
        x, y, _, opacity = clip_values(clip, a - clip.start)
        tags = _ass_time_tags(clip, a, b)
        if opacity < 1:
            tags += f"\\alpha&H{int(round((1 - opacity) * 255)):02X}&"
        for row, text in enumerate(clip.text.content.splitlines()):
            rows = len(clip.text.content.splitlines())
            em = style.size * width / 1080
            lines.append(
                ass_event(
                    style, width, height, a - c0, b - c0,
                    y + (row - (rows - 1) / 2) * em * 1.2 / height,
                    [{"text": word} for word in text.split()] or [{"text": " "}],
                    lambda i: False, x=x, name=name, tags=tags,
                )
            )
    if document.captions.enabled:
        for start, end, group, accent in caption_events(document.captions, words):
            a, b = max(start, c0), min(end, c1)
            if b > a:
                lines.append(
                    ass_event(document.captions, width, height, a - c0, b - c0, document.captions.y, group, accent)
                )
    if not lines:
        return False
    path.write_text(header + "".join(styles) + ASS_EVENTS + "".join(lines), encoding="utf-8")
    return True


# ---------------------------------------------------------------- render plan


def clip_values(clip: Clip, t: float) -> tuple[float, float, float, float]:
    """(x, y, scale, opacity) `t` seconds into the clip, keyframes applied (mirrors clipValues in document.ts)."""
    if not clip.keys:
        return clip.x, clip.y, clip.scale, clip.opacity
    keys = sorted(clip.keys, key=lambda k: k.t)
    if t <= keys[0].t:
        k = keys[0]
        return k.x, k.y, k.scale, k.opacity
    for a, b in zip(keys, keys[1:]):
        if t <= b.t:
            f = (t - a.t) / (b.t - a.t) if b.t > a.t else 1
            mix = lambda p, q: p + (q - p) * f  # noqa: E731
            return mix(a.x, b.x), mix(a.y, b.y), mix(a.scale, b.scale), mix(a.opacity, b.opacity)
    k = keys[-1]
    return k.x, k.y, k.scale, k.opacity


def _key_expr(clip: Clip, name: str, t0: float, var: str = "t") -> str:
    """ffmpeg expression for an animated property; `var` counts seconds from the piece's start."""
    keys = sorted(clip.keys, key=lambda k: k.t)
    expr = f"{getattr(keys[-1], name):.5f}"
    for a, b in reversed(list(zip(keys, keys[1:]))):
        va, vb, span = getattr(a, name), getattr(b, name), max(b.t - a.t, 1e-6)
        expr = f"if(lt({var}+{t0:.4f},{b.t:.4f}),{va:.5f}+({vb - va:.5f})*clip(({var}+{t0:.4f}-{a.t:.4f})/{span:.4f},0,1),{expr})"
    return expr


def chunk_bounds(document: ProjectDocument) -> list[tuple[float, float]]:
    """Frame-aligned [start, end) stretches covering the timeline, none with too many clips."""
    fps, total = document.fps, document.duration
    frames = max(1, round(total * fps))
    tracks = {t.id: t for t in document.tracks}

    def busy(f0: int, f1: int) -> int:
        a, b = f0 / fps, f1 / fps
        return sum(
            1
            for c in document.clips
            if c.asset and tracks[c.track].kind == "video" and c.start < b and c.start + c.duration > a
        )

    def split(f0: int, f1: int):
        if busy(f0, f1) > MAX_PIECES and f1 - f0 > 2 * fps:
            mid = (f0 + f1) // 2
            yield from split(f0, mid)
            yield from split(mid, f1)
        else:
            yield f0 / fps, f1 / fps

    step = max(1, round(CHUNK_SECONDS * fps))
    return [bounds for f0 in range(0, frames, step) for bounds in split(f0, min(frames, f0 + step))]


def _atempo(speed: float) -> str:
    parts = []
    while speed > 2:
        parts.append("atempo=2")
        speed /= 2
    while speed < 0.5:
        parts.append("atempo=0.5")
        speed /= 0.5
    parts.append(f"atempo={speed:.5f}")
    return ",".join(parts)


def chunk_command(
    document: ProjectDocument,
    assets: dict[str, dict],
    c0: float,
    c1: float,
    ass: Optional[str],
    fonts: Optional[str],
    encode: list[str],
    output: str,
) -> list[str]:
    """One ffmpeg command rendering [c0, c1) of the timeline to `output` (video + PCM audio).

    `ass`/`fonts` are filter-escaped paths. Each clip piece is its own seeked input; a track's
    pieces are joined with gaps into one stream, then the tracks are stacked bottom to top.
    """
    W, H, fps = document.width, document.height, document.fps
    D = c1 - c0
    frames = lambda seconds: max(1, round(seconds * fps))  # noqa: E731
    tracks = {t.id: t for t in document.tracks}
    inputs: list[str] = []
    filters: list[str] = []
    audio_labels: list[str] = []
    layers: list[tuple[str, bool]] = []  # (label, opaque)

    def pieces(track_id: str):
        for clip in sorted((c for c in document.clips if c.track == track_id), key=lambda c: c.start):
            asset = assets.get(clip.asset or "")
            a, b = max(clip.start, c0), min(clip.start + clip.duration, c1)
            if asset and asset.get("status") == "ready" and b - a > 0.5 / fps:
                yield clip, asset, a, b

    def add_input(asset: dict, clip: Clip, a: float, b: float) -> int:
        if asset["kind"] == "image":
            inputs.extend(["-loop", "1", "-framerate", f"{fps:.5f}", "-t", f"{b - a + 1:.4f}", "-i", asset["path"]])
        else:
            source = clip.offset + (a - clip.start) * clip.speed
            inputs.extend(["-ss", f"{source:.4f}", "-t", f"{(b - a) * clip.speed + 0.5:.4f}", "-i", asset["path"]])
        return inputs.count("-i") - 1

    def audio_chain(index: int, clip: Clip, a: float, b: float):
        t0, length = a - clip.start, b - a
        fade_in, fade_out = max(clip.fadeIn, CUT_FADE), max(clip.fadeOut, CUT_FADE)
        label = f"a{len(audio_labels)}"
        filters.append(
            f"[{index}:a:0]asetpts=PTS-STARTPTS,{_atempo(clip.speed)},atrim=duration={length:.4f},"
            f"aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            # Fades are timed from the clip's start, so a clip split across chunks fades once.
            f"asetpts=PTS-STARTPTS+{t0:.4f}/TB,afade=t=in:st=0:d={fade_in:.4f},"
            f"afade=t=out:st={clip.duration - fade_out:.4f}:d={fade_out:.4f},asetpts=PTS-STARTPTS,"
            f"volume={clip.volume:.3f},adelay={int(round((a - c0) * 1000))}:all=1[{label}]"
        )
        audio_labels.append(f"[{label}]")

    video_tracks = [t for t in document.tracks if t.kind == "video"]
    for position, track in enumerate(video_tracks):
        found = list(pieces(track.id))
        if not found:
            continue
        # The lowest picture needs no transparency when nothing in it is see-through or animated.
        opaque = not layers and all(c.opacity == 1 and not c.keys for c, *_ in found)
        fmt, pad = ("yuv420p", "black") if opaque else ("yuva420p", "black@0")
        parts: list[str] = []
        cursor = round(c0 * fps)

        def gap(until: int):
            nonlocal cursor
            if until > cursor:
                label = f"g{position}_{len(parts)}"
                filters.append(
                    f"color=c={pad}:s={W}x{H}:r={fps:.5f}:d={(until - cursor) / fps:.5f},format={fmt},"
                    f"trim=end_frame={until - cursor},setsar=1[{label}]"
                )
                parts.append(f"[{label}]")
                cursor = until

        for clip, asset, a, b in found:
            index = add_input(asset, clip, a, b)
            has_audio = asset["kind"] != "image" and asset.get("hasAudio")
            if has_audio and not (clip.muted or track.muted or clip.volume == 0):
                audio_chain(index, clip, a, b)
            if track.hidden:
                continue
            f0, f1 = max(cursor, round(a * fps)), round(b * fps)
            if f1 <= f0:
                continue
            gap(f0)
            t0 = f0 / fps - clip.start
            sw, sh = asset.get("width") or W, asset.get("height") or H
            fit = min(W / sw, H / sh)
            label = f"v{position}_{len(parts)}"
            chain = [f"[{index}:v:0]setpts=(PTS-STARTPTS)/{clip.speed:.5f}", f"fps={fps:.5f}"]
            if clip.keys:
                # Animated: scale every frame, then place it over a clear frame.
                sx = _key_expr(clip, "scale", t0)
                chain += [
                    f"scale=w='max(2,trunc({sw * fit:.3f}*({sx})/2)*2)':h='max(2,trunc({sh * fit:.3f}*({sx})/2)*2)':eval=frame",
                    "format=yuva420p",
                ]
                filters.append(",".join(chain) + f"[{label}s]")
                op = _key_expr(clip, "opacity", t0, "T")
                # ponytail: geq is slow, but only clips with animated opacity pay for it.
                filters.append(
                    f"[{label}s]geq=lum='lum(X,Y)':cb='cb(X,Y)':cr='cr(X,Y)':a='alpha(X,Y)*({op})'[{label}o]"
                    if any(k.opacity < 1 for k in clip.keys)
                    else f"[{label}s]null[{label}o]"
                )
                filters.append(
                    f"color=c=black@0:s={W}x{H}:r={fps:.5f},format=yuva420p[{label}b];"
                    f"[{label}b][{label}o]overlay=x='{W}*({_key_expr(clip, 'x', t0)})-w/2':"
                    f"y='{H}*({_key_expr(clip, 'y', t0)})-h/2':shortest=1:format=auto,format={fmt}[{label}p]"
                )
                chain = [f"[{label}p]null"]
            else:
                w, h = max(2, round(sw * fit * clip.scale / 2) * 2), max(2, round(sh * fit * clip.scale / 2) * 2)
                left, top = round(clip.x * W - w / 2), round(clip.y * H - h / 2)
                # Keep the part of the picture that is inside the frame, then pad it out to the frame.
                cx, cy = max(0, -left), max(0, -top)
                cw, ch = min(w - cx, W - max(0, left)), min(h - cy, H - max(0, top))
                if cw < 2 or ch < 2:
                    chain += [f"scale={W}:{H}", f"format={fmt}", "colorchannelmixer=aa=0" if not opaque else "drawbox=t=fill:c=black"]
                else:
                    cw, ch = cw // 2 * 2, ch // 2 * 2
                    chain += [f"scale={w}:{h}", f"format={fmt}"]
                    if (cw, ch) != (w, h):
                        chain.append(f"crop={cw}:{ch}:{cx}:{cy}")
                    if clip.opacity < 1:
                        chain.append(f"colorchannelmixer=aa={clip.opacity:.3f}")
                    if (cw, ch) != (W, H):
                        chain.append(f"pad={W}:{H}:{max(0, left)}:{max(0, top)}:color={pad}")
            # Fades are timed from the clip's start (see audio_chain).
            alpha = "" if opaque else ":alpha=1"
            chain.append(f"setpts=PTS-STARTPTS+{t0:.4f}/TB")
            if clip.fadeIn:
                chain.append(f"fade=t=in:st=0:d={clip.fadeIn:.4f}{alpha}")
            if clip.fadeOut:
                chain.append(f"fade=t=out:st={clip.duration - clip.fadeOut:.4f}:d={clip.fadeOut:.4f}{alpha}")
            # Exactly f1 - f0 frames, whatever the source's own frame timing was.
            chain += ["setpts=PTS-STARTPTS", "tpad=stop_mode=clone:stop=-1", f"trim=end_frame={f1 - f0}", "setsar=1"]
            filters.append(",".join(chain) + f"[{label}]")
            parts.append(f"[{label}]")
            cursor = f1
        if parts:
            gap(round(c1 * fps))
            label = f"trk{position}"
            filters.append("".join(parts) + f"concat=n={len(parts)}:v=1:a=0[{label}]")
            layers.append((label, opaque))

    for track in (t for t in document.tracks if t.kind == "audio" and not t.muted):
        for clip, asset, a, b in pieces(track.id):
            if asset["kind"] != "image" and asset.get("hasAudio") and not clip.muted and clip.volume:
                audio_chain(add_input(asset, clip, a, b), clip, a, b)

    if layers and layers[0][1]:
        current = layers.pop(0)[0]
    else:
        filters.append(f"color=c=black:s={W}x{H}:r={fps:.5f}:d={D:.5f},format=yuv420p,trim=end_frame={frames(D)}[base]")
        current = "base"
    for label, _ in layers:
        filters.append(f"[{current}][{label}]overlay=0:0:format=auto[o{label}]")
        current = f"o{label}"
    tail = f"ass={ass}" + (f":fontsdir={fonts}" if fonts else "") if ass else "null"
    filters.append(f"[{current}]{tail},format=yuv420p[outv]")
    filters.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={D:.5f}[sil]")
    filters.append(
        f"[sil]{''.join(audio_labels)}amix=inputs={len(audio_labels) + 1}:normalize=0:duration=longest,"
        f"atrim=duration={D:.5f}[outa]"
    )
    return (
        ["ffmpeg", "-y", "-v", "error"]
        + inputs
        + ["-filter_complex", ";".join(filters), "-map", "[outv]", "-map", "[outa]"]
        + encode
        + ["-frames:v", str(frames(D)), "-c:a", "pcm_s16le", "-ar", "48000", output]
    )


def chunk_key(command: list[str], ass_text: str) -> str:
    """Names a rendered chunk by everything that went into it, so an unchanged chunk is reused."""
    return hashlib.sha1(json.dumps([command[:-1], ass_text]).encode()).hexdigest()[:20]
