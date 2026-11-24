from types import SimpleNamespace

from src import setup_check


def _config(tmp_path, llm="claude-code:sonnet"):
    return SimpleNamespace(llm=llm, temp_dir=str(tmp_path), resolve_ollama_base_url=lambda: "http://127.0.0.1:1")


def test_names_what_is_missing_and_is_empty_when_ready(monkeypatch, tmp_path):
    monkeypatch.setattr(setup_check.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(setup_check.shutil, "disk_usage", lambda _: SimpleNamespace(free=500 * 2**30))
    monkeypatch.setattr(setup_check, "find_claude", lambda: "/bin/claude")
    monkeypatch.setattr(setup_check, "_claude_signed_in", lambda: True)
    assert setup_check.check(_config(tmp_path)) == []

    monkeypatch.setattr(setup_check, "_claude_signed_in", lambda: False)
    (problem,) = setup_check.check(_config(tmp_path))
    assert problem["id"] == "claude-sign-in" and problem["level"] == "warning"

    monkeypatch.setattr(setup_check, "find_claude", lambda: None)
    (problem,) = setup_check.check(_config(tmp_path))
    assert problem["level"] == "error" and "not installed" in problem["detail"]

    # A local model that is gone, no GPU, no ffmpeg, nearly full disk.
    monkeypatch.setattr(setup_check, "discover_local_models", lambda _: [{"llm": "ollama:other"}])
    monkeypatch.setattr(setup_check.shutil, "which", lambda name: None)
    monkeypatch.setattr(setup_check.shutil, "disk_usage", lambda _: SimpleNamespace(free=3 * 2**30))
    problems = setup_check.check(_config(tmp_path, "ollama:llama3"))
    assert [p["id"] for p in problems] == ["ai", "ffmpeg", "gpu", "disk"]
    assert "ollama:llama3" in problems[0]["detail"] and "Only 3 GB" in problems[3]["title"]

    monkeypatch.setattr(setup_check, "discover_local_models", lambda _: [{"llm": "ollama:llama3"}])
    assert "ai" not in [p["id"] for p in setup_check.check(_config(tmp_path, "ollama:llama3"))]
