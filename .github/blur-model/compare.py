"""One-off: vape recall of open-vocabulary detectors on Commons photos of people vaping, and their CPU time."""

import time

import numpy as np
import torch
from PIL import Image
from transformers import Owlv2ForObjectDetection, Owlv2Processor
from ultralytics import YOLOE, YOLOWorld

from check import commons, image

VAPE = ["vape", "e-cigarette", "vape pen", "disposable vape"]
positives = sum((commons(q, 30) for q in ["man vaping electronic cigarette", "vaper using vape device", "woman vaping", "young vaper"]), [])
negatives = sum((commons(q, 20) for q in ["podcast microphone", "person holding smartphone", "person drinking from can"]), [])
frames = {}
for url in dict.fromkeys(positives + negatives):
    try:
        frame = image(url)
        if frame is not None:
            frames[url] = frame
    except Exception:
        pass
print(f"{len(frames)} images")

world = YOLOWorld("yolov8l-worldv2.pt")
world.set_classes(VAPE)
yoloe = YOLOE("yoloe-11l-seg.pt")
yoloe.set_classes(VAPE, yoloe.get_text_pe(VAPE))
processor = Owlv2Processor.from_pretrained("google/owlv2-base-patch16-ensemble")
owl = Owlv2ForObjectDetection.from_pretrained("google/owlv2-base-patch16-ensemble").eval()
queries = processor(text=[[f"a photo of a {v}" for v in VAPE]], return_tensors="pt")


def owl_score(frame):
    pixels = processor(images=Image.fromarray(frame[:, :, ::-1]), return_tensors="pt")["pixel_values"]
    with torch.no_grad():
        out = owl(input_ids=queries["input_ids"], attention_mask=queries["attention_mask"], pixel_values=pixels)
    return float(torch.sigmoid(out.logits).max())


models = {
    "yolo-world-l": lambda f: max([float(b.conf) for b in world.predict(f, conf=0.01, verbose=False)[0].boxes] or [0]),
    "yoloe-11l": lambda f: max([float(b.conf) for b in yoloe.predict(f, conf=0.01, verbose=False)[0].boxes] or [0]),
    "owlv2-base": owl_score,
}
for name, score in models.items():
    for group, urls in (("vaping", positives), ("look-alike", negatives)):
        values, took = [], []
        for url in urls:
            if url in frames:
                start = time.perf_counter()
                values.append(score(frames[url]))
                took.append(time.perf_counter() - start)
                print(f"{name} {group} {values[-1]:.2f} {url.rsplit('/', 1)[-1][:60]}")
        for threshold in (0.1, 0.2, 0.3, 0.5):
            print(f"SUMMARY {name} {group}: {sum(v >= threshold for v in values)}/{len(values)} at >= {threshold}")
        print(f"SUMMARY {name} {group}: {np.mean(took) * 1000:.0f} ms per image")
