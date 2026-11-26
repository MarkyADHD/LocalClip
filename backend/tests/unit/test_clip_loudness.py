import shutil
import subprocess

import numpy as np
import pytest

from src.media.ffmpeg import build_audio_output_args

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg required")


def _rms_db(path, start, end):
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(start), "-t", str(end - start), "-i", str(path),
         "-f", "f32le", "-ac", "1", "-"],
        capture_output=True, check=True,
    ).stdout
    return 20 * np.log10(np.sqrt((np.frombuffer(raw, np.float32) ** 2).mean()))


def test_one_gain_for_the_whole_clip(tmp_path):
    # 6 s quiet talk-level tone, then 6 s 20 dB louder: the quiet part must not be pumped up.
    source = tmp_path / "in.wav"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=12",
         "-af", "volume='if(lt(t,6),0.05,0.5)':eval=frame", str(source)],
        check=True,
    )
    out = tmp_path / "out.m4a"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(source), *build_audio_output_args(True, source), str(out)], check=True)
    quiet = _rms_db(out, 1, 5) - _rms_db(source, 1, 5)
    loud = _rms_db(out, 7, 11) - _rms_db(source, 7, 11)
    assert abs(quiet - loud) < 1
    assert _rms_db(out, 7, 11) < -1.5  # limited below full scale
