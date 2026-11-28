import json
from types import SimpleNamespace

import pytest

from src.services import video_service as video_service_module
from src.services.video_service import VideoService


class _EmptyAnalysis:
    summary = "No strong standalone segment found"
    key_topics = []
    most_relevant_segments = []


@pytest.mark.asyncio
async def test_process_video_complete_uses_fallback_when_ai_selects_no_segments(
    monkeypatch, tmp_path
):
    video_path = tmp_path / "source.mp4"
    video_path.write_bytes(b"placeholder")

    config = SimpleNamespace(
        max_video_duration=5400,
        clip_duration=30,
    )
    monkeypatch.setattr(video_service_module, "get_config", lambda: config)
    monkeypatch.setattr(
        VideoService,
        "resolve_local_video_path",
        staticmethod(lambda _url: video_path),
    )
    monkeypatch.setattr(
        VideoService,
        "_get_file_duration",
        staticmethod(lambda _path: 42.0),
    )

    async def fake_generate_transcript(
        _video_path, processing_mode="balanced", source_url=None
    ):
        return "[00:00 - 00:01] hello"

    async def fake_analyze_transcript(_transcript, clip_signals=None, exclude_ranges=None, clip_request=None):
        return _EmptyAnalysis()

    async def fake_run_in_thread(_func, *_args, **_kwargs):
        return None

    monkeypatch.setattr(
        VideoService,
        "generate_transcript",
        staticmethod(fake_generate_transcript),
    )
    monkeypatch.setattr(
        VideoService,
        "analyze_transcript",
        staticmethod(fake_analyze_transcript),
    )
    monkeypatch.setattr(video_service_module, "run_in_thread", fake_run_in_thread)

    result = await VideoService.process_video_complete(
        url="upload://source.mp4",
        source_type="video_url",
        processing_mode="fast",
    )

    assert result["segments_to_render"] == [
        {
            "start_time": "00:00",
            "end_time": "00:30",
            "text": "[00:00 - 00:01] hello",
            "relevance_score": 0.25,
            "reasoning": (
                "AI analysis did not identify a strong standalone segment, "
                "so LocalClip generated the first available portion of the video."
            ),
            "virality_score": 0,
            "hook_score": 0,
            "engagement_score": 0,
            "value_score": 0,
            "shareability_score": 0,
            "hook_type": "fallback",
            "hook_title": None,
        }
    ]
    analysis = json.loads(result["analysis_json"])
    assert analysis["most_relevant_segments"] == result["segments_to_render"]


def test_fallback_segment_caps_to_video_duration():
    segment = VideoService._build_fallback_segment(
        video_duration=12.0,
        transcript="short transcript",
        target_duration=30,
    )

    assert segment["start_time"] == "00:00"
    assert segment["end_time"] == "00:12"
    assert segment["hook_type"] == "fallback"


@pytest.mark.asyncio
async def test_cached_text_regenerates_missing_word_timings(monkeypatch, tmp_path):
    from unittest.mock import AsyncMock
    from src.config import Config
    source = tmp_path / "source.mp4"
    source.touch()
    monkeypatch.setattr(video_service_module, "get_config", Config)
    monkeypatch.setattr(VideoService, "resolve_local_video_path", lambda _: source)
    monkeypatch.setattr(VideoService, "_get_file_duration", lambda _: 19)
    monkeypatch.setattr(video_service_module, "load_cached_transcript_data", lambda _: None)
    transcribe = AsyncMock(return_value="Restored transcript")
    monkeypatch.setattr(VideoService, "generate_transcript", transcribe)
    analysis = json.dumps({"most_relevant_segments": [{"start_time": "00:00", "end_time": "00:17", "text": "Cached segment"}], "summary": "Test", "key_topics": []})
    await VideoService.process_video_complete(url="upload://source.mp4", source_type="video_url", cached_transcript="Cached transcript", cached_analysis_json=analysis)
    transcribe.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_picked_range_becomes_the_only_clip_without_asking_the_ai(monkeypatch, tmp_path):
    video_path = tmp_path / "source.mp4"
    video_path.write_bytes(b"placeholder")
    monkeypatch.setattr(
        video_service_module, "get_config", lambda: SimpleNamespace(max_video_duration=86400, clip_duration=30)
    )
    monkeypatch.setattr(VideoService, "resolve_local_video_path", staticmethod(lambda _url: video_path))
    monkeypatch.setattr(VideoService, "_get_file_duration", staticmethod(lambda _path: 7000.0))

    async def fake_generate_transcript(_video_path, processing_mode="balanced", source_url=None):
        return "[100:05 - 100:11] no way"

    async def no_ai(*_args, **_kwargs):
        raise AssertionError("a picked range must not run the AI search")

    async def fake_run_in_thread(_func, *_args, **_kwargs):
        return None

    monkeypatch.setattr(VideoService, "generate_transcript", staticmethod(fake_generate_transcript))
    monkeypatch.setattr(VideoService, "analyze_transcript", staticmethod(no_ai))
    monkeypatch.setattr(video_service_module, "run_in_thread", fake_run_in_thread)
    monkeypatch.setattr(VideoService, "_ground_segment_text", staticmethod(lambda *_args: "no way"))

    async def fake_title(text):
        assert text == "no way"
        return "He Did Not Just Do That", ["gta", "fail"]

    monkeypatch.setattr(video_service_module, "title_clip", fake_title)

    result = await VideoService.process_video_complete(
        url="upload://source.mp4", source_type="video_url", processing_mode="fast",
        exclude_ranges=[(0, 30)], manual_range=(5985, 6021),
    )

    (segment,) = result["segments_to_render"]
    assert (segment["start_time"], segment["end_time"]) == ("99:45", "100:21")
    assert segment["relevance_score"] == 1.0
    assert (segment["hook_title"], segment["hashtags"]) == ("He Did Not Just Do That", ["gta", "fail"])

    async def broken_title(_text):
        raise RuntimeError("Claude Code is signed out")

    monkeypatch.setattr(video_service_module, "title_clip", broken_title)
    result = await VideoService.process_video_complete(
        url="upload://source.mp4", source_type="video_url", processing_mode="fast",
        exclude_ranges=[(0, 30)], manual_range=(5985, 6021),
    )
    assert result["segments_to_render"][0]["hook_title"] is None  # still clipped, just untitled


