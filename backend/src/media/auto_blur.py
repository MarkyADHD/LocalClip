"""Auto-blur: finds a vape or nudity in a clip, on this PC, and blurs just that box while it is on screen.

Runs per clip at render time, not per stream. Two small ONNX models on the CPU (onnxruntime ships with
faster-whisper), downloaded once into the state folder from the "blur-models-1" release:
- nudity: NudeNet 320n (AGPL-3.0), exposed breasts, genitals, buttocks;
- vape: YOLO-World v2 with the names baked in (.github/blur-model/export.py), looked for around the
  facecam when the stream has one, since a vape there is small.

A blur is a track: boxes (0..1 of the frame) a few times a second, linked frame to frame by overlap,
held a moment after the object is last seen so a missed frame doesn't flash it.
"""

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
import hashlib
import json
import os
import subprocess
import threading
import uuid

import cv2
import numpy as np

from ..config import get_config
from .common import logger

_RELEASE = "https://github.com/MarkyADHD/LocalClip/releases/download/blur-models-1"
MODELS = {  # name: (file, sha256, input size)
    "nudity": ("320n.onnx", "", 320),
    "vape": ("vape-s.onnx", "", 640),
}
NUDITY_LABELS = {  # NudeNet class index: what to call it
    2: "Nudity",  # BUTTOCKS_EXPOSED
    3: "Nudity",  # FEMALE_BREAST_EXPOSED
    4: "Nudity",  # FEMALE_GENITALIA_EXPOSED
    6: "Nudity",  # ANUS_EXPOSED
    14: "Nudity",  # MALE_GENITALIA_EXPOSED
}
VAPE_CLASSES = 4  # the first names in export.py are vapes; the rest soak up look-alikes (mic, phone, ...)
THRESHOLD = {"nudity": 0.5, "vape": 0.3}
SAMPLE_FPS = 4.0
HOLD_SECONDS = 0.75  # keep blurring this long after the last sighting
PAD = 0.25  # grow each box by this share, so edges and motion between samples stay covered
MIN_SIGHTINGS = {"nudity": 2, "vape": 2}  # seen once is more likely a skin-coloured wall, a mic or a pen

_lock = threading.Lock()
_sessions: Dict[str, object] = {}


def _state_file() -> Path:
    return Path(get_config().temp_dir) / "auto_blur.json"


def enabled() -> bool:
    """On unless turned off in Settings (or AUTO_BLUR=false)."""
    if os.getenv("AUTO_BLUR", "").strip().lower() == "false":
        return False
    try:
        return bool(json.loads(_state_file().read_text()).get("enabled", True))
    except (OSError, ValueError):
        return True


def set_enabled(value: bool) -> None:
    path = _state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"enabled": value}))


def _session(kind: str):
    import onnxruntime

    with _lock:
        if kind not in _sessions:
            from .diarization import _fetch

            name, sha256, _ = MODELS[kind]
            directory = Path(get_config().temp_dir) / "models" / "blur"
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / name
            if not path.exists():
                _fetch(f"{_RELEASE}/{name}", path)
            if sha256 and hashlib.sha256(path.read_bytes()).hexdigest() != sha256:
                path.unlink(missing_ok=True)
                raise RuntimeError(f"The auto-blur model {name} did not match its checksum")
            _sessions[kind] = onnxruntime.InferenceSession(str(path), providers=["CPUExecutionProvider"])
        return _sessions[kind]


Box = Tuple[float, float, float, float]  # x, y, w, h, 0..1 of the image


def decode(output: np.ndarray, size: int, width: int, height: int, threshold: float) -> List[Tuple[int, float, Box]]:
    """YOLOv8 output rows (cx, cy, w, h, class scores...) for a top-left letterbox -> (class, score, box)."""
    rows = output[0].T
    scores = rows[:, 4:]
    best, score = scores.argmax(1), scores.max(1)
    keep = score >= threshold
    rows, best, score = rows[keep], best[keep], score[keep]
    scale = max(width, height) / size
    boxes = [
        (float((cx - w / 2) * scale), float((cy - h / 2) * scale), float(w * scale), float(h * scale))
        for cx, cy, w, h in rows[:, :4]
    ]
    found = []
    for i in cv2.dnn.NMSBoxes(boxes, score.tolist(), threshold, 0.45):
        x, y, w, h = boxes[i]
        x0, y0 = max(0.0, x), max(0.0, y)
        x1, y1 = min(float(width), x + w), min(float(height), y + h)
        if x1 > x0 and y1 > y0:
            found.append((int(best[i]), float(score[i]), (x0 / width, y0 / height, (x1 - x0) / width, (y1 - y0) / height)))
    return found


