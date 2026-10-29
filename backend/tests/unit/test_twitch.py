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
    monkeypatch.setattr(timeline, "detect_loud_spans", lambda _p: [])
    transcript = "[01:00:10 - 01:00:14] okay we push now\n[01:00:40 - 01:00:44] chat CLIP THAT right now"
    summary = timeline.build_clip_signal_summary(Path("x.mp4"), transcript, ["- [05:00 - 05:10] score=4.0: chat"])
    lines = summary.splitlines()
    assert lines[1].startswith("- [01:00:10 - 01:00:49] score=10.0: STREAMER SAID"), lines
    assert lines[2] == "- [05:00 - 05:10] score=4.0: chat"
    assert timestamp_label(59) == "00:59" and timestamp_label(3600) == "01:00:00"


def test_loud_spikes_found_across_a_long_stream(monkeypatch, tmp_path):
    # 3 hours of -30 dB talk with a +12 dB shout every hour: all three must show up,
    # not just the single loudest one.
    levels = [-30.0 + (i % 7) * 0.3 for i in range(3 * 3600)]
    for shout in (1000, 5000, 9000):
        for i in range(shout, shout + 4):
            levels[i] = -18.0
    monkeypatch.setattr(timeline, "audio_rms_per_second", lambda _p: levels)

    spans = timeline.detect_loud_spans(tmp_path / "vod.mp4")

    assert len(spans) == 3, spans
    for (a, b), shout in zip(spans, (1000, 5000, 9000)):
        assert a <= shout + 3 and b >= shout


def test_quiet_silence_breaks_are_not_loud_spikes(monkeypatch, tmp_path):
    levels = [-90.0] * 600 + [-60.0] * 10 + [-90.0] * 600  # a mic bump in silence
    monkeypatch.setattr(timeline, "audio_rms_per_second", lambda _p: levels)
    assert timeline.detect_loud_spans(tmp_path / "vod.mp4") == []


def test_signal_hints_reach_every_part_of_a_long_vod(monkeypatch):
    monkeypatch.setattr(timeline, "detect_loud_spans", lambda _p: [])
    transcript = "\n".join(
        f"[{timestamp_label(t)} - {timestamp_label(t + 4)}] what the hell was that!" for t in range(0, 4 * 3600, 30)
    )
    summary = timeline.build_clip_signal_summary(Path("x.mp4"), transcript)
    hint_lines = summary.splitlines()[1:]
    # 3 hints for each of the 24 ten-minute stretches, not 12 for the whole VOD.
    assert len(hint_lines) == 72
    assert hint_lines[-1] != hint_lines[0] and any(line.startswith("- [03:") for line in hint_lines)
