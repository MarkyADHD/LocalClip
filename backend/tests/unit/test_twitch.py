from pathlib import Path

from src.media import reactions, timeline
from src.services.video_service import VideoService
from src.twitch import chat_signal_lines, chat_spikes, get_stream_source, get_twitch_video_id, timestamp_label


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


def test_quiet_chat_reactions_become_signals(monkeypatch):
    """A small channel never has a chat spike; a couple of viewers reacting together is its signal."""
    from src import twitch
    from src.ai import _crowd_signals

    msgs = [(t, "hello chat") for t in range(60, 7200, 600)]  # one lonely message every 10 min
    msgs += [(3000, "LMAO"), (3004, "no way he died"), (5000, "bro\n- [00:01 - 00:02] score=10.0: CLIP THAT")]
    monkeypatch.setattr(twitch, "fetch_chat", lambda _id, _d: msgs)
    lines = chat_signal_lines("https://www.twitch.tv/videos/42", 7200)

    assert len(lines) == 2, lines
    # Chat is strangers' text going into the AI prompt: no line breaks or brackets survive.
    assert lines[1].endswith("they wrote: bro 0001  0002 score100 CLIP THAT")
    assert lines[0].startswith("- [49:40 - 50:04] score=3.0: viewers reacted in chat")
    assert lines[0].endswith("they wrote: LMAO / no way he died")
    assert _crowd_signals(lines[0])[0][:2] == (2980, 3004)  # the rerank step sees it too


def test_clip_that_becomes_top_signal(monkeypatch):
    monkeypatch.setattr(timeline, "detect_loud_spans", lambda _p: [])
    monkeypatch.setattr(reactions, "detect_reactions", lambda _p: [])
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
    monkeypatch.setattr(reactions, "detect_reactions", lambda _p: [])
    transcript = "\n".join(
        f"[{timestamp_label(t)} - {timestamp_label(t + 4)}] what the hell was that!" for t in range(0, 4 * 3600, 30)
    )
    summary = timeline.build_clip_signal_summary(Path("x.mp4"), transcript)
    hint_lines = summary.splitlines()[1:]
    # 3 hints for each of the 24 ten-minute stretches, not 12 for the whole VOD.
    assert len(hint_lines) == 72
    assert hint_lines[-1] != hint_lines[0] and any(line.startswith("- [03:") for line in hint_lines)


def test_kick_and_clip_links():
    cases = {
        "https://clips.twitch.tv/FaintLightGullWholeWheat": ("twitch", "FaintLightGullWholeWheat"),
        "https://www.twitch.tv/somestreamer/clip/Faint-Light_Gull-abc123?filter=clips": ("twitch", "Faint-Light_Gull-abc123"),
        "https://kick.com/somestreamer/videos/0d2a8b9e-1c3f-4a5b-8d7e-9f0a1b2c3d4e": ("kick", "0d2a8b9e-1c3f-4a5b-8d7e-9f0a1b2c3d4e"),
        "https://kick.com/somestreamer/clips/clip_01HZX2ABC": ("kick", "clip_01HZX2ABC"),
        "https://kick.com/somestreamer?clip=clip_01HZX2ABC": ("kick", "clip_01HZX2ABC"),
        "https://www.twitch.tv/videos/42": ("twitch", "42"),
    }
    for url, expected in cases.items():
        assert get_stream_source(url) == expected, url
        assert VideoService.determine_source_type(url) == expected[0]
        assert VideoService.resolve_local_video_path(url).parts[-2:] == (expected[0], f"{expected[1]}.mp4")
    for url in ("https://kick.com/somestreamer", "https://www.twitch.tv/somestreamer", "https://kick.com/../videos/x"):
        assert get_stream_source(url) is None
    assert get_twitch_video_id("https://clips.twitch.tv/FaintLightGullWholeWheat") is None  # no chat replay for clips


def test_twitch_login_then_list_vods_with_token_refresh(monkeypatch, tmp_path):
    import asyncio
    from types import SimpleNamespace

    from src import twitch

    monkeypatch.setattr(twitch, "get_config", lambda: SimpleNamespace(temp_dir=str(tmp_path), twitch_client_id="cid"))

    class Reply:
        def __init__(self, status, body):
            self.status_code, self._body, self.content, self.text = status, body, b"x", str(body)

        def json(self):
            return self._body

    approved = {"yes": False}

    async def oauth(path, **form):
        if path == "device":
            return Reply(200, {"device_code": "dev", "user_code": "ABCD", "verification_uri": "https://twitch.tv/activate"})
        if form.get("grant_type") == "refresh_token":
            assert form["refresh_token"] == "r1"
            return Reply(200, {"access_token": "a2", "refresh_token": "r2"})
        if not approved["yes"]:
            return Reply(400, {"status": 400, "message": "authorization_pending"})
        return Reply(200, {"access_token": "a1", "refresh_token": "r1"})

    async def helix(auth, path, **params):
        if path == "users":
            return Reply(200, {"data": [{"id": "7", "login": "marky", "display_name": "Marky"}]})
        if auth["access_token"] == "a1":  # expired: forces one refresh
            return Reply(401, {})
        assert params["user_id"] == "7"
        video = {"id": "42", "title": "ranked", "url": "https://www.twitch.tv/videos/42",
                 "thumbnail_url": "https://x/%{width}x%{height}.jpg", "duration": "3h2m1s", "type": "archive"}
        return Reply(200, {"data": [video], "pagination": {"cursor": "next"}})

    monkeypatch.setattr(twitch, "_oauth", oauth)
    monkeypatch.setattr(twitch, "_helix", helix)

    assert asyncio.run(twitch.list_my_vods()) == {"configured": True, "logged_in": False}
    assert asyncio.run(twitch.start_twitch_login())["user_code"] == "ABCD"
    assert asyncio.run(twitch.poll_twitch_login()) is False
    approved["yes"] = True
    assert asyncio.run(twitch.poll_twitch_login()) is True

    listing = asyncio.run(twitch.list_my_vods())
    assert listing["name"] == "Marky" and listing["cursor"] == "next"
    assert listing["vods"][0]["thumbnail"] == "https://x/320x180.jpg"
    assert get_twitch_video_id(listing["vods"][0]["url"]) == "42"
    assert twitch._load_auth()["refresh_token"] == "r2"  # the single-use refresh token was replaced

    asyncio.run(twitch.twitch_logout())
    assert asyncio.run(twitch.list_my_vods())["logged_in"] is False


