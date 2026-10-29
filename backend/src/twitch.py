"""Twitch VODs: download with yt-dlp, and chat replay as a clip signal (ported from LocalClip)."""

import json
import logging
import re
import urllib.request
from pathlib import Path
from typing import List, Optional, Tuple

from .config import get_config
from .media.timeline import spike_spans

logger = logging.getLogger(__name__)

TWITCH_VOD = re.compile(r"^https?://(?:www\.|m\.)?twitch\.tv/(?:[^/]+/)?videos?/(\d+)", re.I)
CHAT_EMOTES = re.compile(r"\b(LUL|KEKW|OMEGALUL|LMAO+|LOL+|Pog\w*|POGGERS|W+|L+|clip|monkaS|ICANT|Clap|EZ)\b|\?{2,}", re.I)


def get_twitch_video_id(url: str) -> Optional[str]:
    match = TWITCH_VOD.match((url or "").strip())
    return match.group(1) if match else None


def _ydl_opts(**extra):
    return {"quiet": True, "no_warnings": True, "noprogress": True, **extra}


def get_twitch_title(url: str) -> str:
    import yt_dlp

    try:
        with yt_dlp.YoutubeDL(_ydl_opts()) as ydl:
            return ydl.extract_info(url, download=False).get("title") or "Twitch VOD"
    except Exception as exc:
        logger.warning("Twitch title lookup failed: %s", exc)
        return "Twitch VOD"


def download_twitch_vod(url: str) -> Path:
    """Download a VOD at up to 1080p. Kept between runs so a retry doesn't re-download hours of video."""
    import yt_dlp

    video_id = get_twitch_video_id(url)
    if not video_id:
        raise ValueError("Not a Twitch VOD link (expected twitch.tv/videos/<id>)")
    out_dir = Path(get_config().temp_dir) / "twitch"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{video_id}.mp4"
    if target.exists() and target.stat().st_size > 0:
        return target
    # ponytail: VODs are cached forever in uploads/twitch; delete by hand or add cleanup if disk fills.
    with yt_dlp.YoutubeDL(_ydl_opts(
        format="b[height<=1080]/bv*[height<=1080]+ba/b",
        outtmpl=str(out_dir / f"{video_id}.%(ext)s"),
        merge_output_format="mp4",
        # Twitch serves fMP4 HLS that yt-dlp's native HLS downloader rejects; ffmpeg handles it.
        external_downloader={"m3u8": "ffmpeg"},
    )) as ydl:
        ydl.download([url])
    if not target.exists():
        raise RuntimeError("Twitch download finished but no MP4 was written")
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
