import json

import numpy as np

from src.media import streamer_voice, transcription


def _unit(rows):
    rows = np.array(rows, np.float32)
    return rows / np.linalg.norm(rows, axis=1, keepdims=True)


def test_the_most_common_voice_is_the_streamer():
    rng = np.random.default_rng(1)
    streamer = np.eye(16)[0] + rng.normal(0, 0.02, (60, 16))  # one voice, all stream long
    npcs = np.eye(16)[1:11].repeat(4, 0) + rng.normal(0, 0.02, (40, 16))  # ten game characters
    scores = streamer_voice.dominant_voice(_unit(np.vstack([streamer, npcs])))
    assert (scores[:60] >= streamer_voice.STREAMER_MIN).all()
    assert (scores[60:] <= streamer_voice.OTHER_MAX).all()


def test_no_labels_when_no_voice_stands_out():
    everyone_different = _unit(np.eye(64))
    assert streamer_voice.dominant_voice(everyone_different) is None
    assert streamer_voice.dominant_voice(everyone_different[:5]) is None


def test_voice_labels_reach_the_transcript_and_are_kept(monkeypatch, tmp_path):
    video = tmp_path / "vod.mp4"
    words = [{"text": " Nice.", "start": 0, "end": 900}, {"text": " Halt!", "start": 5000, "end": 5900}]
    cached = {"utterances": [{"start": 0, "end": 30000, "text": " Nice. Halt!", "words": words}]}
    calls = []
    monkeypatch.setattr(transcription, "_prepare_audio_for_transcription", lambda path: path)
    monkeypatch.setattr(
        streamer_voice, "label_voices", lambda _audio, spans: calls.append(spans) or ["Streamer", "Other"]
    )

    text = transcription._cached_whisper_transcript(video, cached)
    assert text == "[00:00 - 00:00] Speaker Streamer: Nice.\n[00:05 - 00:05] Speaker Other: Halt!"
    assert calls == [[(0, 900), (5000, 5900)]]

    saved = json.loads(video.with_suffix(".transcript_cache.json").read_text())
    assert transcription._cached_whisper_transcript(video, saved) == text and len(calls) == 1  # not worked out twice
