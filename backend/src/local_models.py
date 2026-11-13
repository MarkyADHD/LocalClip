"""Find the LLMs this PC can run clip selection with, and start their server when needed.

Values use the LLM setting format: ``claude-code:<model>``, ``ollama:<model>`` or
``local:<model>`` (any OpenAI-compatible server, at ``LOCAL_LLM_BASE_URL``).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from .claude_code import find_claude

logger = logging.getLogger(__name__)

# OpenAI-compatible servers on their default ports. 8000 is LocalClip's own backend.
OPENAI_COMPATIBLE_SERVERS = (
    ("LM Studio", 1234),
    ("llama.cpp", 8080),
    ("Jan", 1337),
    ("KoboldCpp", 5001),
    ("text-generation-webui", 5000),
    ("LocalAI", 8081),
    ("GPT4All", 4891),
    ("vLLM", 8001),
)
LM_STUDIO_BASE_URL = "http://localhost:1234/v1"
_HIDDEN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _get_json(url: str, timeout: float = 1.0):
    try:
        response = httpx.get(url, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError):
        return None


def _which(name: str, *fallbacks: Path) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    return next((str(p) for p in fallbacks if p.is_file()), None)


def find_ollama() -> str | None:
    local = Path(os.getenv("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
    return _which("ollama", local)


def find_lms() -> str | None:
    return _which("lms", Path.home() / ".lmstudio" / "bin" / "lms.exe")


def ollama_root(base_url: str) -> str:
    return base_url.rstrip("/").removesuffix("/v1")


def _installed_ollama_models() -> list[str]:
    """Model names from Ollama's manifest folder, for when its server is not running."""
    root = Path(os.getenv("OLLAMA_MODELS") or Path.home() / ".ollama" / "models") / "manifests"
    names = []
    for tag in root.glob("*/*/*/*"):
        if not tag.is_file():
            continue
        registry, namespace, model = tag.parts[-4:-1]
        if registry == "registry.ollama.ai":
            prefix = "" if namespace == "library" else f"{namespace}/"
        else:
            prefix = f"{registry}/{namespace}/"
        names.append(f"{prefix}{model}:{tag.name}")
    return sorted(names)


def _lm_studio_downloads(lms: str) -> list[str]:
    try:
        out = subprocess.run(
            [lms, "ls", "--json"], capture_output=True, text=True, timeout=15, creationflags=_HIDDEN
        ).stdout
        return sorted(m["modelKey"] for m in json.loads(out) if m.get("type") == "llm")
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        return []


def _probe_openai_server(name: str, port: int) -> list[dict]:
    base_url = f"http://localhost:{port}/v1"
    data = _get_json(f"{base_url}/models", timeout=0.7)
    if not isinstance(data, dict):
        return []
    return [
        {"llm": f"local:{m['id']}", "label": m["id"], "source": name, "base_url": base_url, "running": True}
        for m in data.get("data") or []
        if isinstance(m, dict) and m.get("id") and "embed" not in m["id"].lower()
    ]


def discover_local_models(ollama_base_url: str) -> list[dict]:
    """Every LLM found on this PC, Claude Code first. ``running`` False means LocalClip
    starts that app's server when the model is used."""
    models: list[dict] = []
    if find_claude():
        for name, label in (("sonnet", "Claude Sonnet (recommended, fastest)"), ("opus", "Claude Opus"), ("haiku", "Claude Haiku")):
            models.append({"llm": f"claude-code:{name}", "label": label, "source": "Claude Code", "base_url": None, "running": True})

    tags = _get_json(f"{ollama_root(ollama_base_url)}/api/tags")
    if isinstance(tags, dict):
        ollama_names, running = [m["name"] for m in tags.get("models") or [] if m.get("name")], True
    else:
        ollama_names, running = (_installed_ollama_models() if find_ollama() else []), False
    models += [
        {"llm": f"ollama:{n}", "label": n, "source": "Ollama", "base_url": None, "running": running}
        for n in ollama_names
        if "embed" not in n.lower()
    ]

    with ThreadPoolExecutor(len(OPENAI_COMPATIBLE_SERVERS)) as pool:
        for found in pool.map(lambda s: _probe_openai_server(*s), OPENAI_COMPATIBLE_SERVERS):
            models += found

    lms = find_lms()
    if lms and not any(m["source"] == "LM Studio" for m in models):
        models += [
            {"llm": f"local:{key}", "label": key, "source": "LM Studio", "base_url": LM_STUDIO_BASE_URL, "running": False}
            for key in _lm_studio_downloads(lms)
        ]
    return models


def _wait_until_up(url: str, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if _get_json(url) is not None:
            return True
        time.sleep(0.5)
    return False


def ensure_local_server(provider: str, ollama_base_url: str, local_base_url: str) -> None:
    """Start Ollama or LM Studio's server if the selected model needs it and it is down."""
    if provider == "ollama":
        tags_url = f"{ollama_root(ollama_base_url)}/api/tags"
        ollama = find_ollama()
        if _get_json(tags_url) is None and ollama:
            logger.info("Starting Ollama (%s serve)", ollama)
            subprocess.Popen(
                [ollama, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=_HIDDEN
            )
            _wait_until_up(tags_url, 20)
    elif provider == "local":
        models_url = f"{local_base_url.rstrip('/')}/models"
        lms = find_lms()
        if _get_json(models_url) is None and lms and local_base_url.rstrip("/") == LM_STUDIO_BASE_URL:
            # LM Studio loads the requested model on its first request (JIT loading).
            logger.info("Starting the LM Studio server")
            subprocess.run([lms, "server", "start"], capture_output=True, timeout=60, creationflags=_HIDDEN)
            _wait_until_up(models_url, 20)


if __name__ == "__main__":
    for row in discover_local_models("http://localhost:11434/v1"):
        print(row)
