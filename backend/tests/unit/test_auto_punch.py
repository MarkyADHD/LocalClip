import shutil
import subprocess

import pytest

from src.media import reframing

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg required")


def _clip(path, burst: bool):
    # 12 s of quiet tone, with a loud burst from 6 s to 6.5 s.
    volume = "volume='if(between(t,6,6.5),1,0.05)':eval=frame" if burst else "volume=0.05"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=24:duration=12",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=12",
         "-af", volume, "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)],
        check=True,
    )


def test_generated_clip_punches_in_on_the_loudest_moment(tmp_path):
    _clip(tmp_path / "in.mp4", burst=True)
    assert reframing.loudest_moment(tmp_path / "in.mp4") == pytest.approx(6, abs=0.3)
    chain = reframing.punch_in_chain(tmp_path / "in.mp4", "vertical")
    assert "between(t,5." in chain
    ok, width, height = reframing.render_reframed_clip_ffmpeg(tmp_path / "in.mp4", tmp_path / "out.mp4", "vertical")
    assert ok and (width, height) == (1080, 1920)


def test_a_flat_clip_gets_no_punch_in(tmp_path):
    _clip(tmp_path / "in.mp4", burst=False)
    assert reframing.loudest_moment(tmp_path / "in.mp4") is None
