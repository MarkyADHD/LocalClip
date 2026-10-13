from pathlib import Path

from src.media import timeline
from src.services.video_service import VideoService
from src.twitch import chat_spikes, get_twitch_video_id, timestamp_label


def test_twitch_urls():
    assert get_twitch_video_id("https://www.twitch.tv/videos/2896208513") == "2896208513"
    assert get_twitch_video_id("https://twitch.tv/somestreamer/video/123?t=1h") == "123"
    assert get_twitch_video_id("https://www.twitch.tv/somestreamer") is None
    assert VideoService.determine_source_type("https://www.twitch.tv/videos/42") == "twitch"
    assert VideoService.resolve_local_video_path("https://www.twitch.tv/videos/42").name == "42.mp4"


def test_chat_spike_found_and_shifted_back():
    msgs = [(t, "hi") for t in range(0, 600, 10)] + [(308 + i * 0.1, "KEKW KEKW") for i in range(40)]
    spans = chat_spikes(msgs, 600)
    assert len(spans) == 1 and spans[0][0] <= 300 <= spans[0][1] + 5, spans


def test_clip_that_becomes_top_signal(monkeypatch):
    monkeypatch.setattr(timeline, "detect_audio_peak_times", lambda _p: [])
    transcript = "[01:00:10 - 01:00:14] okay we push now\n[01:00:40 - 01:00:44] chat CLIP THAT right now"
    summary = timeline.build_clip_signal_summary(Path("x.mp4"), transcript, ["- [05:00 - 05:10] score=4.0: chat"])
    lines = summary.splitlines()
    assert lines[1].startswith("- [01:00:10 - 01:00:49] score=10.0: STREAMER SAID"), lines
    assert lines[2] == "- [05:00 - 05:10] score=4.0: chat"
    assert timestamp_label(59) == "00:59" and timestamp_label(3600) == "01:00:00"
