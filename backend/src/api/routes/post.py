"""Post a finished clip: show its file in File Explorer, ready to drag onto a site's upload page,
and write its captions with the AI model.
Under /tasks so the frontend's task proxy reaches it."""

import os
import subprocess
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth_headers import get_authenticated_user_id
from ...config import get_config
from ...database import get_db
from ...post_captions import write_captions
from ...services.task_service import TaskService

router = APIRouter(prefix="/tasks", tags=["post"])


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
    revealed = os.name == "nt"
    if revealed:
        subprocess.Popen(["explorer", f"/select,{path}"])
    return {"revealed": revealed, "path": str(path)}
