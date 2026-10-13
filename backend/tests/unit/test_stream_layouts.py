import subprocess

import pytest

from src.media import stream_layouts as sl


def test_stable_face_prefers_the_box_that_stays_put():
    cam = (0.75, 0.70, 0.08, 0.14)
    frames = [[cam, (0.1 * i, 0.3, 0.05, 0.09)] for i in range(8)]  # game faces move around
    assert sl.stable_face(frames) == cam
    assert sl.stable_face([[], [], [(0.5, 0.5, 0.1, 0.1)], []] * 3) is None


def test_fit_crop_keeps_aspect_and_stays_inside():
    w, h, x, y = map(int, sl.fit_crop((0.9, 0.8, 0.1, 0.2), 1080 / 768, 1920, 1080)[5:].split(":"))
    assert abs(w / h - 1080 / 768) < 0.02 and x + w <= 1920 and y + h <= 1080 and w % 2 == 0


@pytest.mark.parametrize("layout", sorted(sl.STREAM_LAYOUTS))
def test_layout_filters_render_1080x1920(tmp_path, monkeypatch, layout):
    monkeypatch.setattr(sl, "detect_facecam", lambda path: (0.78, 0.68, 0.08, 0.14))
    src = tmp_path / "src.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=1920x1080:duration=1:rate=30",
                    "-pix_fmt", "yuv420p", str(src)], check=True, capture_output=True)
    graph = sl.build_stream_layout_filter(src, 1920, 1080, layout)
    out = tmp_path / "out.mp4"
    subprocess.run(["ffmpeg", "-y", "-i", str(src), "-filter_complex", graph, "-map", "[vout]", str(out)],
                   check=True, capture_output=True)
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                            "-of", "csv=p=0", str(out)], check=True, capture_output=True, text=True)
    assert probe.stdout.strip() == "1080,1920"


def test_fullscreen_camera_falls_back_to_face_tracking(monkeypatch):
    monkeypatch.setattr(sl, "detect_facecam", lambda path: (0.3, 0.2, 0.4, 0.6))
    assert sl.build_stream_layout_filter(None, 1920, 1080, "facecam_top") is None
