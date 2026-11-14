"""Long-form projects: the media bin, the timeline draft, preview files and exports."""

from pathlib import Path
import mimetypes
import os
import re
import shutil
import subprocess
import time
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_config
from ...database import get_db
from ...editor_document import RevisionConflict, atomic_json, editor_lock
from ...project_ai import ask, read_proposals, remove_proposal
from ...project_document import (
    ProjectDocument,
    project_words,
    asset_dir,
    project_dir,
    projects_root,
    read_assets,
    read_draft,
    read_json,
    save_draft,
)
from ...utils.async_helpers import run_in_thread
from ...workers.job_queue import JobQueue
from .tasks import _get_user_id_from_headers, _read_json_object

router = APIRouter(prefix="/projects", tags=["projects"])

MEDIA = {
    ".mp4", ".mkv", ".mov", ".webm", ".avi", ".flv", ".ts", ".m4v",
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus",
    ".png", ".jpg", ".jpeg", ".webp", ".gif",
}
PREVIEW_FILES = {
    "proxy.mp4": "video/mp4",
    "audio.m4a": "audio/mp4",
    "thumbs.jpg": "image/jpeg",
    "waveform.bin": "application/octet-stream",
    "transcript.json": "application/json",
}
WORKER_DOWN = "The rendering worker is unavailable. Try again shortly."


async def owned(request: Request, db: AsyncSession, project_id: str) -> Path:
    """The project's folder, after checking that the caller owns it."""
    user_id = await _get_user_id_from_headers(request, db)
    await db.close()
    try:
        directory = project_dir(get_config().temp_dir, project_id)
    except FileNotFoundError:
        raise HTTPException(404, "Project not found")
    project = read_json(directory / "project.json")
    if not project or project.get("user_id") != user_id:
        raise HTTPException(404, "Project not found")
    return directory


