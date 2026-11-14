"""MCP server for the video editor, at http://localhost:8000/mcp.

Lets Claude Code, Claude Desktop or any MCP client read a project's transcript and timeline, leave
proposed edits for the user to approve in the editor, and start exports. Only served on a
self-hosted install, where every project on the PC belongs to its one user.

    claude mcp add --transport http localclip http://localhost:8000/mcp
"""

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .config import get_config
from .project_ai import Edit, add_proposal, source_edits, transcript_text
from .project_document import ProjectDocument, project_dir, project_words, projects_root, read_draft, read_json

def _open(project_id: str) -> tuple[Path, ProjectDocument]:
    try:
        directory = project_dir(get_config().temp_dir, project_id)
    except FileNotFoundError:
        raise ValueError("There is no project with that id. Call list_projects to see them.")
    return directory, ProjectDocument.model_validate(read_draft(directory)["document"])


def list_projects() -> list[dict]:
    """The video projects on this PC: id, name and length in seconds."""
    found = []
    for path in projects_root(get_config().temp_dir).glob("*/project.json"):
        project = read_json(path)
        if project:
            _, document = _open(project["id"])
            found.append({"id": project["id"], "name": project["name"], "seconds": round(document.duration, 1)})
    return found


def get_transcript(project_id: str) -> str:
    """What is said in the video as it is cut now, as lines of [start-end] text in timeline seconds."""
    directory, document = _open(project_id)
    return transcript_text(project_words(directory, document)) or "No speech has been transcribed yet."


def get_timeline(project_id: str) -> dict:
    """The project's title, description, chapters, frame size, tracks and the clips on them."""
    directory, document = _open(project_id)
    assets = {a: (read_json(directory / "assets" / a / "meta.json") or {}).get("name", a) for a in {c.asset for c in document.clips if c.asset}}
    return {
        "title": document.title,
        "description": document.description,
        "seconds": round(document.duration, 2),
        "frame": f"{document.width}x{document.height} at {document.fps:g} fps",
        "chapters": [c.model_dump() for c in document.chapters],
        "tracks": [
            {
                "name": track.name,
                "kind": track.kind,
                "clips": [
                    {
                        "start": round(c.start, 2),
                        "seconds": round(c.duration, 2),
                        "what": c.text.content if c.text else assets.get(c.asset, c.asset),
                    }
                    for c in sorted(document.clips, key=lambda c: c.start)
                    if c.track == track.id
                ],
            }
            for track in document.tracks
        ],
    }


def propose_edits(project_id: str, summary: str, edits: list[Edit]) -> str:
    """Suggest edits for the user to accept in the editor's Assistant tab.

    Times are timeline seconds from get_transcript. Kinds: cut (remove start to end; `note` says why),
    chapter (begins at start, title in `text`), title, description (in `text`), and text (on-screen
    words in `text`, shown from start to end). `summary` is a short note to the user.
    """
    directory, document = _open(project_id)
    ready = source_edits(document, project_words(directory, document), edits)
    if not ready:
        return "None of those edits fit the video. Check the times against get_transcript."
    add_proposal(directory, summary.strip()[:2000], ready, "mcp")
    return f"{len(ready)} edits are waiting in the editor's Assistant tab for the user to accept."


async def export_video(project_id: str, quality: str = "standard") -> str:
    """Start rendering the video as it is saved now. Quality is high, standard or small."""
    from fastapi import HTTPException

    from .api.routes.projects import queue_export

    directory, document = _open(project_id)
    try:
        job = await queue_export(directory, project_id, document, quality)
    except HTTPException as error:
        return str(error.detail)
    return f"Export {job['id']} started. Call export_status to follow it."


def export_status(project_id: str) -> list[dict]:
    """The project's exports, newest first: status, progress and the finished file's path."""
    from .api.routes.projects import jobs

    directory, _ = _open(project_id)
    return [
        {**job, **({"file": str(directory / "exports" / f"{job['id']}.mp4")} if job.get("status") == "completed" else {})}
        for job in jobs(directory)
    ]


def create_mcp() -> FastMCP:
    """A fresh server: its session manager runs once, for the life of one app."""
    server = FastMCP(
        "LocalClip",
        instructions=(
            "Tools for LocalClip's video editor. Read a project's transcript, then use propose_edits to "
            "suggest cuts, chapters, a title, a description or on-screen text. Proposals wait in the "
            "editor's Assistant tab until the user accepts them; nothing changes the video directly."
        ),
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
    )
    for tool in (list_projects, get_transcript, get_timeline, propose_edits, export_video, export_status):
        server.tool()(tool)
    return server