def test_cut_down_clip_text_is_only_its_parts():
    words = [{"text": w, "start": i * 10_000, "end": i * 10_000 + 500} for i, w in enumerate("a b c d e f".split())]
    payload = {"start_time": "00:00", "end_time": "00:55", "text": "", "source_ranges": [[0, 15], [40, 55]]}
    assert VideoService._ground_segment_text(payload, {"words": words}) == "a b … e f"


@pytest.mark.asyncio
async def test_twitch_clips_are_imported_whole_and_vod_clips_sit_beside_the_ai_picks(monkeypatch, tmp_path):
    video_path = tmp_path / "source.mp4"
    video_path.write_bytes(b"placeholder")
    monkeypatch.setattr(
        video_service_module, "get_config", lambda: SimpleNamespace(max_video_duration=86400, clip_duration=30)
    )
    duration = {"value": 27.4}
    monkeypatch.setattr(VideoService, "_get_file_duration", staticmethod(lambda _path: duration["value"]))

    async def fake_run_in_thread(func, *args, **_kwargs):
        if func is video_service_module.align_vod_clip:
            return args[1]["start"] - 0.5  # the clip's sound was found half a second earlier
        return video_path if func is video_service_module.download_stream_video else None

    async def fake_generate_transcript(*_args, **_kwargs):
        return "[00:01 - 00:05] no way"

    async def no_ai(*_args, **_kwargs):
        raise AssertionError("an imported clip must not run the AI search")

    async def fake_title(_text):
        return "No Way", []

    monkeypatch.setattr(video_service_module, "run_in_thread", fake_run_in_thread)
    monkeypatch.setattr(VideoService, "generate_transcript", staticmethod(fake_generate_transcript))
    monkeypatch.setattr(VideoService, "analyze_transcript", staticmethod(no_ai))
    monkeypatch.setattr(VideoService, "_ground_segment_text", staticmethod(lambda *_args: "no way"))
    monkeypatch.setattr(video_service_module, "title_clip", fake_title)

    result = await VideoService.process_video_complete(url="https://clips.twitch.tv/FaintLightGull", source_type="twitch")
    (segment,) = result["segments_to_render"]
    assert (segment["start_time"], segment["end_time"], segment["reasoning"]) == ("00:00", "00:28", "Imported from Twitch.")
    assert segment["hook_type"] == "twitch_clip"

    duration["value"] = 3600.0

    async def ai_picks(*_args, **_kwargs):
        return SimpleNamespace(summary=None, key_topics=[], most_relevant_segments=[{"start_time": "00:10", "end_time": "00:40"}])

    async def vod_clips(vod_id):
        assert vod_id == "42"
        return [{"start": 100.5, "end": 130.5, "title": "HE DID IT", "creator": "viewer", "views": 3},
                {"start": 3599.5, "end": 3629.5, "title": None, "creator": "", "views": 1}]  # past the end: skipped

    monkeypatch.setattr(VideoService, "analyze_transcript", staticmethod(ai_picks))
    monkeypatch.setattr(video_service_module, "clips_from_vod", vod_clips)
    result = await VideoService.process_video_complete(url="https://www.twitch.tv/videos/42", source_type="twitch")
    ai, twitch_clip = result["segments_to_render"]
    assert ai["start_time"] == "00:10"
    assert (twitch_clip["start_time"], twitch_clip["end_time"], twitch_clip["source_ranges"]) == ("01:40", "02:10", [[100.0, 130.0]])
    assert (twitch_clip["hook_type"], twitch_clip["hook_title"]) == ("twitch_clip", "HE DID IT")
    assert "HE DID IT" not in result["analysis_json"]  # fetched fresh on a rerun, not cached

    result = await VideoService.process_video_complete(
        url="https://www.twitch.tv/videos/42", source_type="twitch", exclude_ranges=[(10, 40)]
    )
    assert [s["hook_type"] for s in result["segments_to_render"]] == [None]  # Find more: not added again
