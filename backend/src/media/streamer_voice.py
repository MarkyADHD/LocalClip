"""Which transcript lines are the streamer and which are another voice (game dialogue, a friend
on voice chat, a video playing), so the clip picker follows the streamer and not a cutscene.

The streamer's mic is the one voice that is there for the whole stream, so the biggest group of
alike-sounding lines is taken to be the streamer. Same voice model as the caption speaker colours
(sherpa-onnx on the CPU); about half a minute per hour of stream.
"""

from pathlib import Path
from typing import List, Optional, Sequence, Tuple
import os

from .common import logger

# Cosine similarity to the streamer's voice. In between is left unlabelled: short lines are noisy.
STREAMER_MIN = 0.45
OTHER_MAX = 0.15
MIN_LINES = 20  # too few to tell who the usual voice is
MIN_LINE_SECONDS = 1.5  # shorter lines are widened to this before fingerprinting
# ponytail: a stream that is mostly someone else's voice (watching videos, one co-host talking
# more) labels that voice as the streamer. Needs under this share of lines to give up instead.
MIN_STREAMER_SHARE = 0.15


def dominant_voice(embeddings) -> "Optional[object]":
    """Similarity of every (unit) row to the most common voice; None when no voice stands out."""
    import numpy as np

    count = len(embeddings)
    if count < MIN_LINES:
        return None
    sample = embeddings[np.random.default_rng(0).choice(count, min(count, 2000), replace=False)]
    seed = sample[((sample @ sample.T) >= 0.5).sum(1).argmax()]
    scores = embeddings @ seed
    for _ in range(3):  # pull the centre from one line to the whole group
        members = embeddings[scores >= STREAMER_MIN]
        if not len(members):
            return None
        centre = members.mean(0)
        scores = embeddings @ (centre / np.linalg.norm(centre))
    if (scores >= STREAMER_MIN).sum() < MIN_STREAMER_SHARE * count:
        return None
    return scores


def label_voices(audio_path: Path, spans_ms: Sequence[Tuple[int, int]]) -> List[Optional[str]]:
    """"Streamer", "Other" or None (unsure) for each (start_ms, end_ms) line of the audio."""
    if len(spans_ms) < MIN_LINES:
        return [None] * len(spans_ms)
    import numpy as np
    import sherpa_onnx

    from .diarization import _models
    from .transcription import WHISPER_CHUNK_SECONDS, _decode_audio_chunk

    extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
        sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(_models()[1]), num_threads=max(1, min(4, (os.cpu_count() or 2) // 2))
        )
    )
    embeddings = np.zeros((len(spans_ms), extractor.dim), np.float32)
    chunk_index, audio = -1, np.empty(0, np.float32)
    for index, (start_ms, end_ms) in enumerate(spans_ms):
        middle = (start_ms + end_ms) / 2000
        half = max((end_ms - start_ms) / 2000, MIN_LINE_SECONDS / 2)
        if int(middle // WHISPER_CHUNK_SECONDS) != chunk_index:  # an hour of audio at a time
            chunk_index = int(middle // WHISPER_CHUNK_SECONDS)
            audio = _decode_audio_chunk(audio_path, chunk_index * WHISPER_CHUNK_SECONDS)
        offset = chunk_index * WHISPER_CHUNK_SECONDS
        samples = audio[max(0, int((middle - half - offset) * 16000)):int((middle + half - offset) * 16000)]
        if len(samples) < 8000:
            continue  # stays a zero row: similar to nothing, so unlabelled
        stream = extractor.create_stream()
        stream.accept_waveform(16000, samples)
        stream.input_finished()
        vector = np.array(extractor.compute(stream), np.float32)
        embeddings[index] = vector / (np.linalg.norm(vector) + 1e-9)

    scores = dominant_voice(embeddings)
    if scores is None:
        logger.info("Streamer voice: no voice stands out in %d lines, leaving them unlabelled", len(spans_ms))
        return [None] * len(spans_ms)
    labels = ["Streamer" if s >= STREAMER_MIN else "Other" if 0 < abs(s) and s <= OTHER_MAX else None for s in scores]
    logger.info(
        "Streamer voice: %d streamer lines, %d other voices, %d unsure",
        labels.count("Streamer"), labels.count("Other"), labels.count(None),
    )
    return labels
