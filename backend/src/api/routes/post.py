"""Post a finished clip: YouTube upload with the user's login, and "show the file" for the sites
that have no usable API for a desktop app (TikTok, Instagram). Under /tasks so the frontend's task proxy reaches it."""

import os
import subprocess
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ... import youtube_upload
from ...auth_headers import get_authenticated_user_id
from ...config import get_config
from ...database import get_db
from ...services.task_service import TaskService


def _require_user(request: Request) -> str:
    return str(get_authenticated_user_id(request, get_config()))


# ponytail: one YouTube login per install (a file in TEMP_DIR), like the Twitch login.
router = APIRouter(prefix="/tasks", tags=["post"], dependencies=[Depends(_require_user)])


async def _call(coro):
    try:
        return await coro
    except youtube_upload.YouTubeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except youtube_upload.httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Could not reach YouTube: {exc}")


@router.get("/post/youtube")
async def youtube_status():
    return youtube_upload.status()


@router.post("/post/youtube/login")
async def youtube_login():
    return await _call(youtube_upload.start_login())


@router.post("/post/youtube/login/poll")
async def youtube_login_poll():
    return {"logged_in": await _call(youtube_upload.poll_login())}


@router.post("/post/youtube/logout")
async def youtube_logout():
    youtube_upload.logout()
    return {"logged_in": False}


async def _clip_path(request: Request, db: AsyncSession, task_id: str, clip_id: str) -> Path:
    service = TaskService(db)
    task = await service.task_repo.get_task_by_id(db, task_id)
    if not task or task.get("user_id") != _require_user(request):
        raise HTTPException(status_code=404, detail="Task not found")
    clip = await service.clip_repo.get_clip_by_id(db, clip_id)
    if not clip or clip.get("task_id") != task_id or not Path(clip["file_path"]).exists():
        raise HTTPException(status_code=404, detail="Clip file not found")
    await db.close()  # not held through the upload
    return Path(clip["file_path"]).resolve()


class YouTubePost(BaseModel):
    title: str
    description: str = ""
    privacy: str = "public"


@router.post("/{task_id}/clips/{clip_id}/post/youtube")
async def post_to_youtube(task_id: str, clip_id: str, body: YouTubePost, request: Request,
                          db: AsyncSession = Depends(get_db, scope="function")):
    path = await _clip_path(request, db, task_id, clip_id)
    return await _call(youtube_upload.upload(path, body.title, body.description, body.privacy))


@router.post("/{task_id}/clips/{clip_id}/reveal")
async def reveal_clip(task_id: str, clip_id: str, request: Request,
                      db: AsyncSession = Depends(get_db, scope="function")):
    """Show the clip's file selected in File Explorer, ready to drag onto a site's upload page."""
    path = await _clip_path(request, db, task_id, clip_id)
    revealed = os.name == "nt"
    if revealed:
        subprocess.Popen(["explorer", f"/select,{path}"])
    return {"revealed": revealed, "path": str(path)}
