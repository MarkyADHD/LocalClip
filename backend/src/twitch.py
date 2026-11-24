"""Twitch and Kick VODs and clips: download with yt-dlp, and Twitch chat replay as a clip signal."""

import json
import logging
import re
import urllib.request
from pathlib import Path
from typing import List, Optional, Tuple

import httpx

from .config import get_config
from .media.timeline import spike_spans

logger = logging.getLogger(__name__)

TWITCH_VOD = re.compile(r"^https?://(?:www\.|m\.)?twitch\.tv/(?:[^/]+/)?videos?/(\d+)", re.I)
CHAT_EMOTES = re.compile(r"\b(LUL|KEKW|OMEGALUL|LMAO+|LOL+|Pog\w*|POGGERS|W+|L+|clip|monkaS|ICANT|Clap|EZ)\b|\?{2,}", re.I)


# (site, pattern capturing the id). The id names the cached file, so every pattern keeps it to [\w-].
STREAM_SOURCES = (
    ("twitch", TWITCH_VOD),
    ("twitch", re.compile(
        r"^https?://(?:clips\.twitch\.tv/(?:embed\?(?:[^#]*&)?clip=)?|(?:(?:www|go|m)\.)?twitch\.tv/(?:[^/]+/)?clip/)([\w-]+)",
        re.I,
    )),
    ("kick", re.compile(r"^https?://(?:www\.)?kick\.com/[\w-]+/videos/([\da-f]{8}-(?:[\da-f]{4}-){3}[\da-f]{12})", re.I)),
    ("kick", re.compile(r"^https?://(?:www\.)?kick\.com/[\w-]+(?:/clips/|/?\?(?:[^#]+&)?clip=)(clip_[\w-]+)", re.I)),
)


def get_twitch_video_id(url: str) -> Optional[str]:
    """Numeric id of a Twitch VOD (the only kind with a chat replay)."""
    match = TWITCH_VOD.match((url or "").strip())
    return match.group(1) if match else None


def get_stream_source(url: str) -> Optional[Tuple[str, str]]:
    """(site, id) for a Twitch or Kick VOD or clip link, else None."""
    for site, pattern in STREAM_SOURCES:
        match = pattern.match((url or "").strip())
        if match:
            return site, match.group(1)
    return None


def _ydl_opts(**extra):
    return {"quiet": True, "no_warnings": True, "noprogress": True, **extra}


def get_twitch_title(url: str) -> str:
    import yt_dlp

    try:
        with yt_dlp.YoutubeDL(_ydl_opts()) as ydl:
            return ydl.extract_info(url, download=False).get("title") or "Stream VOD"
    except Exception as exc:
        logger.warning("Stream title lookup failed: %s", exc)
        return "Stream VOD"


def download_stream_video(url: str) -> Path:
    """Download a Twitch/Kick VOD or clip at up to 1080p. Kept until its generation or the full video is deleted
    (or SOURCE_KEEP_DAYS pass), so a retry or "+30s" doesn't re-download hours of video."""
    import yt_dlp

    source = get_stream_source(url)
    if not source:
        raise ValueError("Not a Twitch or Kick VOD or clip link")
    site, video_id = source
    out_dir = Path(get_config().temp_dir) / site
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{video_id}.mp4"
    if target.exists() and target.stat().st_size > 0:
        return target
    with yt_dlp.YoutubeDL(_ydl_opts(
        format="b[height<=1080]/bv*[height<=1080]+ba/b",
        outtmpl=str(out_dir / f"{video_id}.%(ext)s"),
        merge_output_format="mp4",
        # Twitch serves fMP4 HLS that yt-dlp's native HLS downloader rejects; ffmpeg handles it.
        external_downloader={"m3u8": "ffmpeg"},
    )) as ydl:
        ydl.download([url])
    if not target.exists():
        raise RuntimeError("Download finished but no MP4 was written")
    return target


