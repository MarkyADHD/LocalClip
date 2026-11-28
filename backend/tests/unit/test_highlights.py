import shutil
import subprocess

import pytest

from src.highlights import Scene, build_project, ground_scenes, select_scenes
from src.project_document import ProjectDocument, read_json
from src.services.project_service import prepare_asset_files


def scene(start, end, score, title="x"):
    return {"start": start, "end": end, "score": score, "title": title}


def test_auto_keeps_good_scenes_in_stream_order_without_overlap():
    picked = select_scenes(
        [scene(600, 900, 80, "heist"), scene(0, 100, 30, "intro"), scene(100, 400, 65, "chase"), scene(890, 1000, 70)],
        0,
    )
    assert [(s["start"], s["end"]) for s in picked] == [(100, 400), (600, 900), (900, 1000)]


def test_set_length_takes_the_best_that_fit_and_never_fills_with_downtime():
    scenes = [scene(0, 300, 90), scene(300, 900, 85), scene(900, 1200, 70), scene(1200, 1800, 20)]
    assert [s["start"] for s in select_scenes(scenes, 10)] == [0, 900]  # 600 s budget (+10%), the 600 s scene does not fit
    assert [s["start"] for s in select_scenes(scenes, 60)] == [0, 300, 900]  # room left, but score 20 is downtime
    assert [s["start"] for s in select_scenes([scene(0, 100, 10)], 0)] == [0]  # the best one at least


def test_scenes_snap_out_to_whole_lines_with_room_around():
    lines = [
        {"start_seconds": 10, "end_seconds": 25},
        {"start_seconds": 25, "end_seconds": 50},
        {"start_seconds": 50, "end_seconds": 70},
    ]
    [grounded] = ground_scenes([Scene(start_time="00:30", end_time="00:55", title=" Big  robbery ", score=80)], lines, 60)
    assert (grounded["start"], grounded["end"], grounded["title"]) == (24.0, 60, "Big robbery")
    assert ground_scenes([Scene(start_time="nope", end_time="00:55", title="x", score=80)], lines, 0) == []


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is not installed")
def test_build_project_lays_scenes_out_and_reuses_the_words(tmp_path):
    video = tmp_path / "twitch" / "123.mp4"
    video.parent.mkdir()
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=60:duration=6",
         "-f", "lavfi", "-i", "sine=duration=6", "-shortest", "-pix_fmt", "yuv420p", str(video)],
        check=True,
    )
    words = [{"text": "hello", "start": 1000, "end": 1400}, {"text": " ", "start": 1500, "end": 1600}]
    project_id, asset_id, source = build_project(
        str(tmp_path), "me", "My stream", video, words, [scene(1, 3, 80, "Heist"), scene(4, 6, 70, "Chase")]
    )
    directory = tmp_path / "projects" / project_id
    assert source.parent == directory / "uploads" and source.samefile(video)  # survives the VOD clean-up
    document = ProjectDocument.model_validate(read_json(directory / "document.json")["document"])
    assert (document.width, document.height, document.fps, document.captions.enabled) == (320, 180, 60, False)
    assert [(c.start, c.duration, c.offset) for c in document.clips] == [(0, 2, 1), (2, 2, 4)]
    assert [(c.time, c.title) for c in document.chapters] == [(0, "Heist"), (2, "Chase")]
    assert read_json(directory / "project.json")["user_id"] == "me"

    folder = directory / "assets" / asset_id
    prepare_asset_files(directory, asset_id)  # no Whisper: the words came along
    meta = read_json(folder / "meta.json")
    assert (meta["status"], meta["transcript"]) == ("ready", "ready")
    assert read_json(folder / "transcript.json")["words"] == [{"s": 1.0, "e": 1.4, "t": "hello"}]
