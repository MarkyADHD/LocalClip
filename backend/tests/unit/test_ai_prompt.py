from types import SimpleNamespace

from pydantic_ai.models.ollama import OllamaModel

from src.ai import (
    MIN_ACCEPTED_CLIP_SECONDS,
    TranscriptSegment,
    _build_transcript_model,
    _choose_repaired_bounds,
    _extract_transcript_text,
    _format_transcript_timestamp,
    _get_missing_llm_key_error,
    _parse_transcript_spans,
    _parse_transcript_timestamp_seconds,
    build_transcript_analysis_prompt,
    transcript_analysis_system_prompt,
)


def test_system_prompt_enforces_grounding_rules():
    assert "extraction and ranking, not creative rewriting" in (
        transcript_analysis_system_prompt
    )
    assert "Never invent facts, tone, context, or transitions" in (
        transcript_analysis_system_prompt
    )
    assert "Each selected segment must map to one contiguous range" in (
        transcript_analysis_system_prompt
    )
    assert "Do not judge, moralize, or downgrade a segment" in (
        transcript_analysis_system_prompt
    )
    assert "must be 15-90 seconds long, or up to 5 minutes" in transcript_analysis_system_prompt
    assert "25-50" not in transcript_analysis_system_prompt
    assert "WHAT IS NOT A CLIP" in transcript_analysis_system_prompt
    assert "Tutorials, strategy" in transcript_analysis_system_prompt
    assert "Return valid JSON only" in transcript_analysis_system_prompt
    assert "Do not use \"segment\" as an output field. Use \"text\"." in (
        transcript_analysis_system_prompt
    )


def test_build_transcript_analysis_prompt_requires_transcript_fidelity():
    prompt = build_transcript_analysis_prompt(
        transcript="[00:12 - 00:21] A strong opening line"
    )

    assert "Do not fabricate or embellish content." in prompt
    assert "Do not merge separate non-contiguous moments into one segment." in prompt
    assert "If there is a tradeoff between \"viral\" and \"accurate\", choose accuracy." in prompt
    assert "Do not reject or penalize a segment simply because of the subject matter" in prompt
    assert "as long as its moment needs, from 15 to 90 seconds" in prompt
    assert "25-50" not in prompt
    assert "viewer would understand and care without seeing the rest" in prompt
    assert "Return one valid JSON object and nothing else." in prompt
    assert "No Markdown, headings, bullets, code fences" in prompt
    assert "[00:12 - 00:21] A strong opening line" in prompt


def test_build_transcript_analysis_prompt_mentions_broll_only_when_enabled():
    without_broll = build_transcript_analysis_prompt(
        transcript="[00:12 - 00:21] A strong opening line"
    )
    with_broll = build_transcript_analysis_prompt(
        transcript="[00:12 - 00:21] A strong opening line",
        include_broll=True,
    )

    assert "B-roll opportunities" not in without_broll
    assert "B-roll opportunities" in with_broll


def test_ollama_llm_builds_native_ollama_model():
    runtime_config = SimpleNamespace(
        llm="ollama:gpt-oss:20b",
        ollama_api_key=None,
        resolve_ollama_base_url=lambda: "http://ollama.example/v1",
    )

    model = _build_transcript_model(runtime_config)

    assert isinstance(model, OllamaModel)
    assert model.model_name == "gpt-oss:20b"
    assert model.base_url == "http://ollama.example/v1/"


def test_parse_transcript_timestamp_supports_minute_and_hour_formats():
    assert _parse_transcript_timestamp_seconds("02:35") == 155
    assert _parse_transcript_timestamp_seconds("01:02:35") == 3755
    assert _format_transcript_timestamp(155) == "02:35"
    assert _format_transcript_timestamp(3755) == "01:02:35"
    assert MIN_ACCEPTED_CLIP_SECONDS == 15


def test_transcript_span_helpers_repair_near_miss_durations():
    spans = _parse_transcript_spans(
        "\n".join(
            [
                "[00:00 - 00:10] Setup",
                "[00:10 - 00:24] Short highlight",
                "[00:24 - 00:36] Payoff",
                "[00:36 - 01:50] Too much background",
            ]
        )
    )

    assert _extract_transcript_text(spans, 10, 36) == "Short highlight Payoff"
    assert _choose_repaired_bounds(spans, 10, 24) == (0, 24)  # least extra time, no target length
    assert _choose_repaired_bounds(spans, 0, 110) == (0, 36)  # over 90 s: back to the last line end that fits


def test_transcript_segment_normalizes_percent_relevance_score():
    segment = TranscriptSegment(
        start_time="00:00",
        end_time="00:30",
        text="A complete standalone moment with useful context.",
        relevance_score=100,
    )

    assert segment.relevance_score == 1.0


def test_llm_validation_rejects_unsupported_or_incomplete_model_names():
    runtime_config = SimpleNamespace(
        google_api_key=None,
        openai_api_key=None,
        anthropic_api_key=None,
    )

    assert "Unsupported LLM provider" in _get_missing_llm_key_error(
        "mystery:model", runtime_config
    )
    assert "missing a model name" in _get_missing_llm_key_error(
        "ollama:", runtime_config
    )
    assert _get_missing_llm_key_error("ollama:gpt-oss:20b", runtime_config) is None


