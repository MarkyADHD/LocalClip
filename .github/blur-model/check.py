"""Scores vape-*.onnx on public Wikimedia Commons photos: vaping photos should score high, look-alikes low."""

import glob
import json
import time
import urllib.parse
import urllib.request

import cv2
import numpy as np
import onnxruntime

from export import NAMES

VAPES = 4  # the first names are vapes
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
    data = urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS)).read()
    return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)


def detect(session, frame):
    size = session.get_inputs()[0].shape[2]
    h, w = frame.shape[:2]
    scale = size / max(h, w)
    canvas = np.full((size, size, 3), 114, np.uint8)
    canvas[: round(h * scale), : round(w * scale)] = cv2.resize(frame, (round(w * scale), round(h * scale)))
    blob = cv2.dnn.blobFromImage(canvas, 1 / 255, swapRB=True)
    out = session.run(None, {session.get_inputs()[0].name: blob})[0][0].T  # rows: cx cy w h scores...
    best = out[:, 4:].argmax(1)
    return out[:, 4:].max(1), best


sets = {
    "vaping": sum((commons(q, 25) for q in ["vaping person", "electronic cigarette vaper", "vape pen", "disposable vape"]), []),
    "look-alike": sum((commons(q, 20) for q in ["podcast microphone", "gamer headset streaming", "person drinking can", "person holding smartphone"]), []),
}
for path in sorted(glob.glob("vape-*.onnx")):
    session = onnxruntime.InferenceSession(path, providers=["CPUExecutionProvider"])
    for name, urls in sets.items():
        scores, took = [], []
        for url in urls:
            try:
                frame = image(url)
            except Exception:
                continue
            if frame is None:
                continue
            start = time.perf_counter()
            score, best = detect(session, frame)
            took.append(time.perf_counter() - start)
            vape = float(score[best < VAPES].max()) if (best < VAPES).any() else 0.0
            scores.append(vape)
            print(f"{path} {name} {vape:.2f} {url.rsplit('/', 1)[-1][:70]}")
        for threshold in (0.15, 0.25, 0.35, 0.5):
            hits = sum(s >= threshold for s in scores)
            print(f"SUMMARY {path} {name}: {hits}/{len(scores)} at >= {threshold}")
        print(f"SUMMARY {path} {name}: {np.mean(took) * 1000:.0f} ms per image on the CPU")
