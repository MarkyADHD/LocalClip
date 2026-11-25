"""AI-written post text for a finished clip: one caption with hashtags per site, from the clip's transcript."""

import re

from pydantic import BaseModel, Field

SITES = ("youtube", "tiktok", "instagram")
# YouTube's title limit; TikTok and Instagram captions hold 2200, the prompt keeps them far shorter.
LIMITS = {"youtube": 100, "tiktok": 2200, "instagram": 2200}

SYSTEM_PROMPT = """You write the post text for a short vertical clip cut from a livestream (gaming or just chatting).
You get the clip's on-screen title, its transcript and suggested hashtags. Write one text per site, hashtags included:

- "youtube": the YouTube Shorts title. At most 90 characters with its hashtags. A curiosity hook, then 1-2 hashtags, the last one #shorts.
- "tiktok": one short punchy line in a casual voice, lowercase is fine, then 3-5 hashtags.
- "instagram": 1-2 sentences ending with a question or a call to comment, then a blank line, then 5-8 hashtags.

Rules:
- Only say what the transcript supports. Never invent names, scores, games or events.
- Tease the moment, do not spoil the payoff. Do not repeat the on-screen title word for word.
- Hashtags: the game or topic first, then what happens. No spaces inside a tag. No filler (#fyp, #viral, #foryou).
- Write in the transcript's language. At most one emoji per text. No quotes around the text.
- Return JSON only, with the keys "youtube", "tiktok" and "instagram"."""


class PostCaptions(BaseModel):
    youtube: str = Field(description="YouTube Shorts title with 1-2 hashtags, at most 90 characters")
    tiktok: str = Field(description="TikTok caption with 3-5 hashtags")
    instagram: str = Field(description="Instagram Reels caption with 5-8 hashtags")


def build_prompt(clip: dict, source_title: str | None = None) -> str:
    tags = clip.get("hashtags") or []
    if isinstance(tags, str):
        tags = tags.split()
    lines = [
        f"Stream title: {source_title}" if source_title else "",
        f"On-screen title: {clip['hook_title']}" if clip.get("hook_title") else "",
        f"Suggested hashtags: {' '.join('#' + tag for tag in tags)}" if tags else "",
        # ponytail: clips are under 60 s (10 minutes after "+30s"), so 6000 characters is the whole transcript.
        f"Transcript:\n{(clip.get('text') or '').strip()[:6000]}",
    ]
    return "\n".join(line for line in lines if line)


def clean(site: str, text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text.strip().strip('"')).strip()
    limit = LIMITS[site]
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0]  # never cut a word or hashtag in half
    return text


async def write_captions(clip: dict, source_title: str | None = None) -> dict[str, str]:
    from .ai import build_agent

    if not (clip.get("text") or "").strip():
        raise ValueError("This clip has no transcript to write from")
    result = await build_agent(PostCaptions, SYSTEM_PROMPT).run(build_prompt(clip, source_title))
    return {site: clean(site, getattr(result.output, site)) for site in SITES}
