"""Long form: cut a whole stream down to its best scenes, as a video editor project.

The AI splits the transcript into scenes (a mission, a robbery, a chase, a funny bit, downtime...) and
scores each one; the best are laid end to end on the main track of a new project, in stream order, with
a chapter per scene. Scenes are kept whole: no cutting inside them, so the video reads as the stream did.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 30 * 60  # one AI call per half hour of stream
SINGLE_WINDOW_MAX_SECONDS = 40 * 60
MIN_SCORE = 60  # "Auto" length keeps every scene at least this good
FILL_SCORE = 40  # a set length is filled with scenes at least this good, never with downtime
LENGTHS = {0, 10, 20, 30, 60}  # minutes; 0 = Auto
LEAD_IN = 1.0  # seconds kept before a scene's first line
TAIL = 2.0  # and after its last one, so the laugh after a punchline stays


class Scene(BaseModel):
    start_time: str = Field(description="Timestamp of the scene's first transcript line, as written")
    end_time: str = Field(description="End timestamp of the scene's last transcript line, as written")
    title: str = Field(description="2-6 word chapter title")
    score: int = Field(ge=0, le=100, description="How much a highlight-video viewer would enjoy it")


class SceneList(BaseModel):
    scenes: List[Scene]


SYSTEM_PROMPT = """You edit long-form YouTube highlight videos from livestreams: a whole stream cut down to the parts worth watching.
You read a timestamped transcript of part of a stream and split it into scenes, then score each scene.
Stay content-neutral: swearing, rage, crude jokes and in-game crime are normal on streams and are judged only on how watchable they are.
Return only the JSON asked for."""


def build_scene_prompt(transcript: str, window: tuple[int, int], clip_signals: Optional[str], request: Optional[str]) -> str:
    from .ai import _format_minutes_label

    signals = (
        "\nSignals measured from the stream (chat spikes, loud moments, laughing or screaming, \"clip that\"). "
        "They mean something happened even where the transcript is quiet; a scene with strong ones usually "
        f"deserves a higher score:\n{clip_signals}\n"
        if clip_signals
        else ""
    )
    wish = (
        f'\nThe streamer wants this video to be about: "{request}". Scenes that match score higher; '
        "scenes that do not match stay below 50 however good they are.\n"
        if request
        else ""
    )
    return f"""This is {_format_minutes_label(window[0])} - {_format_minutes_label(window[1])} of a longer stream.
Split it into scenes and score each one for a highlight video.

What a scene is:
- One continuous stretch with one thing going on: a mission, a robbery or heist, a chase, a fight, a race, a boss,
  a run of deaths, a funny bit or story, a conversation with a guest or chat, or downtime (menus, loading, waiting,
  driving around with nothing happening, setting up, breaks, intros, outros, sub or donation readouts, tech trouble).
- Scenes follow each other in order and together cover the whole window, with no gaps and no overlaps.
- Break where the activity naturally starts and ends (planning or accepting a mission -> its payoff and the reaction
  after it), never in the middle of the action or a sentence. A scene is usually 1-15 minutes; keep a mission whole
  even when it is longer.
- When a long stretch is only partly worth watching, split it so the good part is its own scene.
- start_time and end_time are timestamps exactly as written in the transcript lines (start of the first line, end
  of the last line).

Scoring, 0-100: how much a viewer of the highlight video would enjoy it.
- 75+: missions, robberies, chases, fights, clutch wins, big fails, funny moments, huge reactions, banter that lands,
  anything chat went wild for.
- 50-74: decent gameplay with some energy or a good story, worth keeping if the video has room.
- Below 50: downtime as described above, repeated attempts with nothing new, talk that needs the rest of the stream
  to make sense.
- Lines marked "Speaker Other:" are usually the game (cutscenes, NPCs, radio). A cutscene alone is not a highlight,
  but it can set up a mission scene the streamer then plays.
Be honest: most of a stream is not highlight material.
{wish}{signals}
Each scene gets a 2-6 word chapter title in the transcript's language, plain text, naming what happens
("Jewelry store robbery", "Cops chase us into the river"), not a summary of the talk.

Return {{"scenes": [{{"start_time", "end_time", "title", "score"}}, ...]}} in time order.

