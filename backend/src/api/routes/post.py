"""Post a finished clip: show its file in File Explorer, ready to drag onto a site's upload page.
Under /tasks so the frontend's task proxy reaches it."""

import os
import subprocess
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth_headers import get_authenticated_user_id
from ...config import get_config
from ...database import get_db
from ...services.task_service import TaskService

router = APIRouter(prefix="/tasks", tags=["post"])


@router.post("/{task_id}/clips/{clip_id}/reveal")
async def reveal_clip(task_id: str, clip_id: str, request: Request,
                      db: AsyncSession = Depends(get_db, scope="function")):
    user_id = str(get_authenticated_user_id(request, get_config()))
    service = TaskService(db)
    task = await service.task_repo.get_task_by_id(db, task_id)
    if not task or task.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Task not found")
    clip = await service.clip_repo.get_clip_by_id(db, clip_id)
    if not clip or clip.get("task_id") != task_id or not Path(clip["file_path"]).exists():
        raise HTTPException(status_code=404, detail="Clip file not found")
    path = Path(clip["file_path"]).resolve()
    revealed = os.name == "nt"
    if revealed:
        subprocess.Popen(["explorer", f"/select,{path}"])
    return {"revealed": revealed, "path": str(path)}