def jobs(directory: Path) -> list[dict]:
    files = sorted((directory / "exports").glob("job-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"id": p.stem[4:], **(read_json(p) or {})} for p in files[:10]]


@router.get("")
async def list_projects(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = await _get_user_id_from_headers(request, db)
    # ponytail: projects are folders, listed by scanning; move to a table if there are ever thousands.
    found = []
    for path in projects_root(get_config().temp_dir).glob("*/project.json"):
        project = read_json(path)
        if project and project.get("user_id") == user_id:
            draft = read_json(path.parent / "document.json") or {}
            clips = (draft.get("document") or {}).get("clips") or []
            found.append(
                {
                    "id": project["id"],
                    "name": project["name"],
                    "created_at": project["created_at"],
                    "updated_at": max(p.stat().st_mtime for p in (path, path.parent / "document.json") if p.exists()),
                    "duration": max((c["start"] + c["duration"] for c in clips), default=0),
                }
            )
    return {"projects": sorted(found, key=lambda p: p["updated_at"], reverse=True)}


@router.post("", status_code=201)
async def create_project(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = await _get_user_id_from_headers(request, db)
    payload = await _read_json_object(request)
    project_id = uuid.uuid4().hex
    directory = project_dir(get_config().temp_dir, project_id)
    (directory / "assets").mkdir(parents=True)
    (directory / "exports").mkdir()
    project = {
        "id": project_id,
        "user_id": user_id,
        "name": str(payload.get("name") or "Untitled project").strip()[:120] or "Untitled project",
        "created_at": time.time(),
    }
    atomic_json(directory / "project.json", project)
    return project


@router.get("/{project_id}")
async def get_project(project_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    directory = await owned(request, db, project_id)
    project = read_json(directory / "project.json")
    return {
        "id": project["id"],
        "name": project["name"],
        "assets": list(read_assets(directory).values()),
        "draft": read_draft(directory),
        "jobs": jobs(directory),
    }


@router.get("/{project_id}/assets")
async def get_assets(project_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    directory = await owned(request, db, project_id)
    return {
        "assets": list(read_assets(directory).values()),
        "jobs": jobs(directory),
        "proposals": read_proposals(directory),
    }


@router.patch("/{project_id}")
async def save_project(project_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    directory = await owned(request, db, project_id)
    payload = await _read_json_object(request)
    if "name" in payload:
        project = read_json(directory / "project.json")
        project["name"] = str(payload["name"]).strip()[:120] or project["name"]
        atomic_json(directory / "project.json", project)
    if "document" not in payload:
        return {"name": read_json(directory / "project.json")["name"]}
    revision = payload.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise HTTPException(400, "Invalid draft revision")
    try:
        document = ProjectDocument.model_validate(payload["document"])
        result = await run_in_thread(save_draft, directory, document, revision)
    except RevisionConflict as error:
        raise HTTPException(409, str(error))
    except (ValueError, ValidationError) as error:
        raise HTTPException(400, str(error))
    return {"revision": result["revision"]}


@router.delete("/{project_id}")
async def delete_project(project_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    directory = await owned(request, db, project_id)
    # Only the project's own copies go; recordings imported from elsewhere on disk are never touched.
    await run_in_thread(shutil.rmtree, directory, True)
    return {"deleted": True}


# ---------------------------------------------------------------- media bin


async def add_asset(directory: Path, project_id: str, name: str, **source) -> dict:
    asset_id = uuid.uuid4().hex[:12]
    folder = asset_dir(directory, asset_id)
    folder.mkdir(parents=True)
    meta = {"id": asset_id, "name": name[:200], "status": "preparing", "progress": 0, "kind": "video", **source}
    atomic_json(folder / "meta.json", meta)
    try:
        await JobQueue.enqueue_job("prepare_asset", project_id, asset_id)
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise HTTPException(503, WORKER_DOWN)
    return meta


@router.post("/{project_id}/assets", status_code=202)
async def import_asset(project_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Add a file by its path on this computer (used in place, never copied) or by a video link."""
    directory = await owned(request, db, project_id)
    payload = await _read_json_object(request)
    url = str(payload.get("url") or "").strip()
    if url:
        if not re.match(r"^https?://", url):
            raise HTTPException(400, "Enter a full link starting with https://")
        return await add_asset(directory, project_id, url, url=url)
    if not get_config().self_host:
        raise HTTPException(403, "Opening files by path is only available when LocalClip runs on your own computer")
    path = Path(str(payload.get("path") or "").strip().strip('"'))
    if not path.is_absolute() or not path.is_file():
        raise HTTPException(400, "That file was not found. Paste the full path to a video, audio or image file.")
    if path.suffix.lower() not in MEDIA:
        raise HTTPException(400, f"{path.suffix or 'That'} files are not supported")
    return await add_asset(directory, project_id, path.name, path=str(path))


@router.post("/{project_id}/assets/upload", status_code=202)
async def upload_asset(
    project_id: str,
    request: Request,
    uploaded: UploadFile = File(..., alias="file"),
    db: AsyncSession = Depends(get_db),
):
    """Add a file dropped into the browser; it is stored inside the project."""
    directory = await owned(request, db, project_id)
    name = Path(uploaded.filename or "file").name
    suffix = Path(name).suffix.lower()
    if suffix not in MEDIA:
        raise HTTPException(400, f"{suffix or 'That'} files are not supported")
    uploads = directory / "uploads"
    uploads.mkdir(exist_ok=True)
    target = uploads / f"{uuid.uuid4().hex}{suffix}"
    with target.open("wb") as out:
        while chunk := await uploaded.read(1024 * 1024):
            out.write(chunk)
    return await add_asset(directory, project_id, name, path=str(target))


@router.post("/browse")
async def browse(request: Request, db: AsyncSession = Depends(get_db)):
    """Open the Windows file picker on this computer and return the chosen paths."""
    await _get_user_id_from_headers(request, db)
    if os.name != "nt" or not get_config().self_host:
        raise HTTPException(501, "The file picker is only available in the Windows app. Paste the file's path.")
    script = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$owner = New-Object System.Windows.Forms.Form -Property @{TopMost=$true; ShowInTaskbar=$false; Opacity=0};"
        "$owner.Show(); $owner.Activate();"
        "$dialog = New-Object System.Windows.Forms.OpenFileDialog -Property @{Multiselect=$true; Title='Add media to LocalClip';"
        "Filter='Media|" + ";".join(f"*{suffix}" for suffix in sorted(MEDIA)) + "|All files|*.*'};"
        "if ($dialog.ShowDialog($owner) -eq 'OK') { $dialog.FileNames | ForEach-Object { [Console]::Out.WriteLine($_) } };"
        "$owner.Close()"
    )
    try:
        result = await run_in_thread(
            subprocess.run,
            ["powershell", "-NoProfile", "-STA", "-Command", script],
            capture_output=True, text=True, timeout=600, encoding="utf-8",
        )
    except Exception:
        raise HTTPException(500, "Could not open the file picker. Paste the file's path instead.")
    return {"paths": [line.strip() for line in result.stdout.splitlines() if line.strip()]}


@router.delete("/{project_id}/assets/{asset_id}")
async def delete_asset(project_id: str, asset_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    directory = await owned(request, db, project_id)
    try:
        folder = asset_dir(directory, asset_id)
    except FileNotFoundError:
        raise HTTPException(404, "File not found")
    meta = read_json(folder / "meta.json") or {}
    upload = Path(meta.get("path") or "")
    if upload.parent == directory / "uploads":
        upload.unlink(missing_ok=True)
    shutil.rmtree(folder, ignore_errors=True)
    return {"deleted": True}


@router.post("/{project_id}/assets/{asset_id}/transcribe", status_code=202)
async def transcribe(project_id: str, asset_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    directory = await owned(request, db, project_id)
    try:
        path = asset_dir(directory, asset_id) / "meta.json"
    except FileNotFoundError:
        raise HTTPException(404, "File not found")
    meta = read_json(path)
    if not meta or meta.get("status") != "ready" or not meta.get("hasAudio"):
        raise HTTPException(409, "This file has no audio to transcribe")
    if meta.get("transcript") != "pending":
        atomic_json(path, {**meta, "transcript": "pending"})
        try:
            await JobQueue.enqueue_job("transcribe_asset", project_id, asset_id)
        except Exception:
            atomic_json(path, {**meta, "transcript": "failed"})
            raise HTTPException(503, WORKER_DOWN)
    return {"transcript": "pending"}


@router.get("/{project_id}/assets/{asset_id}/{name}")
async def asset_file(
    project_id: str,
    asset_id: str,
    name: str,
    request: Request,
    db: AsyncSession = Depends(get_db, scope="function"),
):
    directory = await owned(request, db, project_id)
    try:
        folder = asset_dir(directory, asset_id)
    except FileNotFoundError:
        raise HTTPException(404, "File not found")
    headers = {"Cache-Control": "private, max-age=3600"}
    if name == "image":
        meta = read_json(folder / "meta.json") or {}
        if meta.get("kind") != "image" or not Path(meta.get("path", "")).is_file():
            raise HTTPException(404, "File not found")
        return FileResponse(meta["path"], media_type=mimetypes.guess_type(meta["path"])[0] or "image/png", headers=headers)
    if name not in PREVIEW_FILES or not (folder / name).exists():
        raise HTTPException(404, "Preview not ready")
    return FileResponse(folder / name, media_type=PREVIEW_FILES[name], headers=headers)


# ---------------------------------------------------------------- export


def job_file(directory: Path, job_id: str) -> Path:
    path = directory / "exports" / f"job-{job_id}.json"
    if not re.fullmatch(r"[a-f0-9]{32}", job_id) or not path.exists():
        raise HTTPException(404, "Export not found")
    return path


async def queue_export(directory: Path, project_id: str, document: ProjectDocument, quality: str) -> dict:
    if document.duration <= 0:
        raise HTTPException(400, "There is nothing on the timeline to export")
    if quality not in {"high", "standard", "small"}:
        raise HTTPException(400, "Unknown export quality")
    exports = directory / "exports"
    exports.mkdir(exist_ok=True)
    with editor_lock(directory):
        if any(job.get("status") in {"queued", "rendering"} for job in jobs(directory)):
            raise HTTPException(429, "An export is already running for this project")
        job_id = uuid.uuid4().hex
        atomic_json(exports / f"request-{job_id}.json", {"document": document.model_dump(), "quality": quality})
        atomic_json(exports / f"job-{job_id}.json", {"status": "queued", "progress": 0})
    try:
        await JobQueue.enqueue_job("export_project", project_id, job_id)
    except Exception:
        atomic_json(exports / f"job-{job_id}.json", {"status": "failed", "progress": 0, "error": WORKER_DOWN})
        raise HTTPException(503, WORKER_DOWN)
    return {"id": job_id, "status": "queued", "progress": 0}


def parse_document(value) -> ProjectDocument:
    try:
        return ProjectDocument.model_validate(value)
    except (ValueError, ValidationError) as error:
        raise HTTPException(400, str(error))


@router.post("/{project_id}/exports", status_code=202)
async def start_export(project_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    directory = await owned(request, db, project_id)
    payload = await _read_json_object(request)
    return await queue_export(
        directory, project_id, parse_document(payload.get("document")), payload.get("quality", "standard")
    )


@router.delete("/{project_id}/exports/{job_id}")
async def cancel_export(project_id: str, job_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    directory = await owned(request, db, project_id)
    path = job_file(directory, job_id)
    status = read_json(path) or {}
    if status.get("status") in {"queued", "rendering"}:
        (directory / "exports" / f"cancel-{job_id}").touch()
        if status["status"] == "queued":
            atomic_json(path, {"status": "cancelled", "progress": 0})
    return {"status": "cancelling"}


@router.get("/{project_id}/exports/{job_id}/file")
async def export_file(
    project_id: str,
    job_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db, scope="function"),
):
    directory = await owned(request, db, project_id)
    status = read_json(job_file(directory, job_id)) or {}
    output = directory / "exports" / f"{job_id}.mp4"
    if status.get("status") != "completed" or not output.exists():
        raise HTTPException(409, "Export is not ready")
    name = re.sub(r"[^\w .-]+", "", read_json(directory / "project.json")["name"]).strip() or "localclip"
    return FileResponse(output, media_type="video/mp4", filename=f"{name}.mp4", headers={"Cache-Control": "private, no-store"})


# ---------------------------------------------------------------- assistant


@router.post("/{project_id}/assistant")
async def assistant(project_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Asks the AI model for edits. Returns proposals only; the editor applies what the user accepts."""
    directory = await owned(request, db, project_id)
    payload = await _read_json_object(request)
    message = str(payload.get("message") or "").strip()[:4000]
    if not message:
        raise HTTPException(400, "Type what you want changed")
    document = parse_document(payload.get("document"))
    history = [h for h in payload.get("history") or [] if isinstance(h, dict)]
    words = await run_in_thread(project_words, directory, document)
    try:
        return await ask(document, words, message, history)
    except Exception as error:
        raise HTTPException(502, f"The AI model could not answer: {str(error)[:300]}")


@router.delete("/{project_id}/proposals/{proposal_id}")
async def dismiss_proposal(project_id: str, proposal_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    directory = await owned(request, db, project_id)
    with editor_lock(directory):
        remove_proposal(directory, proposal_id)
    return {"ok": True}