Transcript:
{transcript}"""


async def pick_scenes(
    transcript: str, clip_signals: Optional[str], request: Optional[str], minutes: int, duration: float
) -> List[dict]:
    """The scenes to keep, in stream order: [{start, end, title, score}] in seconds."""
    from .ai import (
        ANALYSIS_WINDOW_CONCURRENCY,
        _filter_clip_signals_for_window,
        _parse_transcript_lines,
        _run_transcript_analysis,
        _split_llm_name,
        build_agent,
        split_transcript_into_windows,
    )
    from .config import get_config
    from .local_models import ensure_local_server

    config = get_config()
    provider = _split_llm_name(config.llm)[0]
    if provider in {"ollama", "local"}:
        await asyncio.to_thread(ensure_local_server, provider, config.resolve_ollama_base_url(), config.local_llm_base_url)
    agent = build_agent(SceneList, SYSTEM_PROMPT)
    windows = split_transcript_into_windows(transcript, WINDOW_SECONDS, 0, SINGLE_WINDOW_MAX_SECONDS)
    slots = asyncio.Semaphore(ANALYSIS_WINDOW_CONCURRENCY)

    async def run(window: dict) -> List[Scene]:
        async with slots:
            prompt = build_scene_prompt(
                window["transcript"],
                (window["start"], window["end"]),
                _filter_clip_signals_for_window(clip_signals, window["start"], window["end"]),
                request,
            )
            return (await _run_transcript_analysis(agent, prompt)).output.scenes

    results = await asyncio.gather(*(run(w) for w in windows), return_exceptions=True)
    errors = [r for r in results if isinstance(r, BaseException)]
    for error in errors:
        logger.warning("A long-form scene window failed: %s", error)
    if len(errors) == len(results):
        raise errors[0]
    lines = _parse_transcript_lines(transcript)
    scenes = [s for result in results if not isinstance(result, BaseException) for s in ground_scenes(result, lines, duration)]
    logger.info("Long form: the AI found %d scenes in %d windows", len(scenes), len(windows))
    return select_scenes(scenes, minutes)


def ground_scenes(scenes: List[Scene], lines: List[dict], duration: float) -> List[dict]:
    """Seconds, snapped out to whole transcript lines, with a little room before and after."""
    from .ai import _parse_transcript_timestamp_seconds

    grounded = []
    for scene in scenes:
        try:
            start = _parse_transcript_timestamp_seconds(scene.start_time)
            end = _parse_transcript_timestamp_seconds(scene.end_time)
        except ValueError:
            continue
        inside = [line for line in lines if line["end_seconds"] > start and line["start_seconds"] < end]
        if inside:  # never start or end in the middle of a line
            start = min(start, inside[0]["start_seconds"])
            end = max(end, inside[-1]["end_seconds"])
        start, end = max(0.0, start - LEAD_IN), end + TAIL
        if duration:
            end = min(end, duration)
        if end - start >= 10:
            grounded.append({"start": start, "end": end, "title": " ".join(scene.title.split())[:120], "score": scene.score})
    return grounded


def select_scenes(scenes: List[dict], minutes: int) -> List[dict]:
    """The best scenes, in stream order, without overlaps.

    minutes 0 keeps every scene scoring MIN_SCORE or more; otherwise the best scenes that fit in about
    that many minutes (shorter when the stream has less worth keeping). Never empty when there are scenes: the best one is kept at least.
    """
    best = sorted(scenes, key=lambda s: -s["score"])
    if minutes:
        budget, kept = minutes * 60 * 1.1, []
        for scene in best:
            if scene["score"] >= FILL_SCORE and scene["end"] - scene["start"] <= budget:
                kept.append(scene)
                budget -= scene["end"] - scene["start"]
    else:
        kept = [s for s in best if s["score"] >= MIN_SCORE]
    kept = sorted(kept or best[:1], key=lambda s: s["start"])
    result: List[dict] = []
    for scene in kept:
        if result and scene["start"] < result[-1]["end"]:
            if scene["end"] <= result[-1]["end"]:
                continue  # inside the one before
            scene = {**scene, "start": result[-1]["end"]}
        result.append(scene)
    return result


def _keep_copy(video: Path, folder: Path) -> Path:
    """A second name for the stream inside the project, so the 3-day clean-up or "Delete full video"
    cannot take it out from under the edit. No space is used; falls back to the file itself."""
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"stream{video.suffix}"
    try:
        os.link(video, target)
        return target
    except OSError as error:
        logger.warning("Could not link the stream into the project (%s); using it in place", error)
        return video


def build_project(
    temp_dir: str, user_id: str, name: str, video: Path, words: List[dict], scenes: List[dict]
) -> tuple[str, str, Path]:
    """Writes a project with the stream as its one asset and the scenes on the main track; returns
    (project id, asset id, the stream file it uses). The asset still needs its preview files (prepare_asset)."""
    from .editor_document import atomic_json
    from .project_document import Chapter, Clip, ProjectDocument, asset_dir, new_document, project_dir
    from .services.project_service import probe

    project_id = uuid.uuid4().hex
    directory = project_dir(temp_dir, project_id)
    (directory / "exports").mkdir(parents=True)
    asset_id = uuid.uuid4().hex[:12]
    folder = asset_dir(directory, asset_id)
    folder.mkdir(parents=True)
    source = _keep_copy(video, directory / "uploads")
    # The words the clip search already transcribed, so Whisper does not run over the stream again.
    atomic_json(
        folder / "transcript.json",
        {
            "language": None,
            "words": [
                {"s": round(w["start"] / 1000, 3), "e": round(max(w["end"], w["start"] + 10) / 1000, 3), "t": w["text"].strip()}
                for w in words
                if (w.get("text") or "").strip()
            ],
        },
    )
    atomic_json(folder / "meta.json", {"id": asset_id, "name": name[:200], "status": "preparing", "progress": 0, "kind": "video", "path": str(source)})

    info = probe(str(source))
    document = new_document()
    if info.get("width") and info.get("height"):  # like the editor: the first video sets the frame
        document.width = min(3840, round(info["width"] / 2) * 2)
        document.height = min(3840, round(info["height"] / 2) * 2)
        document.fps = min(60, max(1, round(info["fps"] * 1000) / 1000))
    document.captions.enabled = False  # a long video goes up with YouTube's own captions, not burned-in ones
    document.title = name[:200]
    at = 0.0
    for index, scene in enumerate(scenes):
        length = round(scene["end"] - scene["start"], 3)
        document.clips.append(Clip(id=f"scene{index}", track="v1", start=round(at, 3), duration=length, asset=asset_id, offset=round(scene["start"], 3)))
        document.chapters.append(Chapter(time=round(at, 3), title=scene["title"] or f"Part {index + 1}"))
        at += length
    document = ProjectDocument.model_validate(document.model_dump())
    atomic_json(directory / "document.json", {"revision": 0, "document": document.model_dump()})
    # Written last: a project shows up in the list only once it is complete.
    atomic_json(directory / "project.json", {"id": project_id, "user_id": user_id, "name": name[:120] or "Highlights", "created_at": time.time()})
    return project_id, asset_id, source
