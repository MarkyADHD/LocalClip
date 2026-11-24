"""Anonymous user count, on by default; Settings > Privacy turns it off.

LocalClip adds 1 to a public counter once per install and once per calendar month.
The request carries no ID and no data about the PC or its videos: it is a bare GET to COUNTER_URL.
"""

from __future__ import annotations

import asyncio
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


def get_choice() -> bool:
    """Counted unless the user turned it off."""
    return load().get("enabled") is not False


def set_choice(enabled: bool) -> None:
    _save({**load(), "enabled": enabled})


# Waits between tries while the app stays open. A timeout on the first try (seen on a real PC,
# 10 s after startup) used to mean no count until the next launch.
RETRY_DELAYS = (0, 60, 600, 3600)


async def ping() -> None:
    """Count this install (once) and this month (once). Never raises: counting must not break the app."""
    for delay in RETRY_DELAYS:
        await asyncio.sleep(delay)
        try:
            # Only the real Windows app counts, not dev servers, Docker or CI.
            if os.getenv("LOCALCLIP_NATIVE") != "1" or not get_choice():
                return
            month = datetime.now(timezone.utc).strftime("%Y-%m")
            async with httpx.AsyncClient(timeout=30) as client:
                # Saved after each hit, so a failure on the second never counts the first twice.
                if not load().get("installed"):
                    (await client.get(f"{COUNTER_URL}/installs")).raise_for_status()
                    _save({**load(), "installed": True})
                if load().get("month") != month:
                    (await client.get(f"{COUNTER_URL}/active-{month}")).raise_for_status()
                    _save({**load(), "month": month})
            return
        except Exception as exc:  # offline, service down: try again later, then next start
            logger.warning("Usage count not sent: %r", exc)