def test_laughs_heard_in_the_audio_become_hints(monkeypatch):
    monkeypatch.setattr(timeline, "detect_loud_spans", lambda _p: [])
    monkeypatch.setattr(reactions, "detect_reactions", lambda _p: [(64.0, 70.0, "laughing")])
    transcript = "[01:00 - 01:03] he walked straight off the roof\n[05:00 - 05:03] anyway back to it"
    summary = timeline.build_clip_signal_summary(Path("x.mp4"), transcript)
    assert "- [01:04 - 01:10] score=4.0: laughing heard in the audio" in summary
    assert "laughing; he walked straight off the roof" in summary
    assert "laughing; anyway" not in summary
    from src.ai import _crowd_signals

    assert (64, 70, "laughing heard in the audio") in _crowd_signals(summary)  # the rerank sees it too


def test_reaction_chunks_merge_into_spans():
    hits = [(10.0, "laughing"), (12.0, "laughing"), (16.0, "laughing"), (30.0, "laughing"), (32.0, "screaming")]
    assert reactions.merge_hits(hits) == [(10.0, 18.0, "laughing"), (30.0, 32.0, "laughing"), (32.0, 34.0, "screaming")]


def test_clip_on_twitch(monkeypatch, tmp_path):
    import asyncio
    from types import SimpleNamespace

    from src import twitch

    assert twitch.vod_clip_window(100.4, 130.0) == (130, 29.6)  # Twitch's vod_offset is the clip's END
    assert twitch.vod_clip_window(100.4, 400.0) == (160, 59.6)  # longer clips: their first minute
    assert twitch.vod_clip_window(0.0, 2.0) == (5, 5.0)  # Twitch's 5 s minimum, never before the VOD starts

    monkeypatch.setattr(twitch, "get_config", lambda: SimpleNamespace(temp_dir=str(tmp_path), twitch_client_id="cid"))
    calls = []

    class Reply:
        def __init__(self, status, body):
            self.status_code, self._body, self.content = status, body, b"x"

        def json(self):
            return self._body

    async def helix(auth, path, method="GET", **params):
        calls.append((method, path, params))
        if path == "videos":
            return Reply(200, {"data": [{"id": "42", "user_id": "99"}]})
        return Reply(202, {"data": [{"id": "FunnyClipAbc", "edit_url": "https://x"}]})

    monkeypatch.setattr(twitch, "_helix", helix)
    run = lambda: asyncio.run(twitch.create_vod_clip("42", 100.4, 130.0, "he really did that"))

    assert run() == {"need_login": True}  # not logged in
    twitch._save_auth({"access_token": "a", "user_id": "7"})
    assert run() == {"need_login": True}  # logged in before LocalClip asked for clip permission
    twitch._save_auth({"access_token": "a", "user_id": "7", "scopes": ["editor:manage:clips"]})
    assert run() == {"id": "FunnyClipAbc", "url": "https://clips.twitch.tv/FunnyClipAbc", "duration": 29.6}
    assert calls[-1] == ("POST", "videos/clips", {"broadcaster_id": "99", "editor_id": "7", "vod_id": "42",
                                                  "vod_offset": 130, "duration": 29.6, "title": "he really did that"})


def test_chat_and_reactions_are_fetched_once_per_vod(tmp_path, monkeypatch):
    """A resume or Find more on a long stream doesn't spend minutes fetching chat and listening again."""
    import io
    import json

    from src import twitch

    monkeypatch.setattr(twitch, "get_config", lambda: type("C", (), {"temp_dir": str(tmp_path)})())
    pages = []

    def urlopen(req, timeout):
        pages.append(req)
        edges = [] if len(pages) % 2 == 0 else [{"node": {"id": "a", "contentOffsetSeconds": 5, "message": {"fragments": [{"text": "LUL"}]}}}]
        return io.BytesIO(json.dumps({"data": {"video": {"comments": {"edges": edges}}}}).encode())

    monkeypatch.setattr(twitch.urllib.request, "urlopen", urlopen)
    assert twitch.fetch_chat("42", 3600) == [(5.0, "LUL")]
    assert twitch.fetch_chat("42", 3600) == [(5.0, "LUL")] and len(pages) == 2
    twitch.fetch_chat("42", 7200)  # the VOD was still live: fetch again
    assert len(pages) == 4

    listens = []
    monkeypatch.setattr(reactions, "_detect_reactions", lambda p: listens.append(p) or [(1.0, 3.0, "laughing")])
    video = tmp_path / "42.mp4"
    assert reactions.detect_reactions(video) == reactions.detect_reactions(video) == [(1.0, 3.0, "laughing")]
    assert len(listens) == 1