def _detect(kind: str, image: np.ndarray) -> List[Tuple[int, float, Box]]:
    session = _session(kind)
    size = MODELS[kind][2]
    height, width = image.shape[:2]
    scale = size / max(width, height)
    canvas = np.zeros((size, size, 3), np.uint8)
    canvas[: round(height * scale), : round(width * scale)] = cv2.resize(
        image, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA
    )
    blob = cv2.dnn.blobFromImage(canvas, 1 / 255, swapRB=True)
    output = session.run(None, {session.get_inputs()[0].name: blob})[0]
    return decode(output, size, width, height, THRESHOLD[kind])


def _distance(a: Box, b: Box) -> float:
    """Centre distance in box sizes: under 1.5 is the same object moving (a hand going to the mouth)."""
    size = max(a[2], a[3], b[2], b[3])
    return float(np.hypot(a[0] + a[2] / 2 - b[0] - b[2] / 2, a[1] + a[3] / 2 - b[1] - b[3] / 2)) / size


def track(sightings: Sequence[Tuple[float, str, Box]], step: float = 1 / SAMPLE_FPS) -> List[dict]:
    """Links (time, label, box) sightings into blurs: same label, nearby boxes, gaps under HOLD_SECONDS."""
    open_tracks: List[dict] = []
    done: List[dict] = []
    for t, label, box in sorted(sightings, key=lambda s: s[0]):
        for item in list(open_tracks):
            if t - item["boxes"][-1]["t"] > HOLD_SECONDS + step / 2:
                open_tracks.remove(item)
                done.append(item)
        last = lambda item: tuple(item["boxes"][-1][k] for k in "xywh")  # noqa: E731
        match = min(
            (i for i in open_tracks if i["label"] == label and i["boxes"][-1]["t"] < t and _distance(last(i), box) < 1.5),
            key=lambda i: _distance(last(i), box),
            default=None,
        )
        entry = {"t": round(t, 3), **{k: round(v, 4) for k, v in zip("xywh", box)}}
        if match:
            match["boxes"].append(entry)
        else:
            open_tracks.append({"label": label, "boxes": [entry]})
    blurs = []
    for item in done + open_tracks:
        kind = "vape" if item["label"] == "Vape" else "nudity"
        if len(item["boxes"]) < MIN_SIGHTINGS[kind]:
            continue
        blurs.append(
            {
                "id": uuid.uuid4().hex[:12],
                "label": item["label"],
                "start": round(max(0.0, item["boxes"][0]["t"] - step / 2), 3),
                "end": round(item["boxes"][-1]["t"] + HOLD_SECONDS, 3),
                "boxes": item["boxes"],
            }
        )
    return sorted(blurs, key=lambda b: b["start"])


def _padded(box: Box) -> Box:
    x, y = max(0.0, box[0] - box[2] * PAD / 2), max(0.0, box[1] - box[3] * PAD / 2)
    return (x, y, min(1 - x, box[2] * (1 + PAD)), min(1 - y, box[3] * (1 + PAD)))


def find_blurs(video: Path, cam: Optional[Box] = None) -> List[dict]:
    """Blurs for `video` (times in its seconds). `cam`: where to look for a vape (the facecam, padded)."""
    from .ffmpeg import ffprobe_video_size

    sightings: List[Tuple[float, str, Box]] = []
    width, height = ffprobe_video_size(video)
    # ffmpeg decodes on all cores and hands over only the sampled frames.
    reader = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(video), "-an", "-vf", f"fps={SAMPLE_FPS}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
        stdout=subprocess.PIPE,
    )
    try:
        index = 0
        while len(data := reader.stdout.read(width * height * 3)) == width * height * 3:
            frame = np.frombuffer(data, np.uint8).reshape(height, width, 3)
            t = index / SAMPLE_FPS
            for _, _, box in [d for d in _detect("nudity", frame) if d[0] in NUDITY_LABELS]:
                sightings.append((t, "Nudity", _padded(box)))
            cx, cy, cw, ch = cam or (0.0, 0.0, 1.0, 1.0)
            x0, y0 = int(cx * width), int(cy * height)
            region = frame[y0 : y0 + max(1, int(ch * height)), x0 : x0 + max(1, int(cw * width))]
            for cls, _, (bx, by, bw, bh) in _detect("vape", region):
                if cls < VAPE_CLASSES:
                    sightings.append((t, "Vape", _padded((cx + bx * cw, cy + by * ch, bw * cw, bh * ch))))
            index += 1
    finally:
        reader.kill()
        reader.wait()
    return track(sightings)


