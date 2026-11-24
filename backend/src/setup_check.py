"""What is missing before LocalClip can make clips on this PC, in plain words.

Shown on the home screen (`GET /admin/setup-check`) so a new user sees "Claude Code is not signed in"
before waiting through a download and transcription that would end in a raw error.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from .ai import _get_missing_llm_key_error
from .claude_code import find_claude
from .config import Config
from .local_models import discover_local_models

LOW_DISK_GB = 20  # a long VOD plus its clips; below this downloads start failing mid-way
PICK_MODEL = "Or pick a model that runs on this PC (Ollama, LM Studio) in Settings > AI model."


def _claude_signed_in() -> bool:
    # Same file install.ps1 looks for; the env vars are Claude Code's other ways to sign in.
    return (
        (Path.home() / ".claude" / ".credentials.json").is_file()
        or bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_CODE_OAUTH_TOKEN"))
    )


def _ai_problem(config: Config) -> str | None:
    provider = config.llm.split(":", 1)[0].lower()
    if provider == "claude-code":
        if not find_claude():
            return f"Claude Code is not installed, and it picks the clips. Install it from claude.com/claude-code and sign in. {PICK_MODEL}"
        return None
    if provider in {"ollama", "local"}:
        found = {m["llm"] for m in discover_local_models(config.resolve_ollama_base_url())}
        if config.llm not in found:
            return f"The AI model {config.llm} was not found on this PC. Pick another one in Settings > AI model."
        return None
    return _get_missing_llm_key_error(config.llm, config)


def check(config: Config) -> list[dict]:
    """Problems only, worst first. ``level`` is "error" (clips will fail) or "warning" (slow or risky)."""
    problems: list[dict] = []
    ai = _ai_problem(config)
    if ai:
        problems.append({"id": "ai", "level": "error", "title": "No AI model to pick clips", "detail": ai, "link": "/settings"})
    elif config.llm.lower().startswith("claude-code:") and not _claude_signed_in():
        # ponytail: a warning, not an error, because the sign-in file is the only evidence and Claude Code
        # could keep it elsewhere one day. Make it an error if a real "not signed in" run is ever confirmed.
        problems.append({
            "id": "claude-sign-in", "level": "warning", "title": "Claude Code may not be signed in",
            "detail": f'It picks the clips. If clips fail, open a terminal, run "claude" and sign in. {PICK_MODEL}',
            "link": "/settings",
        })
    if not shutil.which("ffmpeg"):
        problems.append({
            "id": "ffmpeg", "level": "error", "title": "ffmpeg is missing",
            "detail": "LocalClip cuts video with ffmpeg. Close LocalClip and start it again so it can install it.",
        })
    if not shutil.which("nvidia-smi"):
        problems.append({
            "id": "gpu", "level": "warning", "title": "No NVIDIA graphics card found",
            "detail": "LocalClip still works, but transcribing and rendering run on the processor and take much longer.",
        })
    temp = Path(config.temp_dir)
    free_gb = shutil.disk_usage(temp if temp.exists() else ".").free // 2**30
    if free_gb < LOW_DISK_GB:
        problems.append({
            "id": "disk", "level": "warning", "title": f"Only {free_gb} GB of disk space left",
            "detail": "Long streams need room for the video and its clips. Delete old generations in the library to free space.",
        })
    return problems
