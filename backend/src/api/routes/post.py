"""Post finished clips: show a clip's file in File Explorer, or copy several into one folder,
ready to drag onto a site's upload page.
Under /tasks so the frontend's task proxy reaches it."""

import os
import re
import shutil
import subprocess
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...clip_editor import EXPORT_PRESETS, export_with_preset
from ...auth_headers import get_authenticated_user_id
from ...config import get_config
from ...database import get_db
from ...services.task_service import TaskService
from ...utils.async_helpers import run_in_thread

router = APIRouter(prefix="/tasks", tags=["post"])


EXPORT_ROOT = Path.home() / "Videos" / "LocalClip"  # ponytail: fixed place, a setting if someone asks for another drive


def safe_name(text: str, fallback: str) -> str:
    """A file or folder name Windows accepts."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", text or "")
    return " ".join(cleaned.split())[:80].rstrip(". ") or fallback


def export_folder(task: dict) -> Path:
    return EXPORT_ROOT / safe_name(task.get("source_title") or "", task["id"][:8])


def export_name(clip: dict, preset: str) -> str:
    title = safe_name(clip.get("hook_title") or "", "clip")
    suffix = "" if preset == "original" else f" ({preset})"
    return f"{int(clip.get('clip_order') or 0):02d} {title}{suffix}.mp4"


def open_in_explorer(*args: str) -> bool:
    if os.name != "nt":
        return False
    subprocess.Popen(["explorer", *args])
    return True


async def _owned_task(request: Request, service: TaskService, db: AsyncSession, task_id: str) -> dict:
    user_id = str(get_authenticated_user_id(request, get_config()))
    task = await service.task_repo.get_task_by_id(db, task_id)
    if not task or task.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


async def _clip_with_file(service: TaskService, db: AsyncSession, task_id: str, clip_id: str) -> dict:
    clip = await service.clip_repo.get_clip_by_id(db, clip_id)
    if not clip or clip.get("task_id") != task_id or not Path(clip["file_path"]).exists():
        raise HTTPException(status_code=404, detail="Clip file not found")
    return clip


@router.post("/{task_id}/clips/{clip_id}/reveal")
async def reveal_clip(task_id: str, clip_id: str, request: Request,
                      db: AsyncSession = Depends(get_db, scope="function")):
    service = TaskService(db)
    await _owned_task(request, service, db, task_id)
    path = Path((await _clip_with_file(service, db, task_id, clip_id))["file_path"]).resolve()
    return {"revealed": open_in_explorer(f"/select,{path}"), "path": str(path)}


@router.post("/{task_id}/clips/{clip_id}/export-to-folder")
async def export_clip_to_folder(task_id: str, clip_id: str, request: Request, preset: str = "original",
                                db: AsyncSession = Depends(get_db, scope="function")):
    """Copy one clip into the generation's export folder. The batch bar calls this once per ticked clip."""
    if preset not in {"original", "raw", *EXPORT_PRESETS}:
        raise HTTPException(status_code=400, detail="Unknown export format")
    service = TaskService(db)
    task = await _owned_task(request, service, db, task_id)
    clip = await _clip_with_file(service, db, task_id, clip_id)
    if preset == "raw":
        source = await service.render_raw_clip(task_id, clip)
    else:
        await db.close()  # not held through the encode, as in export_clip
        source = Path(clip["file_path"])
        if preset != "original":
            source = await run_in_thread(export_with_preset, source, Path(get_config().temp_dir) / "exports", preset)
    target = export_folder(task) / export_name(clip, preset)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        await run_in_thread(shutil.copyfile, source, target)
    except OSError as exc:  # Windows: the old copy is open in a player or mid-upload
        raise HTTPException(status_code=409, detail=f"Could not write {target.name}: {exc.strerror or exc}")
    return {"folder": str(target.parent), "path": str(target)}


@router.post("/{task_id}/export-folder/open")
async def open_export_folder(task_id: str, request: Request, db: AsyncSession = Depends(get_db, scope="function")):
    folder = export_folder(await _owned_task(request, TaskService(db), db, task_id))
    if not folder.is_dir():
        raise HTTPException(status_code=404, detail="Nothing has been exported yet")
    return {"opened": open_in_explorer(str(folder)), "folder": str(folder)}
