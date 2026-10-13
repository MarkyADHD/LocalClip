"""LLM provider that runs the local Claude Code CLI (`LLM=claude-code:sonnet`).

Uses the user's Claude subscription instead of an API key: on the host it is the
signed-in `claude`; in Docker it reads CLAUDE_CODE_OAUTH_TOKEN (`claude setup-token`).
"""

import asyncio
import json
import logging
import os
import shutil
import tempfile
from types import SimpleNamespace
from typing import Generic, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def find_claude() -> Optional[str]:
    home = os.path.expanduser("~")
    for candidate in (
        os.getenv("CLAUDE_CODE_PATH"),
        shutil.which("claude"),
        os.path.join(home, ".local", "bin", "claude"),
        os.path.join(home, ".local", "bin", "claude.exe"),
    ):
        # Windows npm shims (claude.cmd) go through cmd.exe, which mangles the multi-line system prompt.
        if candidate and os.path.isfile(candidate) and not candidate.lower().endswith((".cmd", ".bat")):
            return candidate
    return None


class ClaudeCodeAgent(Generic[T]):
    """Drop-in for the two pydantic-ai Agents in ai.py: `await agent.run(prompt)` -> `.output`."""

    def __init__(self, model: str, output_type: Type[T], system_prompt: str, output_retries: int = 2):
        self.model = model
        self.output_type = output_type
        self.system_prompt = system_prompt
        self.output_retries = output_retries
        self.schema = json.dumps(output_type.model_json_schema(), separators=(",", ":"))

    async def run(self, prompt: str) -> SimpleNamespace:
        for attempt in range(self.output_retries + 1):
            payload = await self._call(prompt)
            try:
                return SimpleNamespace(output=self.output_type.model_validate(payload))
            except ValidationError as error:
                if attempt == self.output_retries:
                    raise
                logger.warning("Claude Code output failed validation (%s errors); retrying", error.error_count())
        raise AssertionError("unreachable")

    async def _call(self, prompt: str) -> dict:
        claude = find_claude()
        if not claude:
            raise RuntimeError("Claude Code CLI not found. Install it and sign in, or set CLAUDE_CODE_PATH.")
        cmd = [
            claude, "-p", "--model", self.model, "--output-format", "json",
            "--tools", "", "--no-session-persistence",
            "--system-prompt", self.system_prompt, "--json-schema", self.schema,
        ]
        # Neutral cwd so no project CLAUDE.md shapes the answer; prompt goes via stdin.
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=tempfile.gettempdir(),
        )
        try:
            stdout, stderr = await proc.communicate(prompt.encode("utf-8"))
        except BaseException:
            proc.kill()
            raise
        try:
            out = json.loads(stdout)
        except ValueError:
            out = {}
        if proc.returncode != 0 or out.get("is_error"):
            detail = out.get("result") or stderr.decode("utf-8", "replace").strip()[-300:] or f"exit {proc.returncode}"
            raise RuntimeError(f"Claude Code failed: {detail}")
        logger.info("Claude Code (%s) answered, cost $%s", self.model, out.get("total_cost_usd"))
        return out.get("structured_output") or {}
