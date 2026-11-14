"""The video editor's assistant: reads the timeline's transcript and proposes edits.

Nothing here changes a project. The model's answer becomes a list of proposed edits that the
editor shows for approval and applies with its own actions (lib/project/document.ts). The MCP
server (mcp_server.py) leaves proposals the same way.
"""

import time
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from .editor_document import atomic_json
from .project_document import ProjectDocument, read_json

MAX_PROPOSALS = 10

SYSTEM_PROMPT = """You are the editing assistant inside LocalClip's video editor. The user is a streamer or
YouTuber editing a long video. You get the video's transcript as lines of
[start-end] text, with times in seconds on the timeline, and the user's request.

Answer with a short, plain reply and a list of proposed edits. The user reviews every edit before it
is applied, so propose what was asked for and nothing else. If the request is a question, answer it
in the reply and propose no edits.

Edit kinds:
- cut: remove the timeline between start and end. Use the times from the transcript; cut whole
  sentences or phrases, never the middle of a word. `note` says why in a few words.
- chapter: a chapter that begins at `start`, with its title in `text`. The first chapter starts at 0.
  Chapters are at least 10 seconds apart.
- title: a video title in `text` (under 70 characters, no clickbait the video does not deliver).
- description: a video description in `text`.
- text: on-screen text shown from `start` to `end`, with the words in `text` (a few words only).

When asked to tighten or shorten the video, cut rambling, repeats, false starts, dead air and
off-topic stretches, and keep the story and the best moments. Never invent anything that is not in
the transcript. Times must lie inside the transcript."""


class Edit(BaseModel):
    kind: Literal["cut", "chapter", "title", "description", "text"]
    start: float = 0
    end: float = 0
    text: str = ""
    note: str = ""


class Proposal(BaseModel):
    reply: str = Field(description="A short answer for the user, in plain language")
    edits: list[Edit] = Field(default_factory=list)


def transcript_lines(words: list[dict]) -> list[dict]:
    """Timeline words grouped into sentence-like lines: [{start, end, text}]."""
    lines: list[list[dict]] = []
    for word in words:
        line = lines[-1] if lines else None
        if (
            line is None
            or word["start"] - line[-1]["end"] > 0.7
            or len(line) >= 18
            or line[-1]["text"].rstrip()[-1:] in ".?!"
        ):
            lines.append([word])
        else:
            line.append(word)
    return [
        {"start": line[0]["start"], "end": line[-1]["end"], "text": " ".join(w["text"].strip() for w in line)}
        for line in lines
    ]


def transcript_text(words: list[dict]) -> str:
    return "\n".join(f"[{line['start']:.1f}-{line['end']:.1f}] {line['text']}" for line in transcript_lines(words))


def _snap(words: list[dict], start: float, end: float) -> tuple[float, float]:
    """Moves a cut onto word edges, taking up to 0.15 s of the pause either side (like wordRange)."""
    inside = [i for i, w in enumerate(words) if start <= (w["start"] + w["end"]) / 2 < end]
    if not inside:
        return start, end
    first, last = inside[0], inside[-1]
    before = words[first - 1]["end"] if first else 0.0
    after = words[last + 1]["start"] if last + 1 < len(words) else words[last]["end"] + 0.3
    pad = lambda gap: min(0.15, max(0.0, gap / 2))  # noqa: E731
    return (
        words[first]["start"] - pad(words[first]["start"] - before),
        words[last]["end"] + pad(after - words[last]["end"]),
    )


