from src.ai import search_transcript

TRANSCRIPT = """[00:00 - 00:06] Welcome back everybody
[00:06 - 00:12] oh my God, he did NOT just
[00:12 - 00:19] do that. Clip that!
[100:05 - 100:11] No way, no way
"""


def test_finds_phrases_ignoring_case_and_punctuation_even_across_lines():
    assert search_transcript(TRANSCRIPT, "  ") == []
    assert search_transcript(TRANSCRIPT, "banana") == []

    (hit,) = search_transcript(TRANSCRIPT, "oh my god")
    assert (hit["start"], hit["end"], hit["label"]) == (6, 12, "00:06")

    # The phrase runs over a line end: one hit covering both lines, not two.
    (hit,) = search_transcript(TRANSCRIPT, "did not just do that")
    assert (hit["start"], hit["end"]) == (6, 19) and "Clip that" in hit["text"]

    # A phrase inside one line is not also reported through the line before it.
    (hit,) = search_transcript(TRANSCRIPT, "clip that")
    assert hit["start"] == 12

    assert search_transcript(TRANSCRIPT, "no way")[0]["start"] == 100 * 60 + 5  # past 99 minutes
    assert len(search_transcript(TRANSCRIPT * 40, "welcome", limit=5)) == 5
