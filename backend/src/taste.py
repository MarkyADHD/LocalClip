"""The streamer's own taste: the last clips they posted or exported, and the last ones they deleted.

The clip rerank gets them as examples, so picks drift toward what this streamer actually keeps.
A small JSON file in the state folder; nothing leaves the PC except inside the rerank prompt.
"""

import json
import os
import threading
import uuid
from pathlib import Path
from typing import Dict, List

from .config import get_config

KEEP = 10  # examples of each kind
MIN_EXAMPLES = 3  # fewer says nothing about taste yet
_lock = threading.Lock()


def _path() -> Path:
    return Path(get_config().temp_dir) / "clip_taste.json"


def _load() -> Dict[str, List[str]]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return {kind: [str(x) for x in data.get(kind, [])][:KEEP] for kind in ("kept", "deleted")}
    except (OSError, ValueError, AttributeError):
        return {"kept": [], "deleted": []}


def describe(clip: dict) -> str:
    words = " ".join(str(clip.get("text") or "").split()[:30])
    return f'"{clip.get("hook_title") or "untitled"}": {words}'


def remember(kind: str, clip: dict) -> None:
    """kind is "kept" (posted, exported) or "deleted". Never raises: taste is a nicety."""
    try:
        example = describe(clip)
        with _lock:
            data = _load()
            other = "deleted" if kind == "kept" else "kept"
            data[other] = [x for x in data[other] if x != example]  # changed their mind
            data[kind] = [example, *[x for x in data[kind] if x != example]][:KEEP]
            path = _path()
            partial = path.with_name(f".{path.name}.{uuid.uuid4().hex}")
            partial.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            os.replace(partial, path)
    except Exception:
        pass


def taste_note() -> str:
    data = _load()
    if len(data["kept"]) + len(data["deleted"]) < MIN_EXAMPLES:
        return ""
    lines = ["\nThis streamer's own choices on earlier clips (lean toward their taste, but judge every candidate on its own):"]
    if data["kept"]:
        lines += ["Clips they posted or exported:", *(f"- {x}" for x in data["kept"])]
    if data["deleted"]:
        lines += ["Clips they deleted:", *(f"- {x}" for x in data["deleted"])]
    return "\n".join(lines) + "\n"
