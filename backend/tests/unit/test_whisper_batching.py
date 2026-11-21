from types import SimpleNamespace

import numpy as np

from src.media import transcription


class FakeModel:
    def __init__(self):
        self.calls = []

    def transcribe(self, audio, **options):
        self.calls.append(("plain", options))
        return iter([]), SimpleNamespace(language="en")


class FakeBatched:
    def __init__(self, model):
        self.model = model

    def transcribe(self, audio, batch_size, **options):
        self.model.calls.append(("batched", {"batch_size": batch_size, **options}))
        word = SimpleNamespace(word=" hi", start=0.0, end=0.4, probability=0.9)
        return iter([SimpleNamespace(start=0.0, end=0.4, text=" hi", words=[word])]), SimpleNamespace(language="en")


def _setup(monkeypatch, tmp_path, gpu):
    model = FakeModel()
    monkeypatch.setattr(transcription, "_prepare_audio_for_transcription", lambda p: tmp_path / "a.mp3")
    monkeypatch.setattr(transcription, "_get_whisper_model", lambda name: model)
    monkeypatch.setattr(transcription, "_decode_audio_chunk", lambda path, offset: np.zeros(16000 if not offset else 0, np.float32))
    monkeypatch.setattr(transcription, "_whisper_on_gpu", lambda: gpu)
    monkeypatch.setattr(transcription, "_whisper", SimpleNamespace(BatchedInferencePipeline=FakeBatched))
    return model


def test_gpu_transcription_is_batched_with_the_same_options(monkeypatch, tmp_path):
    model = _setup(monkeypatch, tmp_path, gpu=True)

    result = transcription.transcribe_with_whisper(tmp_path / "v.mp4", "turbo", "en_us")

    kind, options = model.calls[0]
    assert kind == "batched" and options["batch_size"] == transcription.WHISPER_GPU_BATCH_SIZE
    assert options["word_timestamps"] and options["vad_filter"] and not options["condition_on_previous_text"]
    assert options["language"] == "en"
    assert result["segments"][0]["words"][0]["word"] == " hi"


def test_cpu_transcription_stays_unbatched(monkeypatch, tmp_path):
    model = _setup(monkeypatch, tmp_path, gpu=False)
    transcription.transcribe_with_whisper(tmp_path / "v.mp4", "turbo")
    assert model.calls[0][0] == "plain"


def test_long_audio_is_transcribed_an_hour_at_a_time_with_shifted_timestamps(monkeypatch, tmp_path):
    model = _setup(monkeypatch, tmp_path, gpu=True)
    hour = transcription.WHISPER_CHUNK_SECONDS
    sizes = {0: hour * 16000, hour: 16000}  # one full hour, then a 1 s tail
    monkeypatch.setattr(
        transcription, "_decode_audio_chunk", lambda path, offset: np.zeros(sizes.get(offset, 0), np.float32)
    )

    result = transcription.transcribe_with_whisper(tmp_path / "v.mp4", "turbo")

    assert [s["start"] for s in result["segments"]] == [0.0, float(hour)]
    assert result["segments"][1]["words"][0]["end"] == hour + 0.4
    # language is detected on the first hour and pinned for the rest
    assert [options["language"] for _, options in model.calls] == [None, "en"]