def fetch_chat(video_id: str, duration: float) -> List[Tuple[float, str]]:
    """Chat replay through Twitch's public web GQL (what twitch.tv uses; no login).
    Pages by time offset because cursor paging needs an integrity token."""
    out, seen, at = [], set(), 0.0
    while at <= duration:
        query = (
            f'query{{video(id:"{video_id}"){{comments(contentOffsetSeconds:{int(at)})'
            "{edges{node{id contentOffsetSeconds message{fragments{text}}}}}}}"
        )
        req = urllib.request.Request(
            "https://gql.twitch.tv/gql",
            data=json.dumps({"query": query}).encode(),
            headers={"Client-ID": "kimne78kx3ncx6brgo4mv6wki5h1ko", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read())
        if data.get("errors"):
            raise RuntimeError("Twitch chat: " + "; ".join(str(e.get("message")) for e in data["errors"]))
        edges = ((((data.get("data") or {}).get("video") or {}).get("comments")) or {}).get("edges") or []
        if not edges:
            break
        last = at
        for edge in edges:
            node = edge.get("node") or {}
            offset = float(node.get("contentOffsetSeconds") or 0)
            last = max(last, offset)
            if node.get("id") in seen:
                continue
            seen.add(node.get("id"))
            text = "".join(f.get("text", "") for f in (node.get("message") or {}).get("fragments") or [])
            out.append((offset, text[:200]))
        at = last if last > at else at + 1
    return out


def chat_spikes(messages, duration: float, lag: float = 8.0, window: int = 300, z: float = 2.5):
    """Seconds where chat exploded: messages + emote bursts per second, smoothed, compared with a
    rolling 5-min median. Shifted back ~8 s because chat reacts after the moment."""
    n = int(duration) + 1
    rate = [0.0] * n
    for t, text in messages:
        i = int(t - lag)
        if 0 <= i < n:
            rate[i] += 1 + 2 * len(CHAT_EMOTES.findall(text))
    smooth = [sum(rate[max(0, i - 2):i + 3]) / 5 for i in range(n)]
    return spike_spans(smooth, window=window, z=z, floor=0.5, min_value=1)


def timestamp_label(seconds: float) -> str:
    """Same format as transcript timestamps (MM:SS, or HH:MM:SS past an hour)."""
    s = max(0, int(seconds))
    return f"{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


def chat_signal_lines(url: str, duration: float) -> List[str]:
    """Signal lines for the LLM prompt. Any failure (Twitch changed GQL, chat disabled) just means no chat hints."""
    video_id = get_twitch_video_id(url)
    if not video_id or not duration:
        return []
    try:
        messages = fetch_chat(video_id, duration)
    except Exception as exc:
        logger.warning("Twitch chat fetch failed: %s", exc)
        return []
    spans = chat_spikes(messages, duration)
    logger.info("Twitch chat: %s messages, %s spikes", len(messages), len(spans))
    return [
        f"- [{timestamp_label(a)} - {timestamp_label(b)}] score=4.0: Twitch chat exploded here (viewers reacted to this moment)"
        for a, b in spans
    ]


# --- "Log in with Twitch": device code login (no client secret) and the user's own videos ---

TWITCH_ID = "https://id.twitch.tv/oauth2"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
_pending_login: dict = {}  # the device code being approved; one login at a time is enough for a one-user app


class TwitchLoginError(Exception):
    pass


def _auth_file() -> Path:
    return Path(get_config().temp_dir) / "twitch_login.json"


def _client_id() -> str:
    client_id = get_config().twitch_client_id
    if not client_id:
        raise TwitchLoginError("Twitch login is not set up: TWITCH_CLIENT_ID is missing")
    return client_id


def _load_auth() -> Optional[dict]:
    try:
        return json.loads(_auth_file().read_text())
    except (OSError, ValueError):
        return None


def _save_auth(auth: dict) -> None:
    path = _auth_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(auth))


async def _oauth(path: str, **form) -> httpx.Response:
    async with httpx.AsyncClient(timeout=15) as client:
        return await client.post(f"{TWITCH_ID}/{path}", data={"client_id": _client_id(), **form})


async def _helix(auth: dict, path: str, **params) -> httpx.Response:
    async with httpx.AsyncClient(timeout=15) as client:
        return await client.get(
            f"https://api.twitch.tv/helix/{path}",
            params=params,
            headers={"Client-Id": _client_id(), "Authorization": f"Bearer {auth['access_token']}"},
        )


