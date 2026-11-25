import asyncio

import pytest

from src import youtube_upload as yt
from src.config import Config


class Reply:
    def __init__(self, status_code, body=None, headers=None):
        self.status_code, self._body, self.headers = status_code, body or {}, headers or {}

    def json(self):
        return self._body


def test_metadata_is_made_safe_for_youtube():
    body = yt.video_metadata("  <b>" + "x" * 150, "desc <3 #fyp", "unlisted")
    assert body["snippet"]["title"] == "b" + "x" * 99
    assert body["snippet"]["description"] == "desc 3 #fyp"
    assert body["status"]["privacyStatus"] == "unlisted"
    with pytest.raises(yt.YouTubeError):
        yt.video_metadata("title", "", "everyone")
    with pytest.raises(yt.YouTubeError):
        yt.video_metadata(" <> ", "", "public")


def test_login_then_upload_then_expired_login(monkeypatch, tmp_path):
    config = Config()
    config.temp_dir = str(tmp_path)
    config.youtube_client_id, config.youtube_client_secret = "id", "secret"
    monkeypatch.setattr(yt, "get_config", lambda: config)
    state = {"approved": False, "revoked": False}

    async def oauth(path, **form):
        if path == "device/code":
            assert form["scope"] == yt.SCOPE
            return Reply(200, {"device_code": "dev", "user_code": "ABCD-EFGH", "verification_url": "https://www.google.com/device"})
        if form["grant_type"] == "refresh_token":
            assert form["refresh_token"] == "r1"
            return Reply(400, {"error": "invalid_grant"}) if state["revoked"] else Reply(200, {"access_token": "a2"})
        if not state["approved"]:
            return Reply(428, {"error": "authorization_pending"})
        return Reply(200, {"access_token": "a1", "refresh_token": "r1"})

    async def channel_name(token):
        return "Marky"

    monkeypatch.setattr(yt, "_oauth", oauth)
    monkeypatch.setattr(yt, "_channel_name", channel_name)

    assert yt.status() == {"configured": True, "logged_in": False, "name": None}
    assert asyncio.run(yt.start_login())["user_code"] == "ABCD-EFGH"
    assert asyncio.run(yt.poll_login()) is False
    state["approved"] = True
    assert asyncio.run(yt.poll_login()) is True
    assert yt.status() == {"configured": True, "logged_in": True, "name": "Marky"}

    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"video")
    seen = {}

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, params, headers, json):
            seen.update(auth=headers["Authorization"], body=json, size=headers["X-Upload-Content-Length"])
            return Reply(200, headers={"location": "https://upload.example/session"})

    def send_file(session_url, path):
        seen.update(session=session_url, sent=path.read_bytes())
        return Reply(200, {"id": "vid123"})

    monkeypatch.setattr(yt.httpx, "AsyncClient", Client)
    monkeypatch.setattr(yt, "_send_file", send_file)

    posted = asyncio.run(yt.upload(clip, "My clip", "#fyp", "public"))
    assert posted == {"id": "vid123", "url": "https://youtube.com/shorts/vid123"}
    assert seen["auth"] == "Bearer a2" and seen["size"] == "5" and seen["sent"] == b"video"
    assert seen["session"] == "https://upload.example/session"
    assert seen["body"]["snippet"]["title"] == "My clip"

    state["revoked"] = True
    with pytest.raises(yt.YouTubeError, match="Log in to YouTube again"):
        asyncio.run(yt.upload(clip, "My clip", "", "public"))
    assert yt.status()["logged_in"] is False
