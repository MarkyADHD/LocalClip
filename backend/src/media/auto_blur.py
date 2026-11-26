"""Auto-blur: finds a vape or nudity in a clip, on this PC, and blurs just that box while it is on screen.

Runs per clip at render time, not per stream. Two small ONNX models on the CPU (onnxruntime ships with
faster-whisper), downloaded once into the state folder from the "blur-models-1" release:
- nudity: NudeNet 320n (AGPL-3.0), exposed breasts, genitals, buttocks;
- vape: OWLv2 (Apache-2.0) with the vape names baked in (.github/blur-model/owl.py). Slower, so it looks
  once a second, and only around the facecam when the stream has one (a vape there is small).

A blur is a track: boxes (0..1 of the frame) linked sighting to sighting by distance, held a moment after
the object is last seen so a missed frame doesn't flash it.
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
    "nudity": ("320n.onnx", "c15d8273adad2d0a92f014cc69ab2d6c311a06777a55545f2c4eb46f51911f0f", 320),
    "vape": ("vape-owl-480.onnx", "97084ce481051cc044ebdc89b35a386c82edd43966c9dd4f61c019b73271b712", 480),
}
NUDITY_LABELS = {  # NudeNet class index: what to call it
    2: "Nudity",  # BUTTOCKS_EXPOSED
    3: "Nudity",  # FEMALE_BREAST_EXPOSED
    4: "Nudity",  # FEMALE_GENITALIA_EXPOSED
    6: "Nudity",  # ANUS_EXPOSED
    14: "Nudity",  # MALE_GENITALIA_EXPOSED
}
THRESHOLD = {"nudity": 0.5, "vape": 0.3}
SAMPLE_FPS = 4.0  # nudity: every sampled frame
VAPE_EVERY = 4  # vape: every 4th sampled frame, once a second
HOLD_SECONDS = 0.75  # keep blurring at least this long after the last sighting
# OWLv2's normalisation (CLIP), RGB.
_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], np.float32)
_STD = np.array([0.26862954, 0.26130258, 0.27577711], np.float32)
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


def decode(
    boxes: np.ndarray, scores: np.ndarray, scale: float, width: int, height: int, threshold: float
) -> List[Tuple[int, float, Box]]:
    """cx, cy, w, h boxes (times `scale` = pixels of a top-left padded square) and class scores -> (class, score, box)."""
    best, score = scores.argmax(1), scores.max(1)
    keep = score >= threshold
    boxes, best, score = boxes[keep], best[keep], score[keep]
    rects = [
        (float((cx - w / 2) * scale), float((cy - h / 2) * scale), float(w * scale), float(h * scale))
        for cx, cy, w, h in boxes
    ]
    found = []
    for i in cv2.dnn.NMSBoxes(rects, score.tolist(), threshold, 0.45):
        x, y, w, h = rects[i]
        x0, y0 = max(0.0, x), max(0.0, y)
        x1, y1 = min(float(width), x + w), min(float(height), y + h)
        if x1 > x0 and y1 > y0:
            found.append((int(best[i]), float(score[i]), (x0 / width, y0 / height, (x1 - x0) / width, (y1 - y0) / height)))
    return found


def _detect(kind: str, image: np.ndarray) -> List[Tuple[int, float, Box]]:
    """Runs a model on a BGR image, letterboxed into the top left of its square input."""
    session = _session(kind)
    size = MODELS[kind][2]
    height, width = image.shape[:2]
    scale = size / max(width, height)
    canvas = np.zeros((size, size, 3), np.uint8)
    canvas[: round(height * scale), : round(width * scale)] = cv2.resize(
        image, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA
    )
    rgb = canvas[:, :, ::-1].astype(np.float32) / 255
    if kind == "vape":  # OWLv2: scores [1, boxes, names], boxes 0..1 of the square
        rgb = (rgb - _MEAN) / _STD
    blob = rgb.transpose(2, 0, 1)[None].copy()
    outputs = session.run(None, {session.get_inputs()[0].name: blob})
    if kind == "vape":
        return decode(outputs[1][0], outputs[0][0], max(width, height), width, height, THRESHOLD[kind])
    rows = outputs[0][0].T  # NudeNet (YOLOv8): rows of cx, cy, w, h in input pixels, then class scores
    return decode(rows[:, :4], rows[:, 4:], max(width, height) / size, width, height, THRESHOLD[kind])


def _distance(a: Box, b: Box) -> float:
    """Centre distance in box sizes: under 1.5 is the same object moving (a hand going to the mouth)."""
    size = max(a[2], a[3], b[2], b[3])
    return float(np.hypot(a[0] + a[2] / 2 - b[0] - b[2] / 2, a[1] + a[3] / 2 - b[1] - b[3] / 2)) / size


def track(sightings: Sequence[Tuple[float, str, Box]], step: float = 1 / SAMPLE_FPS) -> List[dict]:
    """Links (time, label, box) sightings `step` seconds apart into blurs: same label, nearby boxes, small gaps.

    A blur starts a step before its first sighting and lasts a step (or HOLD_SECONDS) past its last, since the
    thing may have been there between samples."""
    hold = max(HOLD_SECONDS, step)
    open_tracks: List[dict] = []
    done: List[dict] = []
    for t, label, box in sorted(sightings, key=lambda s: s[0]):
        for item in list(open_tracks):
            if t - item["boxes"][-1]["t"] > hold + step / 2:
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
                "start": round(max(0.0, item["boxes"][0]["t"] - step), 3),
                "end": round(item["boxes"][-1]["t"] + hold, 3),
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

    nudity: List[Tuple[float, str, Box]] = []
    vapes: List[Tuple[float, str, Box]] = []
    width, height = ffprobe_video_size(video)
    # ffmpeg decodes on all cores and hands over only the sampled frames.
    reader = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(video), "-an", "-vf", f"fps={SAMPLE_FPS}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
        stdout=subprocess.PIPE,
    )
    cx, cy, cw, ch = cam or (0.0, 0.0, 1.0, 1.0)
    x0, y0 = int(cx * width), int(cy * height)
    try:
        index = 0
        while len(data := reader.stdout.read(width * height * 3)) == width * height * 3:
            frame = np.frombuffer(data, np.uint8).reshape(height, width, 3)
            t = index / SAMPLE_FPS
            for cls, _, box in _detect("nudity", frame):
                if cls in NUDITY_LABELS:
                    nudity.append((t, "Nudity", _padded(box)))
            if index % VAPE_EVERY == 0:
                region = frame[y0 : y0 + max(1, int(ch * height)), x0 : x0 + max(1, int(cw * width))]
                for _, _, (bx, by, bw, bh) in _detect("vape", region):
                    vapes.append((t, "Vape", _padded((cx + bx * cw, cy + by * ch, bw * cw, bh * ch))))
            index += 1
    finally:
        reader.kill()
        reader.wait()
    return sorted(track(nudity) + track(vapes, VAPE_EVERY / SAMPLE_FPS), key=lambda b: b["start"])


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
