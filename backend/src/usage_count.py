"""Opt-in, anonymous user count.

Nothing is sent until the user says yes (the first-launch question or Settings > Privacy).
After that LocalClip adds 1 to a public counter once per install and once per calendar month.
The request carries no ID and no data about the PC or its videos: it is a bare GET to COUNTER_URL.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .config import get_config

logger = logging.getLogger(__name__)

# Abacus: a free, open-source hit counter (https://abacus.jasoncameron.dev). No account, no key.
# ponytail: third-party hobby service; swap this URL for our own endpoint if it ever goes away.
COUNTER_URL = "https://abacus.jasoncameron.dev/hit/localclip"


def _file() -> Path:
    return Path(get_config().temp_dir) / "usage_count.json"


def load() -> dict:
    try:
        state = json.loads(_file().read_text())
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(state: dict) -> None:
    path = _file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state))


def get_choice() -> bool | None:
    """True = count me, False = don't, None = not asked yet."""
    enabled = load().get("enabled")
    return enabled if isinstance(enabled, bool) else None


def set_choice(enabled: bool) -> None:
    _save({**load(), "enabled": enabled})


async def ping() -> None:
    """Count this install (once) and this month (once). Never raises: counting must not break the app."""
    try:
        # Only the real Windows app counts, not dev servers, Docker or CI.
        if os.getenv("LOCALCLIP_NATIVE") != "1" or get_choice() is not True:
            return
        state = load()
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        keys = ([] if state.get("installed") else ["installs"]) + (
            [] if state.get("month") == month else [f"active-{month}"]
        )
        if not keys:
            return
        async with httpx.AsyncClient(timeout=10) as client:
            for key in keys:
                (await client.get(f"{COUNTER_URL}/{key}")).raise_for_status()
        _save({**load(), "installed": True, "month": month})
    except Exception as exc:  # offline, service down: try again next start
        logger.info("Usage count not sent: %s", exc)
