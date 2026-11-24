from pathlib import Path
from types import SimpleNamespace

from src import problem_report


def test_report_has_this_run_and_earlier_runs_without_the_user_name_or_secrets(monkeypatch, tmp_path):
    logs = tmp_path / "logs"
    (logs / "old" / "20261124-180000").mkdir(parents=True)
    home = Path.home()
    (logs / "worker.err.log").write_text(f"line\nTraceback in {home}\\clip.mp4\naccess_token=abc123 next\n")
    (logs / "old" / "20261124-180000" / "worker.err.log").write_text("earlier failure\n")
    config = SimpleNamespace(temp_dir=str(tmp_path / "data"), llm="claude-code:sonnet", whisper_model="turbo")
    monkeypatch.setattr(problem_report, "get_config", lambda: config)

    report = problem_report.build()

    assert "Traceback in ~" in report and str(home) not in report
    assert "abc123" not in report and "access_token=[hidden] next" in report
    assert "earlier failure" in report and "earlier run 20261124-180000" in report
    assert "claude-code:sonnet" in report
    assert len(report) <= problem_report.MAX_CHARS
