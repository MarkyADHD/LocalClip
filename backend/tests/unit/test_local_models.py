import asyncio

import httpx
from pydantic_ai import PromptedOutput

from src.ai import TranscriptAnalysis, _get_missing_llm_key_error, _output_type
from src.api.routes import admin
from src.config import Config


def test_local_provider_is_supported_and_uses_prompted_json():
    assert _get_missing_llm_key_error("local:qwen3:8b", Config()) is None
    assert isinstance(_output_type("local", TranscriptAnalysis), PromptedOutput)
    assert _output_type("ollama", TranscriptAnalysis) is TranscriptAnalysis


def test_discover_local_models_lists_only_servers_that_answer(monkeypatch):
    def handler(request: httpx.Request):
        if request.url.port == 1234:
            return httpx.Response(200, json={"data": [{"id": "qwen3-8b"}, {"id": "gemma-3-4b"}]})
        if request.url.port == 11434:
            return httpx.Response(200, json={"data": []})
        raise httpx.ConnectError("refused")

    real_client = httpx.AsyncClient
    monkeypatch.setattr(admin.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(Config, "_default_ollama_base_url", staticmethod(lambda: "http://localhost:11434/v1"))

    servers = asyncio.run(admin.discover_local_models("http://localhost:11434/v1/"))

    assert servers == [
        {"name": "LM Studio", "base_url": "http://localhost:1234/v1", "models": ["gemma-3-4b", "qwen3-8b"]}
    ]
