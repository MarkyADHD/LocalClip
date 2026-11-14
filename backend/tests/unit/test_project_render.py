import json
import shutil
import subprocess

import pytest

from src.project_document import (
    Clip,
    Keyframe,
    ProjectDocument,
    TextStyle,
    chunk_bounds,
    new_document,
    timeline_words,
)
from src.services.project_service import probe, render_project

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is not installed")


def test_words_follow_clips_and_edits():
    document = new_document()
    document.clips = [
        Clip(id="a", track="v1", asset="x", start=0, duration=1, offset=2),
        Clip(id="b", track="v1", asset="x", start=1, duration=1, offset=6, speed=2),
        Clip(id="m", track="v1", asset="x", start=5, duration=1, offset=2, muted=True),
    ]
    document.wordEdits = {"x": {"1": "fixed", "2": " "}}
    source = [
        {"s": 2.2, "e": 2.5, "t": "one"},
        {"s": 6.0, "e": 7.0, "t": "two"},
        {"s": 7.0, "e": 7.5, "t": "dropped"},
        {"s": 9.0, "e": 9.5, "t": "outside"},
    ]
    words = timeline_words(document, lambda asset: source)
    assert [(w["text"], round(w["start"], 2), round(w["end"], 2)) for w in words] == [
        ("one", 0.2, 0.5),
        ("fixed", 1.0, 1.5),
    ]


def test_chunks_cover_the_timeline_on_frame_edges():
    document = new_document()
    document.clips = [
        Clip(id=f"c{i}", track="v1", asset="x", start=i * 1.5, duration=1.5, offset=0) for i in range(100)
    ]
    bounds = chunk_bounds(document)
    assert bounds[0][0] == 0 and bounds[-1][1] == pytest.approx(150)
    assert all(a[1] == b[0] for a, b in zip(bounds, bounds[1:]))
    assert all(abs(t * document.fps - round(t * document.fps)) < 1e-6 for b in bounds for t in b)
    # 60 s holds 40 of these clips, more than one command takes, so the minutes are split again.
    assert len(bounds) > 3


@needs_ffmpeg
def test_render_layers_text_captions_and_sound(tmp_path):
    def make(name, *args):
        subprocess.run(["ffmpeg", "-y", "-v", "error", *args, str(tmp_path / name)], check=True)

    make("a.mp4", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=6", "-f", "lavfi", "-i", "sine=440:d=6",
         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest")
    make("logo.png", "-f", "lavfi", "-i", "color=red:s=64x64", "-frames:v", "1")
    make("music.wav", "-f", "lavfi", "-i", "sine=220:d=6")
    directory = tmp_path / "project"
    for asset, name in (("a" * 12, "a.mp4"), ("b" * 12, "logo.png"), ("c" * 12, "music.wav")):
        folder = directory / "assets" / asset
        folder.mkdir(parents=True)
        meta = {"id": asset, "path": str(tmp_path / name), "status": "ready", **probe(str(tmp_path / name))}
        (folder / "meta.json").write_text(json.dumps(meta))
    (directory / "assets" / ("a" * 12) / "transcript.json").write_text(
        json.dumps({"words": [{"s": 1.0 + i * 0.4, "e": 1.3 + i * 0.4, "t": f"word{i}"} for i in range(8)]})
    )
    document = new_document()
    document.width, document.height = 320, 180
    document.clips = [
        Clip(id="c1", track="v1", asset="a" * 12, start=0, duration=1.5, offset=1),
        # A gap from 1.5 to 2 stays black and silent.
        Clip(id="c2", track="v1", asset="a" * 12, start=2, duration=2, offset=3, speed=1.5, fadeOut=0.5),
        Clip(id="c3", track="v2", asset="b" * 12, start=0.5, duration=3, scale=0.3,
             keys=[Keyframe(t=0, x=0.2, y=0.2, scale=0.3, opacity=1), Keyframe(t=2, x=0.8, y=0.8, scale=0.6, opacity=0.4)]),
        Clip(id="c4", track="a1", asset="c" * 12, start=0, duration=4, volume=0.3, fadeOut=1),
        Clip(id="c5", track="t1", start=0.5, duration=2, text=TextStyle(content="Hello\nworld"), fadeIn=0.3),
    ]
    document = ProjectDocument.model_validate(document.model_dump())
    exports = directory / "exports"
    exports.mkdir()
    (exports / "request-j.json").write_text(json.dumps({"document": document.model_dump(), "quality": "small"}))

    render_project(directory, "j")

    result = probe(str(exports / "j.mp4"))
    assert (result["width"], result["height"], result["hasAudio"]) == (320, 180, True)
    assert result["duration"] == pytest.approx(4, abs=0.1)
    assert not (exports / "chunks").exists()
