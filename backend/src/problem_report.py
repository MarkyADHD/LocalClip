"""Text for Settings > Help > "Report a problem": what this PC runs plus the ends of the logs.

Nothing is sent anywhere. The app shows the text and the user decides whether to post it.
"""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
from pathlib import Path

from .config import get_config

# GitHub rejects issue bodies over 65,536 characters; leave room for what the user writes.
MAX_CHARS = 40_000
SECRET = re.compile(r"(?i)((?:token|secret|password|api[_-]?key|authorization)\"?\s*[=:]\s*\"?)[^\s\"&,}]+")


def logs_dir() -> Path:
    """The launcher writes logs next to TEMP_DIR: .localclip/data and .localclip/logs."""
    return Path(get_config().temp_dir).resolve().parent / "logs"


def _run(*cmd: str) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def redact(text: str) -> str:
    """Drop the Windows user name and anything that looks like a credential."""
    home = Path.home()
    for needle in {str(home), str(home).replace("\\", "\\\\"), home.as_posix()}:
        text = text.replace(needle, "~")
    return SECRET.sub(r"\1[hidden]", text)


def _tail(path: Path, lines: int) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return ""


def build() -> str:
    config = get_config()
    repo = Path(__file__).resolve().parents[2]
    temp = Path(config.temp_dir)
    free = shutil.disk_usage(temp if temp.exists() else ".").free // 2**30
    parts = [
        "**What happened?**\n\n(write here)\n",
        "**This PC**",
        f"- LocalClip: {_run('git', '-C', str(repo), 'log', '-1', '--format=%h %cs') or 'unknown'}",
        f"- Windows: {platform.platform()}",
        f"- GPU: {_run('nvidia-smi', '--query-gpu=name,memory.total,driver_version', '--format=csv,noheader') or 'no NVIDIA GPU found'}",
        f"- AI model: {config.llm}",
        f"- Whisper: {config.whisper_model}",
        f"- Free disk: {free} GB",
    ]
    logs = logs_dir()
    # This run first, then the newest earlier runs (the launcher keeps them in logs/old/<time>).
    old = sorted((logs / "old").glob("*"), reverse=True)[:2] if (logs / "old").is_dir() else []
    for folder, lines in [(logs, 80), *[(run, 40) for run in old]]:
        for name in ("worker.err.log", "backend.err.log", "web.err.log", "launcher.log"):
            tail = _tail(folder / name, lines)
            if tail:
                label = name if folder == logs else f"{name} (earlier run {folder.name})"
                parts.append(f"\n<details><summary>{label}</summary>\n\n```\n{tail}\n```\n</details>")
    return redact("\n".join(parts))[:MAX_CHARS]
