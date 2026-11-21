from src import config
from src.config import Config


def test_default_ollama_base_url_uses_localhost_outside_docker(monkeypatch):
    monkeypatch.setattr(config.os.path, "exists", lambda path: False)

    assert Config._default_ollama_base_url() == "http://localhost:11434/v1"


def test_default_ollama_base_url_uses_host_gateway_in_docker(monkeypatch):
    monkeypatch.setattr(config.os.path, "exists", lambda path: path == "/.dockerenv")

    assert Config._default_ollama_base_url() == "http://host.docker.internal:11434/v1"


def test_youtube_duration_limit_uses_active_subscription_plan(monkeypatch):
    monkeypatch.setenv("MAX_VIDEO_DURATION", "5400")
    monkeypatch.setenv("PRO_YOUTUBE_MAX_VIDEO_DURATION", "7200")
    monkeypatch.setenv("SCALE_YOUTUBE_MAX_VIDEO_DURATION", "10800")
    monkeypatch.setenv("SELF_HOST", "false")
    config = Config()

    assert config.max_youtube_video_duration_for_plan("free", "active") == 5400
    assert config.max_youtube_video_duration_for_plan("pro", "active") == 7200
    assert config.max_youtube_video_duration_for_plan("scale", "trialing") == 10800
    assert config.max_youtube_video_duration_for_plan("scale", "inactive") == 5400


def test_self_hosted_has_no_length_or_size_limit(monkeypatch):
    monkeypatch.setenv("MAX_VIDEO_DURATION", "43200")  # what existing installs have in .env
    monkeypatch.delenv("SELF_HOST", raising=False)
    config = Config()

    day = 24 * 3600
    assert config.max_video_duration > day and config.max_youtube_video_duration_for_plan("free", None) > day
    assert config.max_video_upload_bytes > 500 * 10**9


def test_whisper_accepts_documented_model_size_setting(monkeypatch):
    monkeypatch.delenv("WHISPER_MODEL", raising=False)
    monkeypatch.setenv("WHISPER_MODEL_SIZE", "tiny")
    assert Config().whisper_model == "tiny"
    monkeypatch.setenv("WHISPER_MODEL", "base")
    assert Config().whisper_model == "base"
