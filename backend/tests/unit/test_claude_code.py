import json
import stat

import pytest

from src import ai
from src.claude_code import ClaudeCodeAgent

FAKE = """#!/usr/bin/env python3
import json, sys
args = sys.argv[1:]
prompt = sys.stdin.read()
assert args[args.index("--model") + 1] == "sonnet", args
assert args[args.index("--tools") + 1] == "", args
schema = json.loads(args[args.index("--json-schema") + 1])
assert "ranking" in schema["properties"], schema
assert "senior short-form editor" in args[args.index("--system-prompt") + 1]
assert "Candidate 1" in prompt
print(json.dumps({"is_error": False, "total_cost_usd": 0.01,
    "structured_output": {"ranking": [{"candidate_id": 1, "score": 90, "reason": "x"}]}}))
"""


@pytest.mark.asyncio
async def test_rerank_runs_through_claude_code_cli(tmp_path, monkeypatch):
    fake = tmp_path / "claude"
    fake.write_text(FAKE)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("CLAUDE_CODE_PATH", str(fake))
    monkeypatch.setenv("LLM", "claude-code:sonnet")
    monkeypatch.setattr(ai, "_rerank_agent", None)

    agent = ai.get_rerank_agent()
    assert isinstance(agent, ClaudeCodeAgent)
    result = await agent.run("Candidate 1: hello")
    assert result.output.ranking[0].score == 90


@pytest.mark.asyncio
async def test_cli_error_is_raised(tmp_path, monkeypatch):
    fake = tmp_path / "claude"
    fake.write_text("#!/bin/sh\necho '" + json.dumps({"is_error": True, "result": "Not logged in"}) + "'\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("CLAUDE_CODE_PATH", str(fake))
    agent = ClaudeCodeAgent("sonnet", ai.CandidateRanking, "sys")
    with pytest.raises(RuntimeError, match="Not logged in"):
        await agent.run("hi")