def find_clip_blurs(video: Path) -> List[dict]:
    """find_blurs with the vape search around the facecam, or [] when auto-blur is off or fails."""
    if not enabled():
        return []
    try:
        from .stream_layouts import FULLSCREEN_CAM_WIDTH, detect_facecam, pad_face

        face = detect_facecam(video)
        cam = pad_face(face, 3.0) if face and face[2] <= FULLSCREEN_CAM_WIDTH else None
        blurs = find_blurs(video, cam)
        if blurs:
            logger.info("Auto-blur: %s", ", ".join(f"{b['label']} {b['start']:.1f}-{b['end']:.1f}s" for b in blurs))
        return blurs
    except Exception as exc:  # a missing model or a bad frame must not stop the clip
        logger.warning("Auto-blur skipped: %s", exc)
        return []


def box_at(blur: dict, t: float) -> Optional[Box]:
    """The blur's box at time t: the union of the sightings around t, so motion between them stays covered."""
    if not blur["start"] <= t < blur["end"]:
        return None
    boxes = blur["boxes"]
    before = [b for b in boxes if b["t"] <= t] or boxes[:1]
    after = [b for b in boxes if b["t"] > t] or boxes[-1:]
    a, b = before[-1], after[0]
    x0, y0 = min(a["x"], b["x"]), min(a["y"], b["y"])
    return (x0, y0, max(a["x"] + a["w"], b["x"] + b["w"]) - x0, max(a["y"] + a["h"], b["y"] + b["h"]) - y0)


def blur_filter(blurs: Sequence[dict], width: int, height: int, tag: str = "b") -> Optional[str]:
    """filter_complex from [<tag>in] to [<tag>out]: the frame with each blur's box blurred while it is on.

    One blurred copy of the frame shows through a mask of boxes, a box per sighting interval.
    """
    boxes = []
    for blur in blurs:
        times = sorted({blur["start"], *(b["t"] for b in blur["boxes"]), blur["end"]})
        for t0, t1 in zip(times, times[1:]):
            box = box_at(blur, t0)
            if box and box[2] > 0.001 and box[3] > 0.001:
                x, y, w, h = box
                boxes.append(
                    f"drawbox=x={int(x * width)}:y={int(y * height)}:w={max(2, round(w * width))}:h={max(2, round(h * height))}"
                    f":color=white:t=fill:enable='between(t,{t0:.3f},{t1:.3f})'"
                )
    if not boxes:
        return None
    radius = max(1, width // 960)
    return (
        f"[{tag}in]split=3[{tag}o][{tag}b][{tag}m];"
        f"[{tag}b]scale={max(2, width // 8)}:-2,boxblur={radius}:2,scale={width}:{height},format=yuva420p[{tag}bl];"
        f"[{tag}m]format=gray,lut=c0=0,{','.join(boxes)}[{tag}mask];"
        f"[{tag}bl][{tag}mask]alphamerge[{tag}ba];[{tag}o][{tag}ba]overlay=format=auto[{tag}out]"
    )


def crop_blurs(blurs: Sequence[dict], crop: str, width: int, height: int) -> List[dict]:
    """`blurs` moved into the picture of `crop` (ffmpeg w:h:x:y of a width x height frame)."""
    cw, ch, cx, cy = map(int, crop.split(":"))
    moved = []
    for blur in blurs:
        boxes = []
        for b in blur["boxes"]:
            x0, y0 = max(0.0, (b["x"] * width - cx) / cw), max(0.0, (b["y"] * height - cy) / ch)
            x1 = min(1.0, ((b["x"] + b["w"]) * width - cx) / cw)
            y1 = min(1.0, ((b["y"] + b["h"]) * height - cy) / ch)
            boxes.append({"t": b["t"], "x": min(x0, 1.0), "y": min(y0, 1.0), "w": max(0.0, x1 - x0), "h": max(0.0, y1 - y0)})
        moved.append({**blur, "boxes": boxes})
    return moved


def apply_blurs(source: Path, output: Path, blurs: Sequence[dict]) -> bool:
    """Writes `source` with `blurs` burned in (near-lossless, sound copied). False when there is nothing to blur."""
    from .ffmpeg import ffprobe_video_size, intermediate_video_encode_args, run_ffmpeg_command

    width, height = ffprobe_video_size(source)
    graph = blur_filter(blurs, width, height)
    if not graph:
        return False
    command = [
        "ffmpeg", "-y", "-i", str(source),
        "-filter_complex", f"[0:v]null[bin];{graph}",
        "-map", "[bout]", "-map", "0:a?", "-c:a", "copy",
        *intermediate_video_encode_args(),
        str(output),
    ]
    return run_ffmpeg_command(command).returncode == 0
