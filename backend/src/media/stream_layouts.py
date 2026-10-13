"""StreamLadder-style templates for gaming streams (ported from the old LocalClip editor).

The default 9:16 mode tracks the biggest face, which on a stream is the facecam, so the
gameplay is lost. These templates find the facecam once per clip and build a fixed
layout around it: cam over gameplay, gameplay over cam, a floating cam, or gameplay only.
"""

from pathlib import Path
from typing import List, Optional, Tuple

import cv2

from .common import UPSCALE_SHARPEN_FILTER, logger
from .face_detection import open_haar_cascade, open_yunet_detector
from .ffmpeg import ffprobe_duration

STREAM_LAYOUTS = {"facecam_top", "gameplay_top", "floating_cam", "gameplay_only"}

Rect = Tuple[float, float, float, float]  # x, y, w, h normalised to the source frame

OUT_W, OUT_H = 1080, 1920
CAM_SHARE = 0.4  # facecam band height in the stacked layouts
FULLSCREEN_CAM_WIDTH = 0.3  # a face this wide is a full-screen camera, not an overlay


def stable_face(frames: List[List[Rect]], min_support: float = 0.3) -> Optional[Rect]:
    """The face box seen in the most sampled frames (a facecam doesn't move; game faces do), medianed."""

    def near(a: Rect, b: Rect) -> bool:
        return (
            abs((a[0] + a[2] / 2) - (b[0] + b[2] / 2)) < a[2] * 0.5
            and abs((a[1] + a[3] / 2) - (b[1] + b[3] / 2)) < a[3] * 0.5
            and 0.6 < b[2] / a[2] < 1.6
        )

    best: List[Rect] = []
    for faces in frames:
        for cand in faces:
            support = [next(b for b in g if near(cand, b)) for g in frames if any(near(cand, b) for b in g)]
            if len(support) > len(best):
                best = support
    if not frames or len(best) / len(frames) < min_support:
        return None
    return tuple(sorted(b[k] for b in best)[len(best) // 2] for k in range(4))  # type: ignore[return-value]


def detect_facecam(input_path: Path, samples: int = 16) -> Optional[Rect]:
    """Sample frames across the clip and return the stable face box, normalised."""
    duration = ffprobe_duration(input_path)
    yunet = open_yunet_detector()
    haar = None if yunet else open_haar_cascade()
    cap = cv2.VideoCapture(str(input_path))
    frames: List[List[Rect]] = []
    try:
        for i in range(samples):
            cap.set(cv2.CAP_PROP_POS_MSEC, duration * (i + 0.5) / samples * 1000)
            ok, img = cap.read()
            if not ok:
                continue
            h, w = img.shape[:2]
            if yunet:
                boxes = [b[:4] for b in yunet.detect(img)]
            else:
                gray = cv2.equalizeHist(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
                boxes = haar.detectMultiScale(gray, 1.1, 6, minSize=(int(h * 0.03),) * 2)
            frames.append([(x / w, y / h, bw / w, bh / h) for x, y, bw, bh in boxes])
    finally:
        cap.release()
    return stable_face(frames)


def pad_face(r: Rect, pad: float = 1.2) -> Rect:
    """Grow a tight face box to head and shoulders, the way a webcam overlay frames it."""
    x, y = max(0.0, r[0] - r[2] * pad / 2), max(0.0, r[1] - r[3] * pad / 2)
    return (x, y, min(1 - x, r[2] * (1 + pad)), min(1 - y, r[3] * (1 + pad)))


def fit_crop(r: Rect, aspect: float, width: int, height: int) -> str:
    """ffmpeg crop (pixels, even) around the centre of `r` with output aspect w/h, inside the frame."""
    cx, cy = (r[0] + r[2] / 2) * width, (r[1] + r[3] / 2) * height
    w, h = r[2] * width, r[3] * height
    if w / h < aspect:
        w = h * aspect
    else:
        h = w / aspect
    if w > width:
        w, h = width, width / aspect
    if h > height:
        h, w = height, height * aspect
    w, h = int(w) // 2 * 2, int(h) // 2 * 2
    x = int(min(max(cx - w / 2, 0), width - w)) // 2 * 2
    y = int(min(max(cy - h / 2, 0), height - h)) // 2 * 2
    return f"crop={w}:{h}:{x}:{y}"


def scaled(w: int, h: int) -> str:
    return f"scale={w}:{h}:flags=lanczos,{UPSCALE_SHARPEN_FILTER},setsar=1"


def build_stream_layout_filter(input_path: Path, width: int, height: int, layout: str) -> Optional[str]:
    """filter_complex producing [vout] for a stream template, or None to use the face-tracked crop
    (a full-screen camera shot, where stacking a cam over itself would look wrong)."""
    full: Rect = (0.0, 0.0, 1.0, 1.0)
    cam = None
    if layout != "gameplay_only":
        face = detect_facecam(input_path)
        if face and face[2] > FULLSCREEN_CAM_WIDTH:
            logger.info("Stream layout %s: full-screen camera, using face tracking", layout)
            return None
        cam = pad_face(face) if face else None
        logger.info("Stream layout %s: facecam %s", layout, "found" if cam else "not found, gameplay only")

    if cam is None or layout == "gameplay_only":
        return f"[0:v]{fit_crop(full, OUT_W / OUT_H, width, height)},{scaled(OUT_W, OUT_H)}[vout]"

    if layout == "floating_cam":
        band_h = min(OUT_H, round(OUT_W * height / width / 2) * 2)  # whole frame across the width
        cam_w, cam_h = 648, 460
        cam_y = max(0, (OUT_H - band_h) // 2 - cam_h - 24)
        return (
            "[0:v]split=3[bg][g][c];"
            "[bg]scale=540:960:force_original_aspect_ratio=increase,crop=540:960,"
            "gblur=sigma=14:steps=2,scale=1080:1920:flags=bilinear,setsar=1[bgv];"
            f"[g]{scaled(OUT_W, band_h)}[gv];"
            f"[c]{fit_crop(cam, cam_w / cam_h, width, height)},{scaled(cam_w, cam_h)}[cv];"
            f"[bgv][gv]overlay=0:(H-h)/2[t];[t][cv]overlay={(OUT_W - cam_w) // 2}:{cam_y}[vout]"
        )

    cam_h = round(OUT_H * CAM_SHARE / 2) * 2
    game_h = OUT_H - cam_h
    order = "[cv][gv]" if layout == "facecam_top" else "[gv][cv]"
    return (
        "[0:v]split=2[g][c];"
        f"[g]{fit_crop(full, OUT_W / game_h, width, height)},{scaled(OUT_W, game_h)}[gv];"
        f"[c]{fit_crop(cam, OUT_W / cam_h, width, height)},{scaled(OUT_W, cam_h)}[cv];"
        f"{order}vstack[vout]"
    )
