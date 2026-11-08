from types import SimpleNamespace

from pydantic_ai.models.openai import OpenAIChatModel

from src import ai, local_models


def test_installed_ollama_models_reads_manifest_names(tmp_path, monkeypatch):
    manifests = tmp_path / "manifests"
    for parts in (
        ("registry.ollama.ai", "library", "qwen3", "8b"),
        ("registry.ollama.ai", "someone", "tiny", "latest"),
        ("hf.co", "User", "Repo-GGUF", "Q4_K_M"),
    ):
        path = manifests.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}")
    monkeypatch.setenv("OLLAMA_MODELS", str(tmp_path))

    assert local_models._installed_ollama_models() == [
        "hf.co/User/Repo-GGUF:Q4_K_M",
        "qwen3:8b",
        "someone/tiny:latest",
    ]


def test_local_provider_uses_openai_compatible_server():
    config = SimpleNamespace(llm="local:qwen3-8b", local_llm_base_url="http://localhost:8080/v1")

    model = ai._build_transcript_model(config)

    assert isinstance(model, OpenAIChatModel)
    assert model.model_name == "qwen3-8b"
    assert str(model.client.base_url).startswith("http://localhost:8080/v1")
    assert ai._get_missing_llm_key_error("local:qwen3-8b", config) is None


def test_long_batched_whisper_segment_is_split_into_sentences():
    from src.media.transcription import format_transcript_for_analysis

    sentence = ["one", "two", "three", "four", "five", "six", "seven", "eight."]
    words = [
        {"word": f" {w}", "start": i * 0.9, "end": i * 0.9 + 0.5, "probability": 1.0}
        for i, w in enumerate(sentence * 4)
    ]
    result = {"segments": [{"start": 0.0, "end": 29.0, "text": " long", "words": words}], "text": "", "language": "en"}

    lines = format_transcript_for_analysis(result)

    assert len(lines) == 4
    assert lines[0] == "[00:00 - 00:06] one two three four five six seven eight."