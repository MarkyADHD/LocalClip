"""Post finished clips: show a clip's file in File Explorer, or copy several into one folder, ready to drag
onto a site's upload page, and write a clip's captions with the AI model.
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
from ...post_captions import write_captions
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


async def owned_clip(task_id: str, clip_id: str, request: Request, db: AsyncSession) -> tuple[dict, dict]:
    user_id = str(get_authenticated_user_id(request, get_config()))
    service = TaskService(db)
    task = await service.task_repo.get_task_by_id(db, task_id)
    if not task or task.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Task not found")
    clip = await service.clip_repo.get_clip_by_id(db, clip_id)
    if not clip or clip.get("task_id") != task_id:
        raise HTTPException(status_code=404, detail="Clip not found")
    return task, clip


@router.post("/{task_id}/clips/{clip_id}/captions")
async def clip_captions(task_id: str, clip_id: str, request: Request,
                        db: AsyncSession = Depends(get_db, scope="function")):
    """A caption with hashtags for each site, written by the AI model from the clip's transcript."""
    task, clip = await owned_clip(task_id, clip_id, request, db)
    try:
        return await write_captions(clip, task.get("source_title"))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"The AI model could not answer: {str(error)[:300]}")


@router.post("/{task_id}/clips/{clip_id}/reveal")
async def reveal_clip(task_id: str, clip_id: str, request: Request,
                      db: AsyncSession = Depends(get_db, scope="function")):
    _, clip = await owned_clip(task_id, clip_id, request, db)
    if not Path(clip["file_path"]).exists():
        raise HTTPException(status_code=404, detail="Clip file not found")
    path = Path(clip["file_path"]).resolve()
    return {"revealed": open_in_explorer(f"/select,{path}"), "path": str(path)}


@router.post("/{task_id}/clips/{clip_id}/export-to-folder")
async def export_clip_to_folder(task_id: str, clip_id: str, request: Request, preset: str = "original",
                                db: AsyncSession = Depends(get_db, scope="function")):
    """Copy one clip into the generation's export folder. The batch bar calls this once per ticked clip."""
    if preset not in {"original", "raw", *EXPORT_PRESETS}:
        raise HTTPException(status_code=400, detail="Unknown export format")
    task, clip = await owned_clip(task_id, clip_id, request, db)
    source = Path(clip["file_path"])
    if not source.exists():
        raise HTTPException(status_code=404, detail="Clip file not found")
    if preset == "raw":
        source = await TaskService(db).render_raw_clip(task_id, clip)
    else:
        await db.close()  # not held through the encode, as in export_clip
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
    task = await TaskService(db).task_repo.get_task_by_id(db, task_id)
    if not task or task.get("user_id") != str(get_authenticated_user_id(request, get_config())):
        raise HTTPException(status_code=404, detail="Task not found")
    folder = export_folder(task)
    if not folder.is_dir():
        raise HTTPException(status_code=404, detail="Nothing has been exported yet")
    return {"opened": open_in_explorer(str(folder)), "folder": str(folder)}