def source_edits(document: ProjectDocument, words: list[dict], edits: list[Edit]) -> list[dict]:
    """Edits in the shape the editor applies. Cuts become ranges of the source files, so they still
    land on the right words if the timeline changed while the proposal waited."""
    main = next((t.id for t in document.tracks if t.kind == "video"), None)
    clips = sorted((c for c in document.clips if c.track == main and c.asset), key=lambda c: c.start)
    total = document.duration
    result: list[dict] = []
    for edit in edits:
        start = min(max(0.0, edit.start), total)
        end = min(max(start, edit.end), total)
        text = edit.text.strip()
        if edit.kind == "cut":
            start, end = _snap(words, start, end)
            spoken = " ".join(w["text"].strip() for w in words if start <= (w["start"] + w["end"]) / 2 < end)
            ranges = [
                {
                    "asset": clip.asset,
                    "start": round(clip.offset + (max(start, clip.start) - clip.start) * clip.speed, 3),
                    "end": round(clip.offset + (min(end, clip.start + clip.duration) - clip.start) * clip.speed, 3),
                }
                for clip in clips
                if min(end, clip.start + clip.duration) - max(start, clip.start) >= 0.05
            ]
            if ranges:
                result.append(
                    {
                        "kind": "cut",
                        "ranges": ranges,
                        "time": round(start, 3),
                        "seconds": round(end - start, 3),
                        "text": spoken,
                        "note": edit.note.strip()[:200],
                    }
                )
        elif edit.kind == "chapter" and text:
            result.append({"kind": "chapter", "time": round(start, 3), "text": text[:100]})
        elif edit.kind == "text" and text and end - start >= 0.2:
            result.append({"kind": "text", "time": round(start, 3), "seconds": round(end - start, 3), "text": text[:200]})
        elif edit.kind in ("title", "description") and text:
            result.append({"kind": edit.kind, "text": text[:5000]})
    return result


def build_prompt(document: ProjectDocument, words: list[dict], message: str, history: list[dict]) -> str:
    parts = [f"The video is {document.duration:.0f} seconds long."]
    if document.title:
        parts.append(f"Current title: {document.title}")
    if document.chapters:
        parts.append("Current chapters: " + "; ".join(f"{c.time:.0f}s {c.title}" for c in document.chapters))
    parts.append("Transcript:\n" + (transcript_text(words) or "(no speech has been transcribed yet)"))
    for turn in history[-6:]:
        who = "User" if turn.get("role") == "user" else "You"
        parts.append(f"{who} said earlier: {str(turn.get('text', ''))[:1000]}")
    parts.append(f"Request: {message}")
    return "\n\n".join(parts)


def assistant_agent():
    """The configured model (Settings > AI model), answering with a Proposal."""
    from .ai import _build_transcript_model, _get_missing_llm_key_error, _output_type, _split_llm_name
    from .claude_code import ClaudeCodeAgent
    from .config import get_config

    config = get_config()
    provider, name = _split_llm_name(config.llm)
    error = _get_missing_llm_key_error(config.llm, config)
    if error:
        raise RuntimeError(error)
    if provider == "claude-code":
        return ClaudeCodeAgent(name, Proposal, SYSTEM_PROMPT)
    from pydantic_ai import Agent

    return Agent(
        model=_build_transcript_model(config),
        output_type=_output_type(provider, Proposal),
        system_prompt=SYSTEM_PROMPT,
        output_retries=2,
    )


async def ask(document: ProjectDocument, words: list[dict], message: str, history: list[dict]) -> dict:
    # ponytail: the whole transcript goes in one prompt (about 15k tokens an hour); window it like
    # ai.py does if small local models need to handle multi-hour videos.
    result = await assistant_agent().run(build_prompt(document, words, message, history))
    proposal: Proposal = result.output
    return {"reply": proposal.reply.strip(), "edits": source_edits(document, words, proposal.edits)}


# ---------------------------------------------------------------- proposals left for the editor


def read_proposals(directory: Path) -> list[dict]:
    return read_json(directory / "proposals.json") or []


def add_proposal(directory: Path, reply: str, edits: list[dict], source: str) -> dict:
    proposal = {"id": uuid.uuid4().hex[:12], "reply": reply, "edits": edits, "source": source, "created": time.time()}
    atomic_json(directory / "proposals.json", [*read_proposals(directory), proposal][-MAX_PROPOSALS:])
    return proposal


def remove_proposal(directory: Path, proposal_id: str) -> None:
    atomic_json(directory / "proposals.json", [p for p in read_proposals(directory) if p["id"] != proposal_id])
