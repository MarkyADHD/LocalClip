"""Log in with Twitch and list the user's own videos. Under /tasks so the frontend's task proxy reaches it."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from ... import twitch
from ...auth_headers import get_authenticated_user_id
from ...config import get_config


def _require_user(request: Request) -> str:
    return str(get_authenticated_user_id(request, get_config()))


# ponytail: one Twitch login per install (a file in TEMP_DIR), fine for the one-user desktop app;
# key it by user id if this ever runs multi-user.
router = APIRouter(prefix="/tasks/twitch", tags=["twitch"], dependencies=[Depends(_require_user)])


async def _call(coro):
    try:
        return await coro
    except twitch.TwitchLoginError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except twitch.httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Could not reach Twitch: {exc}")


@router.post("/login")
async def login():
    return await _call(twitch.start_twitch_login())


@router.post("/login/poll")
async def login_poll():
    return {"logged_in": await _call(twitch.poll_twitch_login())}


@router.get("/vods")
async def vods(after: Optional[str] = None):
    return await _call(twitch.list_my_vods(after))


@router.get("/clips")
async def clips(after: Optional[str] = None):
    return await _call(twitch.list_my_clips(after))


@router.post("/logout")
async def logout():
    await twitch.twitch_logout()
    return {"logged_in": False}
