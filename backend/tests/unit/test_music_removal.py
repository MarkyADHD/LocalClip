import json
import shutil
import subprocess

import numpy as np
import pytest

from src.media import music
from src.project_document import Clip, ProjectDocument, music_needs, new_document
from src.services.project_service import probe, render_project


def test_stft_round_trip_is_exact():
    rng = np.random.default_rng(0)
    audio = rng.standard_normal((2, 44100)).astype(np.float32)
    for n, hop, scale in ((1024, 256, 32), (2048, 512, 1), (8192, 256, 90.5)):
        back = music._istft(music._stft(audio, n, hop, scale), n, hop, scale, audio.shape[1])
        assert np.allclose(back, audio, atol=1e-4)


def test_needs_cover_marked_clips_only():
    document = new_document()
    document.clips = [
        Clip(id="a", track="v1", asset="x", start=0, duration=10, offset=40, noMusic=True),
        Clip(id="b", track="v1", asset="x", start=10, duration=5, offset=100),
        Clip(id="c", track="v1", asset="y", start=15, duration=30, offset=0, speed=2, noMusic=True),
    ]
    assets = {"x": {"kind": "video", "hasAudio": True, "duration": 200}, "y": {"kind": "video", "hasAudio": True, "duration": 50}}
    # 40..50.5 s of x is blocks 1-2 (24 s each); 0..60.5 s of y stops at its end (block 2).
    assert music_needs(document, assets) == {"x": [1, 2], "y": [0, 1, 2]}


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is not installed")
def test_export_plays_the_music_free_blocks_in_step(tmp_path):
    source = tmp_path / "a.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=160x90:r=30:d=30", "-f", "lavfi",
                    "-i", "aevalsrc='if(gte(t,25),0.5*sin(2*PI*440*t),0)':s=48000:d=30", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest",
                    str(source)], check=True)
    directory = tmp_path / "project"
    folder = directory / "assets" / ("a" * 12)
    (folder / "music-free").mkdir(parents=True)
    (folder / "meta.json").write_text(json.dumps({"id": "a" * 12, "path": str(source), "status": "ready", **probe(str(source))}))
    # Stand-in "music-free" blocks: silence, then a loud tone from 25 s of the source on.
    for k, expr, seconds in ((0, "0", 24), (1, "if(gte(t,1),0.5*sin(2*PI*880*t),0)", 6)):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"aevalsrc='{expr}':s=44100:c=stereo:d={seconds}",
                        "-c:a", "flac", str(folder / "music-free" / f"{k}.flac")], check=True)
    exports = directory / "exports"
    exports.mkdir(exist_ok=True)

    def export(no_music: bool):
        document = new_document()
        document.width, document.height = 160, 90
        document.clips = [Clip(id="c", track="v1", asset="a" * 12, start=0, duration=4, offset=22, noMusic=no_music)]
        (exports / "request-j.json").write_text(json.dumps({"document": document.model_dump(), "quality": "small"}))
        render_project(directory, "j")
        pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(exports / "j.mp4"), "-f", "f32le", "-ac", "1", "-ar", "48000", "-"],
                             capture_output=True, check=True).stdout
        sound = np.frombuffer(pcm, np.float32)
        spectrum = np.abs(np.fft.rfft(sound[3 * 48000 :]))
        return np.argmax(np.abs(sound) > 0.2) / 48000, np.argmax(spectrum) * 48000 / (len(sound) - 3 * 48000)

    original, music_free = export(False), export(True)
    # The music-free sound (880 Hz) replaces the original (440 Hz), starting at the same moment, 3 s in.
    assert original[1] == pytest.approx(440, abs=5) and music_free[1] == pytest.approx(880, abs=5)
    assert original[0] == pytest.approx(3.0, abs=0.03)
    # Within 10 ms of the original (lip sync); AAC in the test source and the export blurs the onset a little.
    assert music_free[0] == pytest.approx(original[0], abs=0.01)
