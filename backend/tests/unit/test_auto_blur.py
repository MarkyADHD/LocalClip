import shutil
import subprocess

import numpy as np
import pytest

from src.media import auto_blur
from src.media.auto_blur import apply_blurs, box_at, crop_blurs, decode, track


def test_sightings_become_tracks_that_hold_then_stop():
    box = (0.1, 0.1, 0.2, 0.2)
    moved = (0.15, 0.1, 0.2, 0.2)
    far = (0.7, 0.7, 0.1, 0.1)
    sightings = [
        (0.0, "Vape", box), (0.25, "Vape", moved), (0.5, "Nudity", far), (0.75, "Nudity", far),
        (3.0, "Vape", box), (3.25, "Vape", box),
    ]
    blurs = track(sightings, 0.25)
    assert [(b["label"], b["start"], b["end"], len(b["boxes"])) for b in blurs] == [
        ("Vape", 0.0, 1.0, 2),  # held 0.75 s after the last sighting
        ("Nudity", 0.25, 1.5, 2),  # far away: its own blur
        ("Vape", 2.75, 4.0, 2),  # a 2.75 s gap is a new blur
    ]
    # Seen once is a mic, a pen or a skin-coloured wall.
    assert track([(0.0, "Vape", box), (2.0, "Nudity", far)], 0.25) == []


def test_box_covers_the_motion_between_sightings():
    blur = track([(0.0, "Vape", (0.1, 0.1, 0.2, 0.2)), (0.25, "Vape", (0.3, 0.2, 0.2, 0.2))], 0.25)[0]
    assert box_at(blur, 0.1) == pytest.approx((0.1, 0.1, 0.4, 0.3))
    assert box_at(blur, 0.9) == pytest.approx((0.3, 0.2, 0.2, 0.2))
    assert box_at(blur, blur["end"]) is None
    inside = crop_blurs([blur], "200:100:100:50", 400, 200)[0]["boxes"][1]  # x 120..200 of a crop at 100..300
    assert inside == pytest.approx({"t": 0.25, "x": 0.1, "y": 0.0, "w": 0.4, "h": 0.3})  # cut at the crop top


def test_decode_scales_boxes_back_and_drops_weak_ones():
    boxes = np.array([[160, 80, 64, 32], [10, 10, 5, 5]], np.float32)  # the middle of a 320 letterbox
    scores = np.array([[0.9, 0.1], [0.1, 0.2]], np.float32)
    [(cls, score, box)] = decode(boxes, scores, 640 / 320, 640, 320, 0.3)
    assert cls == 0 and score == pytest.approx(0.9)
    assert box == pytest.approx((256 / 640, 128 / 320, 128 / 640, 64 / 320))


def test_slow_vape_sightings_hold_until_the_next_one():
    blurs = track([(1.0, "Vape", (0.1, 0.1, 0.1, 0.1)), (2.0, "Vape", (0.1, 0.1, 0.1, 0.1))], 1.0)
    assert [(b["start"], b["end"]) for b in blurs] == [(0.0, 3.0)]


def test_switch_is_on_until_turned_off(tmp_path, monkeypatch):
    monkeypatch.setattr(auto_blur, "_state_file", lambda: tmp_path / "auto_blur.json")
    monkeypatch.delenv("AUTO_BLUR")
    assert auto_blur.enabled()
    auto_blur.set_enabled(False)
    assert not auto_blur.enabled()


def _frame(path, t):
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(raw, np.uint8).reshape(180, 320).astype(int)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg required")
def test_only_the_box_is_blurred_and_only_while_it_is_on(tmp_path):
    source, output = tmp_path / "in.mkv", tmp_path / "out.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24:duration=3", "-c:v", "ffv1", str(source)],
        check=True,
    )
    blur = {"id": "a", "label": "Vape", "start": 1.0, "end": 2.0, "boxes": [{"t": 1.0, "x": 0.25, "y": 0.25, "w": 0.25, "h": 0.5}]}
    assert not apply_blurs(source, output, [])
    assert apply_blurs(source, output, [blur])
    before, after = _frame(source, 1.5), _frame(output, 1.5)
    changed = np.abs(before - after) > 12
    assert changed[45:135, 80:160].mean() > 0.3  # the box is blurred
    assert changed[:, 170:].mean() < 0.02 and changed[150:, :].mean() < 0.02  # the rest is the clip (re-encoded)
    assert (np.abs(_frame(source, 0.5) - _frame(output, 0.5)) > 12).mean() < 0.02  # not before it starts


def test_a_clip_is_scanned_once_and_reused_for_a_shorter_cut(tmp_path, monkeypatch):
    monkeypatch.setattr(auto_blur, "enabled", lambda: True)
    monkeypatch.setattr("src.media.stream_layouts.detect_facecam", lambda video: None)
    scans = []
    monkeypatch.setattr(auto_blur, "find_blurs", lambda video, cam: scans.append(video) or [{"label": "Vape", "start": 1.0, "end": 2.0}])
    source = tmp_path / "vod.mp4"
    assert auto_blur.find_clip_blurs(tmp_path / "a.mp4", source, [(10.0, 20.0), (30.0, 45.0)]) == [{"label": "Vape", "start": 1.0, "end": 2.0}]
    # The editor's cut (ends a little sooner) reuses it; a longer or different cut is scanned.
    assert auto_blur.find_clip_blurs(tmp_path / "b.mp4", source, [(10.0, 20.0), (30.0, 44.0)]) == [{"label": "Vape", "start": 1.0, "end": 2.0}]
    auto_blur.find_clip_blurs(tmp_path / "c.mp4", source, [(10.0, 20.0), (30.0, 75.0)])
    auto_blur.find_clip_blurs(tmp_path / "d.mp4", source, [(11.0, 20.0), (30.0, 45.0)])
    assert [p.name for p in scans] == ["a.mp4", "c.mp4", "d.mp4"]
