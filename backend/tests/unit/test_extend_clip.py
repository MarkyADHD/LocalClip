from unittest.mock import AsyncMock, MagicMock

from src.clip_source_map import load_clip_source_ranges, save_clip_source_ranges
from src.config import Config
from src.services import clip_service
from src.services.task_service import TaskService


async def test_extend_widens_the_outer_ranges_within_the_source(isolated_clip_edits, tmp_path, monkeypatch):
    config = Config()
    config.temp_dir = str(tmp_path)
    source = tmp_path / "vod.mp4"
    source.write_bytes(b"source")
    clip_path = tmp_path / "clip.mp4"
    clip_path.write_bytes(b"clip")
    save_clip_source_ranges(clip_path, [(20.0, 40.0), (45.0, 60.0)])  # cleanup cut a pause
    db = MagicMock(info={}, commit=AsyncMock())
    service = TaskService(db=db, config=config)
    service.clip_repo.get_clip_by_id = AsyncMock(return_value={
        "id": "clip", "task_id": "task", "file_path": str(clip_path), "start_time": "00:20", "end_time": "01:00"})
    service.clip_repo.update_clip = AsyncMock()
    service.task_repo.get_task_by_id = AsyncMock(return_value={"source_url": "upload://vod.mp4", "source_type": "video_url"})
    service.cache_repo.get_cache = AsyncMock(return_value={"video_path": str(source)})
    service._load_task_source_settings = AsyncMock(return_value={"output_format": "facecam_top"})
    monkeypatch.setattr("src.video_utils.ffprobe_duration", lambda path: 70.0)
    rendered = {}

    def render(src, start, end, out, **kwargs):
        assert db.commit.await_count == 1  # no transaction held open through the render
        rendered.update(start=start, end=end, ranges=kwargs["keep_ranges"], format=kwargs["output_format"])
        out.write_bytes(b"extended")
        return True

    monkeypatch.setattr(clip_service, "create_optimized_clip", render)

    await service.extend_clip("task", "clip", 30, 30)

    assert rendered == {"start": 0.0, "end": 70.0, "ranges": [(0.0, 40.0), (45.0, 70.0)], "format": "facecam_top"}
    args = service.clip_repo.update_clip.await_args.args
    assert args[4:7] == ("00:00", "01:10", 65.0)
    assert load_clip_source_ranges(tmp_path / "clips" / args[2]) == [(0.0, 40.0), (45.0, 70.0)]


async def test_raw_download_renders_source_without_captions(isolated_clip_edits, tmp_path, monkeypatch):
    config = Config()
    config.temp_dir = str(tmp_path)
    source = tmp_path / "vod.mp4"
    source.write_bytes(b"source")
    service = TaskService(db=AsyncMock(), config=config)
    service.task_repo.get_task_by_id = AsyncMock(return_value={"source_url": "upload://vod.mp4", "source_type": "video_url"})
    service.cache_repo.get_cache = AsyncMock(return_value={"video_path": str(source)})
    seen = {}

    def render(src, start, end, out, **kwargs):
        seen.update(kwargs)
        out.write_bytes(b"raw")
        return True

    monkeypatch.setattr(clip_service, "create_optimized_clip", render)
    clip = {"filename": "c1.mp4", "file_path": str(tmp_path / "c1.mp4"), "start_time": "00:10", "end_time": "00:40"}
    out = await service.render_raw_clip("task", clip)
    assert out.name == "c1_raw.mp4" and out.read_bytes() == b"raw"
    assert seen["output_format"] == "original" and not seen["add_subtitles"] and seen["hook_title"] is None
