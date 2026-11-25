"""Post a finished clip to the user's own YouTube channel (vertical clips up to 3 minutes become Shorts).

Login is Google's device flow, like "Log in with Twitch": the user types a code at google.com/device.
It needs an OAuth client of type "TVs and Limited Input devices" (YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET);
Google does not treat that kind of client's secret as confidential.
"""

import json
import logging
import re
from pathlib import Path
from typing import Optional

import httpx

from .config import get_config

logger = logging.getLogger(__name__)

GOOGLE_OAUTH = "https://oauth2.googleapis.com"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
# The only scope the device flow allows that can upload (youtube.upload is not on Google's list).
SCOPE = "https://www.googleapis.com/auth/youtube"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
PRIVACY = ("public", "unlisted", "private")
_pending_login: dict = {}  # the device code being approved; one login at a time is enough for a one-user app


class YouTubeError(Exception):
    pass


def _auth_file() -> Path:
    return Path(get_config().temp_dir) / "youtube_login.json"


def configured() -> bool:
    config = get_config()
    return bool(config.youtube_client_id and config.youtube_client_secret)


def _client() -> dict:
    if not configured():
        raise YouTubeError("YouTube posting is not set up: YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET are missing")
    config = get_config()
    return {"client_id": config.youtube_client_id, "client_secret": config.youtube_client_secret}


def _load_auth() -> Optional[dict]:
    try:
        return json.loads(_auth_file().read_text())
    except (OSError, ValueError):
        return None


def _save_auth(auth: dict) -> None:
    path = _auth_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(auth))


def logout() -> None:
    _auth_file().unlink(missing_ok=True)


async def _oauth(path: str, **form) -> httpx.Response:
    async with httpx.AsyncClient(timeout=15) as client:
        return await client.post(f"{GOOGLE_OAUTH}/{path}", data={**_client(), **form})


def _error(response: httpx.Response) -> str:
    """Google's reason for a failed call, from either of its two error shapes."""
    try:
        error = response.json().get("error")
    except ValueError:
        return f"HTTP {response.status_code}"
    if isinstance(error, dict):
        return str(error.get("message") or response.status_code)
    return str(error or response.status_code)


def status() -> dict:
    auth = _load_auth()
    return {"configured": configured(), "logged_in": bool(auth), "name": (auth or {}).get("name")}


async def start_login() -> dict:
    """Ask Google for a device code; the user approves it at the returned link."""
    response = await _oauth("device/code", scope=SCOPE)
    if response.status_code != 200:
        raise YouTubeError(f"Google refused the login request: {_error(response)}")
    data = response.json()
    _pending_login.clear()
    _pending_login.update(device_code=data["device_code"])
    return {
        "user_code": data["user_code"],
        "verification_uri": data["verification_url"],
        "interval": data.get("interval", 5),
    }


async def _channel_name(access_token: str) -> Optional[str]:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            "https://www.googleapis.com/youtube/v3/channels",
            params={"part": "snippet", "mine": "true"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
    items = response.json().get("items") if response.status_code == 200 else None
    return items[0]["snippet"]["title"] if items else None


async def poll_login() -> bool:
    """True once the user has approved the code (tokens saved), False while still waiting."""
    device_code = _pending_login.get("device_code")
    if not device_code:
        raise YouTubeError("No YouTube login in progress")
    response = await _oauth("token", device_code=device_code, grant_type=DEVICE_GRANT)
    if response.status_code != 200:
        reason = _error(response)
        if reason in ("authorization_pending", "slow_down"):
            return False
        _pending_login.clear()
        raise YouTubeError("You declined the YouTube login" if reason == "access_denied" else f"YouTube login failed: {reason}")
    tokens = response.json()
    _pending_login.clear()
    name = await _channel_name(tokens["access_token"])
    if not name:
        raise YouTubeError("That Google account has no YouTube channel. Create one at youtube.com, then log in again.")
    _save_auth({"refresh_token": tokens["refresh_token"], "name": name})
    return True


async def _access_token() -> str:
    auth = _load_auth()
    if not auth:
        raise YouTubeError("Log in to YouTube first")
    # ponytail: a fresh access token per upload (one extra call) instead of tracking the 1 hour expiry.
    response = await _oauth("token", grant_type="refresh_token", refresh_token=auth["refresh_token"])
    if response.status_code != 200:
        if _error(response) == "invalid_grant":  # revoked, or expired (7 days while the Google app is in Testing)
            logout()
            raise YouTubeError("Your YouTube login expired. Log in to YouTube again.")
        raise YouTubeError(f"Could not reach your YouTube login: {_error(response)}")
    return response.json()["access_token"]


def video_metadata(title: str, description: str, privacy: str) -> dict:
    """The videos.insert body. YouTube rejects < and > and titles over 100 characters."""
    clean = lambda text: re.sub(r"[<>]", "", text or "").strip()  # noqa: E731
    if privacy not in PRIVACY:
        raise YouTubeError(f"Visibility must be one of: {', '.join(PRIVACY)}")
    title = clean(title)[:100]
    if not title:
        raise YouTubeError("Give the video a title")
    return {
        "snippet": {"title": title, "description": clean(description)[:5000], "categoryId": "20"},  # 20 = Gaming
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
    }


def _send_file(session_url: str, path: Path) -> httpx.Response:
    with path.open("rb") as handle:
        return httpx.put(
            session_url,
            content=handle,
            headers={"Content-Type": "video/mp4", "Content-Length": str(path.stat().st_size)},
            timeout=httpx.Timeout(30, write=600, read=600),
        )


async def upload(path: Path, title: str, description: str, privacy: str) -> dict:
    """Upload the file with the user's login. Returns the new video's id and link."""
    metadata = video_metadata(title, description, privacy)
    if not path.exists():
        raise YouTubeError("The clip file is missing")
    token = await _access_token()
    async with httpx.AsyncClient(timeout=30) as client:
        session = await client.post(
            UPLOAD_URL,
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers={"Authorization": f"Bearer {token}", "X-Upload-Content-Type": "video/mp4",
                     "X-Upload-Content-Length": str(path.stat().st_size)},
            json=metadata,
        )
    if session.status_code != 200 or "location" not in session.headers:
        raise YouTubeError(f"YouTube refused the upload: {_error(session)}")
    from .utils.async_helpers import run_in_thread

    # ponytail: one PUT, no resume after a dropped connection; clips are small. Chunk it if uploads start failing.
    sent = await run_in_thread(_send_file, session.headers["location"], path)
    if sent.status_code not in (200, 201):
        raise YouTubeError(f"YouTube did not accept the video: {_error(sent)}")
    video_id = sent.json()["id"]
    logger.info("Posted %s to YouTube as %s (%s)", path.name, video_id, privacy)
    return {"id": video_id, "url": f"https://youtube.com/shorts/{video_id}"}
