"""Builds the vape detector LocalClip downloads (vape.onnx), from the open YOLO-World model.

YOLO-World finds objects named in text; the names are baked into the ONNX file here, so the app
needs no text model or torch. The other names soak up look-alikes (a mic is a "microphone", not a vape).
Run by .github/workflows/blur-model.yml, which also checks it on public photos and publishes it.
"""

import shutil
import sys

from ultralytics import YOLOWorld

# Same list as VAPE_NAMES / the class order in backend/src/media/auto_blur.py.
NAMES = [
    "vape", "e-cigarette", "vape pen", "disposable vape",
    "microphone", "phone", "game controller", "pen", "can", "bottle", "earphones", "lighter", "remote control",
]

for size in sys.argv[1:] or ["s"]:
    model = YOLOWorld(f"yolov8{size}-worldv2.pt")
    model.set_classes(NAMES)
    path = model.export(format="onnx", imgsz=640, simplify=True)
    shutil.move(path, f"vape-{size}.onnx")
