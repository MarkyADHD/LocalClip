from src.editor_document import CaptionStyle, EditDocument, write_ass
from src.media.diarization import MAX_SPEAKERS, SPEAKER_COLORS, assign_speakers


def words(*spans):
    return [{"text": f"w{i}", "start": s, "end": e} for i, (s, e) in enumerate(spans)]


def test_speaker_zero_is_whoever_says_the_most():
    spoken = words((0, 1), (1, 2), (5, 6), (6, 7), (7, 8))
    # The diarizer numbers the first voice 0; the second voice says more words.
    assert assign_speakers(spoken, [(0, 2, 0), (5, 8, 1)]) == [1, 1, 0, 0, 0]


def test_word_in_a_gap_joins_the_nearest_turn_and_blips_are_dropped():
    spoken = words((0, 1), (2.1, 2.3), (2.6, 3.5), (4, 5))
    turns = [(0, 1.5, "A"), (2.0, 2.2, "C"), (2.5, 6, "B")]  # C speaks for 0.2 s: a misfire
    assert assign_speakers(spoken, turns) == [1, 0, 0, 0]


def test_one_word_flip_inside_a_sentence_is_smoothed():
    spoken = words((0, 1), (1, 2), (2, 3), (3, 4), (4, 5))
    assert assign_speakers(spoken, [(0, 2, 0), (2, 3, 1), (3, 5, 0), (9, 12, 1)]) == [0] * 5


def test_no_turns_and_too_many_speakers():
    assert assign_speakers(words((0, 1)), []) == [0]
    spoken = words(*[(i * 2, i * 2 + 2) for i in range(9)])
    result = assign_speakers(spoken, [(i * 2, i * 2 + 2, i) for i in range(9)])
    assert max(result) == MAX_SPEAKERS - 1


def test_export_colours_each_speaker(tmp_path):
    document = EditDocument.model_validate(
        {
            "segments": [{"id": "s", "start": 0, "end": 3}],
            "captions": {"color": "#FFFFFF", "speakerColors": ["#112233"]},
            "words": [
                {"id": "a", "start": 0, "end": 1, "text": "mine"},
                {"id": "b", "start": 1, "end": 2, "text": "yours", "speaker": 1},
                {"id": "c", "start": 2, "end": 3, "text": "theirs", "speaker": 2},  # no colour set
            ],
        }
    )
    write_ass(tmp_path / "c.ass", document, 1080, 1920)
    text = (tmp_path / "c.ass").read_text()
    assert "{\\c&H00FFFFFF&}mine {\\c&H00332211&}yours {\\c&H00FFFFFF&}theirs" in text
    # Drafts saved before speakers existed load with the default colours.
    assert CaptionStyle().speakerColors == SPEAKER_COLORS
