import json
import shutil
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.editor_document import (
    EditDocument,
    RevisionConflict,
    caption_groups,
    editor_dir,
    layout_filter,
    mapped_words,
    output_size,
    render_document,
    save_document,
)


def document(**changes):
    return EditDocument.model_validate(
        {
            "segments": [
                {"id": "a", "start": 0.25, "end": 1.25},
                {"id": "b", "start": 1.5, "end": 2},
            ],
            "words": [
                {"id": "w", "start": 0.5, "end": 1, "text": "Hello", "highlight": True}
            ],
            **changes,
        }
    )


def test_revisions_protect_other_tabs_and_original(tmp_path):
    draft = document()
    saved = save_document(tmp_path, draft, 0, 2)
    assert saved["revision"] == 1
    with pytest.raises(RevisionConflict):
        save_document(tmp_path, document(muted=True), 0, 2)
    assert json.loads((tmp_path / "draft.json").read_text()) == saved
    assert save_document(tmp_path, document(muted=True), 1, 2)["revision"] == 2


@pytest.mark.parametrize(
    "change",
    [
        {"volume": float("nan")},
        {"volume": float("inf")},
        {"framing": {"x": -1}},
        {"captions": {"font": "../../secret"}},
        {"segments": []},
        {"segments": [{"id": "a", "start": 1, "end": 0.5}]},
        {"words": [{"id": "a", "start": 1, "end": 1, "text": "bad"}]},
        {"effects": {"blur": 1000}},
    ],
)
def test_rejects_unrenderable_edits(change):
    with pytest.raises(ValidationError):
        document(**change)


def test_source_bounds_and_duplicate_ids_are_validated():
    with pytest.raises(ValueError):
        document().validate_duration(1)
    with pytest.raises(ValueError):
        document(
            segments=[
                {"id": "a", "start": 0, "end": 1},
                {"id": "a", "start": 1, "end": 2},
            ]
        ).validate_duration(2)


def test_reordered_cuts_project_caption_timing():
    doc = document(
        segments=[
            {"id": "b", "start": 0.75, "end": 1.5},
            {"id": "a", "start": 0, "end": 0.75},
        ]
    )
    words = mapped_words(doc)
    assert [(w["start"], w["end"]) for w in words] == [(0, 0.25), (1.25, 1.5)]
    assert all(w["highlight"] for w in words)
    assert len(caption_groups(words, 4)) == 2
    assert output_size(doc, 1920, 1080) == (1080, 1920)
    assert editor_dir("/tmp", "../task", "../clip", "../file").parent == Path(
        "/tmp/editor"
    )


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg required")
@pytest.mark.parametrize("audio", [True, False])
def test_real_render_preserves_cuts_dimensions_and_audio(tmp_path, audio):
    args = [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=320x180:rate=24:duration=2",
    ]
    if audio:
        args += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if audio:
        args += ["-c:a", "aac"]
    subprocess.run(
        args + [str(tmp_path / "clean.mp4")], check=True, capture_output=True
    )
    doc = document(
        framing={"aspect": "original", "fit": "cover", "zoom": 1.2, "x": 0.2},
        muted=True,
    )
    render_document(tmp_path, "a" * 32, doc, "tiktok")
    output = tmp_path / f"export-{'a' * 32}.mp4"
    probe = json.loads(
        subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(output),
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    assert (video["width"], video["height"]) == (320, 180)
    assert float(probe["format"]["duration"]) == pytest.approx(1.5, abs=0.1)
    assert any(s["codec_type"] == "audio" for s in probe["streams"]) == audio
    if audio:
        import numpy as np

        pcm = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(output),
                "-f",
                "f32le",
                "-ac",
                "1",
                "-",
            ],
            capture_output=True,
            check=True,
        ).stdout
        assert float(np.max(np.abs(np.frombuffer(pcm, dtype="float32")))) < 0.001


def test_cancelled_render_does_not_publish_output(tmp_path):
    from src.editor_document import run_render

    job_id = "b" * 32
    (tmp_path / f"cancel-{job_id}").touch()
    with pytest.raises(InterruptedError):
        run_render(["sleep", "10"], tmp_path, job_id, 1)


def _pcm(path, rate=8000):
    import numpy as np

    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(rate), "-"],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(raw, dtype="float32")


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg required")
def test_bleep_beeps_only_over_the_word_and_stars_the_caption(tmp_path):
    from src.editor_document import censor, write_ass

    assert censor("fucking,") == "f******,"
    # A silent clip, so any sound in the export is the bleep tone.
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24:duration=3",
         "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-shortest", "-c:v", "libx264",
         "-pix_fmt", "yuv420p", "-c:a", "aac", str(tmp_path / "clean.mp4")],
        check=True, capture_output=True,
    )
    doc = document(
        segments=[{"id": "a", "start": 0, "end": 3}],
        words=[{"id": "w", "start": 1, "end": 1.5, "text": "shit", "bleep": True}],
    )
    write_ass(tmp_path / "c.ass", doc, 1080, 1920)
    assert "s***" in (tmp_path / "c.ass").read_text() and "shit" not in (tmp_path / "c.ass").read_text()
    render_document(tmp_path, "b" * 32, doc, "tiktok")
    pcm = _pcm(tmp_path / f"export-{'b' * 32}.mp4")
    assert abs(pcm[int(1.1 * 8000):int(1.4 * 8000)]).max() > 0.05
    assert abs(pcm[: int(0.8 * 8000)]).max() < 0.01 and abs(pcm[int(1.8 * 8000):]).max() < 0.01



def test_spoken_word_and_title_reach_the_captions(tmp_path):
    from src.editor_document import write_ass

    doc = document(
        segments=[{"id": "a", "start": 0, "end": 2}],
        words=[
            {"id": "1", "start": 0, "end": 0.4, "text": "oh"},
            {"id": "2", "start": 0.5, "end": 1, "text": "no"},
        ],
        captions={"active": True, "uppercase": True, "accent": "#00FF00"},
        title="Wait for it",
    )
    write_ass(tmp_path / "c.ass", doc, 1080, 1920)
    events = [
        line for line in (tmp_path / "c.ass").read_text().splitlines() if line.startswith("Dialogue")
    ]
    assert len(events) == 3 and "WAIT" in events[0]
    green = "{\\c&H0000FF00&}"
    # Each word is lit while it is spoken, and until the next one starts.
    assert green + "OH" in events[1] and green + "NO" not in events[1]
    assert "0:00:00.00,0:00:00.50" in events[1]
    assert green + "NO" in events[2] and green + "OH" not in events[2]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is required")
@pytest.mark.parametrize("layout", ["crop", "cam_top", "cam_bottom", "floating"])
@pytest.mark.parametrize("fit", ["cover", "contain"])
def test_every_layout_renders_at_the_output_size(tmp_path, layout, fit):
    doc = document(framing={"layout": layout, "fit": fit, "zoom": 1.3, "x": 0.2})
    out = tmp_path / "out.png"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=1280x720:duration=0.1",
         "-filter_complex", "[0:v]null[video];" + layout_filter(doc.framing, 1280, 720, 1080, 1920),
         "-map", "[framed]", "-frames:v", "1", str(out)],
        check=True,
    )
    size = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert size == "1080,1920"
