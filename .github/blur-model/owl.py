"""Builds the vape detector LocalClip downloads: OWLv2 (open vocabulary, Apache-2.0) with the vape names baked in.

Exported to ONNX at a few input sizes, also int8-quantized, and each one scored with onnxruntime on public
Wikimedia Commons photos (people vaping should score high, look-alikes low) and timed on the CPU.
The app (backend/src/media/auto_blur.py) prepares frames the same way as `prepare` here.
"""

import json
import sys
import time
import urllib.parse
import urllib.request

import cv2
import numpy as np
import onnxruntime
import torch
from onnxruntime.quantization import QuantType, quantize_dynamic
from transformers import Owlv2ForObjectDetection, Owlv2Processor

HEADERS = {"User-Agent": "LocalClip-model-check/1.0"}


def commons(query: str, count: int) -> list[str]:
    params = {
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
        "gsrsearch": f"{query} filetype:bitmap", "gsrlimit": count, "prop": "imageinfo",
        "iiprop": "url", "iiurlwidth": 960,
    }
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)
    pages = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS)))["query"]["pages"]
    return [p["imageinfo"][0]["thumburl"] for p in pages.values() if p.get("imageinfo")]


def image(url: str):
    data = urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=30).read()
    return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)


MODEL = "google/owlv2-base-patch16-ensemble"
NAMES = ["a photo of a vape", "a photo of an e-cigarette", "a photo of a vape pen", "a photo of a disposable vape"]
MEAN = np.array([0.48145466, 0.4578275, 0.40821073], np.float32)
STD = np.array([0.26862954, 0.26130258, 0.27577711], np.float32)


class Vape(torch.nn.Module):
    """pixel_values -> (scores [1, patches, names], boxes [1, patches, 4] cx cy w h of the padded square)."""

    def __init__(self, owl, queries):
        super().__init__()
        self.owl = owl
        self.register_buffer("queries", queries)

    def forward(self, pixel_values):
        feature_map = self.owl.image_embedder(pixel_values=pixel_values, interpolate_pos_encoding=True)[0]
        b, h, w, d = feature_map.shape
        feats = feature_map.reshape(b, h * w, d)
        mask = torch.ones(self.queries.shape[:2], dtype=torch.bool)
        logits, _ = self.owl.class_predictor(feats, self.queries, mask)
        boxes = self.owl.box_predictor(feats, feature_map, interpolate_pos_encoding=True)
        return torch.sigmoid(logits), boxes


def prepare(frame: np.ndarray, size: int) -> np.ndarray:
    """BGR frame -> 1x3xSxS: padded black to a square at the bottom right, resized, CLIP-normalised."""
    h, w = frame.shape[:2]
    side = max(h, w)
    square = np.zeros((side, side, 3), np.uint8)
    square[:h, :w] = frame
    rgb = cv2.resize(square, (size, size), interpolation=cv2.INTER_AREA)[:, :, ::-1].astype(np.float32) / 255
    return ((rgb - MEAN) / STD).transpose(2, 0, 1)[None].copy()


def export(sizes):
    processor = Owlv2Processor.from_pretrained(MODEL)
    owl = Owlv2ForObjectDetection.from_pretrained(MODEL).eval()
    text = processor(text=[NAMES], return_tensors="pt")
    with torch.no_grad():
        queries = owl(**text, pixel_values=torch.zeros(1, 3, 960, 960)).text_embeds  # [1, names, dim]
    model = Vape(owl, queries).eval()
    paths = []
    for size in sizes:
        path = f"vape-owl-{size}.onnx"
        torch.onnx.export(
            model, (torch.zeros(1, 3, size, size),), path, input_names=["pixel_values"],
            output_names=["scores", "boxes"], opset_version=17, dynamo=False,
        )
        quantize_dynamic(path, f"vape-owl-{size}-int8.onnx", weight_type=QuantType.QInt8)
        paths += [path, f"vape-owl-{size}-int8.onnx"]
    return paths


if __name__ == "__main__":
    paths = export([int(s) for s in sys.argv[1:]] or [480, 640, 960])
    positives = sum((commons(q, 30) for q in ["man vaping electronic cigarette", "vaper using vape device", "woman vaping", "young vaper"]), [])
    negatives = sum((commons(q, 20) for q in ["podcast microphone", "person holding smartphone", "person drinking from can", "streamer gaming headset"]), [])
    frames = {}
    for url in dict.fromkeys(positives + negatives):
        try:
            if (frame := image(url)) is not None:
                frames[url] = frame
        except Exception:
            pass
    options = onnxruntime.SessionOptions()
    for path in paths:
        session = onnxruntime.InferenceSession(path, options, providers=["CPUExecutionProvider"])
        size = int(path.split("-")[2].split(".")[0])
        for group, urls in (("vaping", positives), ("look-alike", negatives)):
            values, took = [], []
            for url in dict.fromkeys(urls):
                if url in frames:
                    start = time.perf_counter()
                    scores, _ = session.run(None, {"pixel_values": prepare(frames[url], size)})
                    took.append(time.perf_counter() - start)
                    values.append(float(scores.max()))
            for threshold in (0.1, 0.2, 0.3, 0.4, 0.5):
                print(f"SUMMARY {path} {group}: {sum(v >= threshold for v in values)}/{len(values)} at >= {threshold}")
            print(f"SUMMARY {path} {group}: {np.mean(took) * 1000:.0f} ms per image")