def test_clip_request_steers_the_search_and_the_rerank():
    from src.ai import build_candidate_rerank_prompt, build_transcript_analysis_prompt

    transcript = "[00:00 - 00:30] I died again to the same guy"
    plain = build_transcript_analysis_prompt(transcript)
    asked = build_transcript_analysis_prompt(transcript, clip_request="only the funny deaths")
    assert "asked for" not in plain
    assert '"only the funny deaths". Pick only moments that match' in asked

    segment = TranscriptSegment(
        start_time="00:00", end_time="00:30", text="I died again", relevance_score=0.9
    )
    rerank = build_candidate_rerank_prompt([segment, segment], clip_request="only the funny deaths")
    assert "does not match the request scores below 40" in rerank
    assert "asked for" not in build_candidate_rerank_prompt([segment, segment])


def test_a_clip_keeps_its_talking_stretch_and_loses_the_dead_air():
    from src.ai import _parse_transcript_lines, _validate_segments

    transcript = "\n".join([
        "[04:16 - 04:21] He does his rave on his streams. He's not even a real streamer.",
        "[04:22 - 04:27] He's been streaming for years and still hasn't made it.",
        "[04:33 - 04:37] Nobody cares about your intro, mate. How is this even content?",
        "[04:37 - 04:41] He'll never make it on Twitch. All that setup is for 10 views.",
        "[05:08 - 05:09] For you.",
    ])
    lines = _parse_transcript_lines(transcript)
    segment = TranscriptSegment(start_time="04:16", end_time="05:09", text="He does his rave", relevance_score=0.9)
    [kept] = _validate_segments([segment], lines, [])
    assert (kept.start_time, kept.end_time) == ("04:16", "04:41")
    assert kept.text.endswith("10 views.")

    # Dropping the far line would leave too little: it stays (the render cuts the pause).
    lonely = TranscriptSegment(start_time="04:37", end_time="05:09", text="He'll never make it", relevance_score=0.9)
    [kept] = _validate_segments([lonely], lines, [])
    assert (kept.start_time, kept.end_time) == ("04:37", "05:09")


def test_quiet_gaps_in_an_action_moment_keep_the_whole_clip():
    from src.ai import _parse_transcript_lines, _validate_segments

    # Marky's GTA heist, 2026-11-26: talk in short bursts with 8-18 s gaps. The old trim cut
    # this 89 s pick to its first 3 s and dropped it.
    lines = _parse_transcript_lines("\n".join([
        "[52:17 - 52:20] what if I moved this van and",
        "[52:28 - 52:29] I moved it over here?",
        "[52:44 - 52:45] You know what I mean?",
        "[52:52 - 52:54] Would we then get even",
        "[52:57 - 52:57] more?",
        "[53:15 - 53:17] Wait, where have they gone? They're not in my hands anymore.",
        "[53:27 - 53:32] Oh my god, it works. We've got even more, chat. This doesn't even make",
        "[53:44 - 53:46] We've got, like, unlimited cocaine, dude.",
        "[60:00 - 60:02] Oh, my",
        "[60:35 - 60:39] God. Oh, I thought I was toast. Oh, fuck.",
    ]))
    segment = TranscriptSegment(start_time="52:17", end_time="53:46", text="what if I moved this van", relevance_score=0.9)
    [kept] = _validate_segments([segment], lines, [])
    assert (kept.start_time, kept.end_time) == ("52:17", "53:46")
    # A scream split by a long silence: the far line is the payoff, not a stray.
    scream = TranscriptSegment(start_time="60:00", end_time="60:39", text="Oh, my God", relevance_score=0.9)
    [kept] = _validate_segments([scream], lines, [])
    assert (kept.start_time, kept.end_time) == ("60:00", "60:39")


def test_a_setup_before_a_quiet_stretch_stays_in_the_clip():
    from src.ai import _parse_transcript_lines, _validate_segments

    # Marky's stream: the setup, a quiet drive, then the punchline about it.
    lines = _parse_transcript_lines("\n".join([
        "[00:10 - 00:15] Okay, there is a lady and she is dancing and",
        "[00:15 - 00:22] she got them out. Now, I did not expect her to do that.",
        "[00:22 - 00:30] Yeah, snap that for later, boys. You can't see it.",
        "[00:41 - 00:42] That is not my car.",
        "[00:50 - 00:57] Someone said I need to go to a payday loan place. That goes against my Christian values.",
        "[00:57 - 01:05] I'm going to hell. I'm going to hell. And I took a picture as well.",
    ]))
    segment = TranscriptSegment(start_time="00:10", end_time="01:05", text="Okay, there is a lady", relevance_score=0.9)
    [kept] = _validate_segments([segment], lines, [])
    assert (kept.start_time, kept.end_time) == ("00:10", "01:05")