async def start_twitch_login() -> dict:
    """Ask Twitch for a device code; the user approves it at the returned link."""
    response = await _oauth("device", scopes="")  # public videos need no scopes
    if response.status_code != 200:
        raise TwitchLoginError(f"Twitch refused the login request: {response.text[:200]}")
    data = response.json()
    _pending_login.clear()
    _pending_login.update(device_code=data["device_code"])
    return {
        "user_code": data["user_code"],
        "verification_uri": data["verification_uri"],
        "interval": data.get("interval", 5),
        "expires_in": data.get("expires_in", 1800),
    }


async def poll_twitch_login() -> bool:
    """True once the user has approved the code (tokens saved), False while still waiting."""
    device_code = _pending_login.get("device_code")
    if not device_code:
        raise TwitchLoginError("No Twitch login in progress")
    response = await _oauth("token", scopes="", device_code=device_code, grant_type=DEVICE_GRANT)
    if response.status_code != 200:
        message = str(response.json().get("message", "")) if response.content else ""
        if "pending" in message or "slow_down" in message:
            return False
        _pending_login.clear()
        raise TwitchLoginError(f"Twitch login failed: {message or response.status_code}")
    tokens = response.json()
    auth = {"access_token": tokens["access_token"], "refresh_token": tokens.get("refresh_token")}
    users = (await _helix(auth, "users")).json().get("data") or []
    if not users:
        raise TwitchLoginError("Twitch login worked but the account could not be read")
    auth.update(user_id=users[0]["id"], name=users[0].get("display_name") or users[0]["login"])
    _save_auth(auth)
    _pending_login.clear()
    return True


async def _refresh(auth: dict) -> Optional[dict]:
    if not auth.get("refresh_token"):
        return None
    response = await _oauth("token", grant_type="refresh_token", refresh_token=auth["refresh_token"])
    if response.status_code != 200:
        return None
    tokens = response.json()
    # Public-client refresh tokens are single use: keep the new one.
    auth.update(access_token=tokens["access_token"], refresh_token=tokens.get("refresh_token"))
    _save_auth(auth)
    return auth


def vod_summary(video: dict) -> dict:
    return {
        "id": video["id"],
        "title": video.get("title") or "Untitled stream",
        "url": video.get("url") or f"https://www.twitch.tv/videos/{video['id']}",
        # Empty while a stream is still live or being processed.
        "thumbnail": (video.get("thumbnail_url") or "").replace("%{width}", "320").replace("%{height}", "180"),
        "duration": video.get("duration", ""),
        "created_at": video.get("created_at", ""),
        "type": video.get("type", "archive"),
    }


async def list_my_vods(after: Optional[str] = None) -> dict:
    """The logged-in user's past broadcasts, highlights and uploads, newest first."""
    auth = _load_auth()
    if not auth:
        return {"configured": bool(get_config().twitch_client_id), "logged_in": False}
    params = {"user_id": auth["user_id"], "first": 50, **({"after": after} if after else {})}
    response = await _helix(auth, "videos", **params)
    if response.status_code == 401:
        auth = await _refresh(auth)
        if not auth:  # revoked, or unused for 30 days
            twitch_logout_local()
            return {"configured": True, "logged_in": False}
        response = await _helix(auth, "videos", **params)
    if response.status_code != 200:
        raise TwitchLoginError(f"Twitch did not return your videos ({response.status_code})")
    body = response.json()
    return {
        "configured": True,
        "logged_in": True,
        "name": auth.get("name"),
        "vods": [vod_summary(video) for video in body.get("data", [])],
        "cursor": (body.get("pagination") or {}).get("cursor"),
    }


def twitch_logout_local() -> None:
    _auth_file().unlink(missing_ok=True)


async def twitch_logout() -> None:
    auth = _load_auth()
    twitch_logout_local()
    if auth:
        try:
            await _oauth("revoke", token=auth["access_token"])
        except (httpx.HTTPError, TwitchLoginError) as exc:
            logger.warning("Twitch token revoke failed: %s", exc)
