from types import SimpleNamespace

from src.media import transcription


def test_tokens_group_into_timed_words():
    seg = SimpleNamespace(
        start=2.0, end=4.0, text="hello world",
        tokens=[" hel", "lo", " world", "."], timestamps=[0.0, 0.16, 0.4, 1.6], logprobs=None,
    )
    words = transcription._parakeet_words(seg, offset=100.0)
    assert [w["word"] for w in words] == [" hello", " world."]
    assert words[0]["start"] == 102.0 and words[0]["end"] == 102.4  # ends where the next word starts
    assert words[1]["start"] == 102.4 and words[1]["end"] == 104.0  # last word ends with the segment


def _config(language="", parakeet="nemo-parakeet-tdt-0.6b-v3"):
    return SimpleNamespace(whisper_model="turbo", transcription_language=language, parakeet_model=parakeet)


def _setup(monkeypatch, parakeet):
    calls = []
    result = {"segments": [], "text": "", "language": "en"}

    def whisper(path, model, language):
        calls.append(("whisper", model))
        return result

    monkeypatch.setattr(transcription, "transcribe_with_parakeet", lambda p, m, l: calls.append(("parakeet", m)) or parakeet())
    monkeypatch.setattr(transcription, "transcribe_with_whisper", whisper)
    monkeypatch.setattr(transcription, "load_cached_transcript_data", lambda p: None)
    monkeypatch.setattr(transcription, "cache_transcript_data", lambda p, r, whisper_key: calls.append(("key", whisper_key)))
    return calls, result


def test_parakeet_runs_first(monkeypatch, tmp_path):
    calls, result = _setup(monkeypatch, lambda: {"segments": [], "text": "", "language": None})
    transcription._get_transcript_with_whisper(tmp_path / "v.mp4", _config())
    assert calls == [("parakeet", "nemo-parakeet-tdt-0.6b-v3"), ("key", "nemo-parakeet-tdt-0.6b-v3:auto")]


def test_parakeet_failure_falls_back_to_whisper(monkeypatch, tmp_path):
    def boom():
        raise RuntimeError("no CUDA")

    calls, _ = _setup(monkeypatch, boom)
    transcription._get_transcript_with_whisper(tmp_path / "v.mp4", _config())
    assert calls[1:] == [("whisper", "turbo"), ("key", "turbo:auto")]


def test_unsupported_language_or_off_uses_whisper(monkeypatch, tmp_path):
    calls, _ = _setup(monkeypatch, lambda: None)
    transcription._get_transcript_with_whisper(tmp_path / "v.mp4", _config(language="ja"))
    transcription._get_transcript_with_whisper(tmp_path / "v.mp4", _config(parakeet="off"))
    assert [c for c in calls if c[0] != "key"] == [("whisper", "turbo"), ("whisper", "turbo")]
