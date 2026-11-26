from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src import ai


def _label(seconds: int) -> str:
    minutes, secs = divmod(seconds, 60)
    return f"{minutes:02d}:{secs:02d}"


def _transcript(total_seconds: int, line_seconds: int = 10) -> str:
    return "\n".join(
        f"[{_label(start)} - {_label(start + line_seconds)}] Speaker A: Line at {start} seconds is here."
        for start in range(0, total_seconds, line_seconds)
    )


def _segment(start: str, end: str, total: int = 60, text: str = "Some useful words here.") -> ai.TranscriptSegment:
    quarter = total // 4
    return ai.TranscriptSegment(
        start_time=start,
        end_time=end,
        text=text,
        virality=ai.ViralityAnalysis(
            hook_score=quarter,
            engagement_score=quarter,
            value_score=quarter,
            shareability_score=total - 3 * quarter,
            total_score=total,
        ),
    )


def test_short_transcript_is_a_single_unchanged_window():
    transcript = _transcript(10 * 60)

    windows = ai.split_transcript_into_windows(transcript)

    assert len(windows) == 1
    assert windows[0]["transcript"] == transcript


def test_long_transcript_splits_into_overlapping_windows():
    transcript = _transcript(60 * 60)

    windows = ai.split_transcript_into_windows(transcript)

    assert [(w["start"], w["end"]) for w in windows] == [
        (0, 720), (600, 1320), (1200, 1920), (1800, 2520), (2400, 3120), (3000, 3600),
    ]
    first_lines = windows[0]["transcript"].splitlines()
    assert first_lines[0].startswith("[00:00 - 00:10]")
    assert first_lines[-1].startswith("[11:50 - 12:00]")
    # The overlap repeats the last two minutes of each window in the next one.
    assert windows[1]["transcript"].splitlines()[0].startswith("[10:00 - 10:10]")
    assert windows[-1]["transcript"].splitlines()[-1].startswith("[59:50 - 60:00]")


def test_short_trailing_window_folds_into_previous():
    windows = ai.split_transcript_into_windows(_transcript(23 * 60))

    assert [(w["start"], w["end"]) for w in windows] == [(0, 720), (600, 1380)]


def test_windowing_handles_three_digit_minutes():
    windows = ai.split_transcript_into_windows(_transcript(110 * 60))

    assert windows[-1]["end"] == 110 * 60
    assert windows[-1]["transcript"].splitlines()[-1].startswith("[109:50 - 110:00]")


def test_three_digit_minute_lines_are_parsed_and_grounded():
    transcript = "\n".join([
        "[100:00 - 100:20] Speaker A: First long sentence past the hundred minute mark.",
        "[100:20 - 100:40] Speaker A: Second sentence with the payoff.",
    ])

    lines = ai._parse_transcript_lines(transcript)
    spans = ai._parse_transcript_spans(transcript)

    assert lines[0]["start_seconds"] == 6000 and lines[1]["end_seconds"] == 6040
    assert spans[1]["end"] == 6040
    assert ai._extract_transcript_text_for_segment(lines, "100:00", "100:40") == (
        "First long sentence past the hundred minute mark. Second sentence with the payoff."
    )


def test_validation_snaps_near_miss_timestamps_instead_of_dropping():
    transcript = _transcript(120)
    lines = ai._parse_transcript_lines(transcript)
    spans = ai._parse_transcript_spans(transcript)
    segment = _segment("00:12", "00:47")

    validated = ai._validate_segments([segment], lines, spans)

    assert len(validated) == 1
    assert (validated[0].start_time, validated[0].end_time) == ("00:10", "00:50")
    assert validated[0].text.startswith("Line at 10 seconds")


def test_validation_still_drops_timestamps_far_from_any_line():
    lines = [
        {"start_time": "00:00", "end_time": "00:40", "start_seconds": 0, "end_seconds": 40, "text": "a b c"},
        {"start_time": "00:40", "end_time": "01:20", "start_seconds": 40, "end_seconds": 80, "text": "d e f"},
    ]

    assert ai._snap_bounds_to_transcript_lines(lines, 20, 60) is None


def test_repaired_bounds_past_an_hour_snap_back_to_transcript_labels():
    transcript = _transcript(70 * 60)
    lines = ai._parse_transcript_lines(transcript)
    spans = ai._parse_transcript_spans(transcript)
    # 2 minutes is too long; repair trims it and must keep MM:SS labels.
    segment = _segment("65:00", "67:00")

    validated = ai._validate_segments([segment], lines, spans)

    assert len(validated) == 1
    assert validated[0].start_time == "65:00"
    assert ai._parse_transcript_timestamp_seconds(validated[0].end_time) <= 65 * 60 + 90
    assert ":" in validated[0].end_time and validated[0].end_time.count(":") == 1


def test_dedupe_keeps_higher_scored_of_overlapping_candidates():
    weaker = _segment("01:00", "01:40", total=60)
    stronger = _segment("01:10", "01:50", total=80)
    separate = _segment("05:00", "05:40", total=50)

    kept = ai.dedupe_overlapping_segments([weaker, separate, stronger])

    assert kept == [stronger, separate]


def test_dedupe_drops_back_to_back_neighbours_but_keeps_separate_moments():
    first = _segment("01:00", "01:40", total=70)
    touching = _segment("01:30", "02:10", total=60)  # overlaps a little
    right_after = _segment("01:50", "02:30", total=65)  # 10 s gap: same moment
    later = _segment("03:00", "03:40", total=50)  # 80 s gap: a different moment

    assert ai.dedupe_overlapping_segments([first, touching, right_after, later]) == [first, later]


def test_drop_weak_candidates_keeps_strong_ones_and_a_minimum():
    ranked = [_segment(f"0{i}:00", f"0{i}:40", total=t) for i, t in enumerate([90, 70, 55, 45, 30])]
    assert [s.virality.total_score for s in ai.drop_weak_candidates(ranked)] == [90, 70, 55]
    weak = [_segment(f"0{i}:00", f"0{i}:40", total=t) for i, t in enumerate([60, 40, 35, 20])]
    assert [s.virality.total_score for s in ai.drop_weak_candidates(weak)] == [60, 40, 35]


def test_rerank_prompt_lists_crowd_signals_inside_each_candidate():
    candidates = [_segment("01:00", "01:40", 70), _segment("05:00", "05:40", 60)]
    signals = "\n".join([
        "Deterministic clip-worthiness signals to consider before ranking:",
        "- [01:20 - 01:30] score=4.0: Twitch chat exploded here (viewers reacted to this moment)",
        "- [01:35 - 01:38] score=3.0: loud spike: shouting, laughing or something loud on screen",
        "- [01:10 - 01:12] score=2.0: trigger phrase; what is that",
        "- [09:00 - 09:10] score=4.0: Twitch chat exploded here (viewers reacted to this moment)",
    ])

    prompt = ai.build_candidate_rerank_prompt(candidates, signals)
    first, second = prompt.split("candidate_id: 1")

    assert "Twitch chat exploded here" in first and "loud spike" in first
    assert "trigger phrase" not in first
    assert "signals: none" in second


def test_apply_ranking_takes_improved_titles():
    candidates = [_segment("00:00", "00:30", 90), _segment("01:00", "01:30", 80)]
    candidates[0].hook_title = "Old title"
    candidates[1].hook_title = "Keep me"
    ranking = ai.CandidateRanking(ranking=[
        ai.RankedCandidate(candidate_id=0, score=90, hook_title='"He did NOT see that coming" #fyp'),
        ai.RankedCandidate(candidate_id=1, score=70, hook_title=None),
    ])

    reranked = ai.apply_candidate_ranking(candidates, ranking)

    assert [s.hook_title for s in reranked] == ["He did NOT see that coming", "Keep me"]


def test_apply_ranking_reorders_and_calibrates_scores():
    candidates = [_segment("00:00", "00:30", 90), _segment("01:00", "01:30", 80), _segment("02:00", "02:30", 70)]
    ranking = ai.CandidateRanking(ranking=[
        ai.RankedCandidate(candidate_id=2, score=88),
        ai.RankedCandidate(candidate_id=0, score=91),  # clamped to keep order monotonic
        ai.RankedCandidate(candidate_id=7, score=50),  # unknown id ignored
    ])

    reranked = ai.apply_candidate_ranking(candidates, ranking)

    assert [s.start_time for s in reranked] == ["02:00", "00:00", "01:00"]
    assert [s.virality.total_score for s in reranked] == [88, 88, 80]
    for segment in reranked:
        virality = segment.virality
        assert virality.total_score == (
            virality.hook_score + virality.engagement_score
            + virality.value_score + virality.shareability_score
        )
        assert all(0 <= score <= 25 for score in (
            virality.hook_score, virality.engagement_score,
            virality.value_score, virality.shareability_score,
        ))


async def test_rerank_failure_keeps_first_pass_order(monkeypatch):
    candidates = [_segment("00:00", "00:30", 90), _segment("01:00", "01:30", 80)]
    agent = SimpleNamespace(run=AsyncMock(side_effect=ValueError("bad output")))
    monkeypatch.setattr(ai, "get_rerank_agent", lambda: agent)

    result = await ai.rerank_candidates(candidates)

    assert result == candidates
    assert [s.virality.total_score for s in result] == [90, 80]


async def test_long_transcript_runs_windows_then_reranks(monkeypatch):
    transcript = _transcript(30 * 60)

    def window_analysis(prompt: str):
        # Each window returns a clip at its own start plus one shared moment
        # inside the first overlap, which must be deduplicated.
        start = 600 if "[10:00 - 10:10]" in prompt.split("Transcript:")[1].splitlines()[1] else 0
        if "[20:00 - 20:10]" in prompt.split("Transcript:")[1].splitlines()[1]:
            start = 1200
        segments = [_segment(_label(start + 30), _label(start + 60), total=60 + start // 60)]
        if start in (0, 600):
            segments.append(_segment("10:30", "11:00", total=40))
        return SimpleNamespace(output=ai.TranscriptAnalysis(
            most_relevant_segments=segments, summary=f"Window {start}.", key_topics=["topic", f"t{start}"],
        ))

    agent = SimpleNamespace(run=AsyncMock(side_effect=window_analysis))
    rerank_agent = SimpleNamespace(run=AsyncMock(side_effect=lambda prompt: SimpleNamespace(
        output=ai.CandidateRanking(ranking=[
            ai.RankedCandidate(candidate_id=i, score=90 - i) for i in reversed(range(prompt.count("candidate_id:")))
        ])
    )))
    monkeypatch.setattr(ai, "get_transcript_agent", lambda: agent)
    monkeypatch.setattr(ai, "get_rerank_agent", lambda: rerank_agent)

    result = await ai.get_most_relevant_parts_by_transcript(transcript)

    assert agent.run.await_count == 3
    prompts = [call.args[0] for call in agent.run.await_args_list]
    assert all("one window" in prompt and "Choose 0-4 segments total." in prompt for prompt in prompts)
    rerank_agent.run.assert_awaited_once()
    starts = [s.start_time for s in result.most_relevant_segments]
    assert sorted(starts) == ["00:30", "10:30", "20:30"]
    assert len(starts) == len(set(starts))
    assert result.key_topics == ["topic", "t0", "t600", "t1200"]
    scores = [s.virality.total_score for s in result.most_relevant_segments]
    assert scores == sorted(scores, reverse=True)


async def test_window_failures_are_tolerated_when_another_window_succeeds(monkeypatch):
    transcript = _transcript(30 * 60)
    calls = {"count": 0}

    async def flaky(prompt: str):
        calls["count"] += 1
        if "[00:00 - 00:10]" not in prompt:
            raise ValueError("schema failure")
        return SimpleNamespace(output=ai.TranscriptAnalysis(
            most_relevant_segments=[_segment("00:30", "01:00")], summary="ok", key_topics=[],
        ))

    monkeypatch.setattr(ai, "get_transcript_agent", lambda: SimpleNamespace(run=AsyncMock(side_effect=flaky)))
    monkeypatch.setattr(ai, "get_rerank_agent", lambda: (_ for _ in ()).throw(RuntimeError("no key")))

    result = await ai.get_most_relevant_parts_by_transcript(transcript)

    assert calls["count"] == 3
    assert [s.start_time for s in result.most_relevant_segments] == ["00:30"]


def test_window_signals_only_include_lines_inside_the_window():
    signals = "\n".join([
        "Deterministic clip-worthiness signals to consider before ranking:",
        "- [00:30 - 00:40] score=2.0: trigger phrase; Wait what",
        "- [15:00 - 15:10] score=1.5: question/hook; Why?",
        "- [101:00 - 101:10] score=1.0: pause before line; Late",
    ])

    early = ai._filter_clip_signals_for_window(signals, 0, 720)
    late = ai._filter_clip_signals_for_window(signals, 6000, 6720)

    assert early.splitlines() == [signals.splitlines()[0], signals.splitlines()[1]]
    assert late.splitlines()[-1].startswith("- [101:00")
    assert ai._filter_clip_signals_for_window(signals, 1000, 1100) is None


async def test_hook_times_survive_windowing_snapping_and_rerank(monkeypatch):
    transcript = _transcript(30 * 60)

    def window_analysis(prompt: str):
        first_line = prompt.split("Transcript:")[1].splitlines()[1]
        if first_line.startswith("[00:00"):
            # Near-miss bounds snap to 00:30-01:00; the hook stays inside.
            segment = _segment("00:31", "00:58", total=60)
            segment.hook_start_time, segment.hook_end_time = "00:45", "00:49"
        elif first_line.startswith("[10:00"):
            # The hook falls outside the final span, so it must be cleared.
            segment = _segment("12:00", "12:30", total=70)
            segment.hook_start_time, segment.hook_end_time = "12:40", "12:44"
        else:
            segment = _segment("20:30", "21:00", total=80)
            segment.hook_start_time, segment.hook_end_time = "20:50", "20:54"
        return SimpleNamespace(output=ai.TranscriptAnalysis(
            most_relevant_segments=[segment], summary="s", key_topics=[],
        ))

    rerank_agent = SimpleNamespace(run=AsyncMock(return_value=SimpleNamespace(
        output=ai.CandidateRanking(ranking=[
            ai.RankedCandidate(candidate_id=2, score=95),
            ai.RankedCandidate(candidate_id=1, score=85),
            ai.RankedCandidate(candidate_id=0, score=75),
        ])
    )))
    agent = SimpleNamespace(run=AsyncMock(side_effect=window_analysis))
    monkeypatch.setattr(ai, "get_transcript_agent", lambda: agent)
    monkeypatch.setattr(ai, "get_rerank_agent", lambda: rerank_agent)

    result = await ai.get_most_relevant_parts_by_transcript(transcript)

    assert all("hook_start_time" in call.args[0] for call in agent.run.await_args_list)
    rerank_agent.run.assert_awaited_once()
    by_start = {s.start_time: s for s in result.most_relevant_segments}
    assert (by_start["00:30"].hook_start_time, by_start["00:30"].hook_end_time) == ("00:45", "00:49")
    assert (by_start["12:00"].hook_start_time, by_start["12:00"].hook_end_time) == (None, None)
    assert (by_start["20:30"].hook_start_time, by_start["20:30"].hook_end_time) == ("20:50", "20:54")



async def test_every_strong_candidate_is_kept_without_a_clip_cap(monkeypatch):
    def window_analysis(prompt: str):
        first = prompt.split("Transcript:")[1].splitlines()[1]
        minutes, seconds = first[1:6].split(":")
        start = int(minutes) * 60 + int(seconds)
        return SimpleNamespace(output=ai.TranscriptAnalysis(
            most_relevant_segments=[
                _segment(_label(start + offset), _label(start + offset + 30), total=80)
                for offset in (130, 230, 330, 430)
            ],
            summary="Window.", key_topics=["topic"],
        ))

    agent = SimpleNamespace(run=AsyncMock(side_effect=window_analysis))
    rerank_agent = SimpleNamespace(run=AsyncMock(side_effect=lambda prompt: SimpleNamespace(
        output=ai.CandidateRanking(ranking=[
            ai.RankedCandidate(candidate_id=i, score=80) for i in range(prompt.count("candidate_id:"))
        ])
    )))
    monkeypatch.setattr(ai, "get_transcript_agent", lambda: agent)
    monkeypatch.setattr(ai, "get_rerank_agent", lambda: rerank_agent)

    result = await ai.get_most_relevant_parts_by_transcript(_transcript(60 * 60))

    assert len(result.most_relevant_segments) == 24


def test_clip_that_always_gets_a_clip():
    from src.ai import TranscriptSegment, _parse_transcript_lines, add_requested_clips

    lines = _parse_transcript_lines(
        "[09:10 - 09:14] okay we push now\n"
        "[09:20 - 09:50] oh my god no way he just did that\n"
        "[10:00 - 10:03] chat clip that\n"
        "[10:04 - 10:06] clip it clip it\n"
        "[20:00 - 20:02] somebody clip that"
    )
    picked = TranscriptSegment(start_time="19:20", end_time="20:00", text="already picked by the AI")
    result = add_requested_clips([picked], lines)
    # 10:00 gets a forced clip from the line ~45 s back; the repeat at 10:04 and the
    # one the AI already covered at 20:00 do not add more.
    assert [(s.start_time, s.end_time) for s in result] == [("09:10", "10:03"), ("19:20", "20:00")]
    assert "no way he just did that" in result[0].text


def test_search_again_skips_ranges_already_clipped():
    kept = ai.drop_excluded_segments(
        [_segment("01:00", "01:40"), _segment("05:00", "05:40"), _segment("01:35", "02:10")],
        [(55, 100)],
    )
    # The repeat is dropped; a new moment that only brushes the old one stays.
    assert [(s.start_time, s.end_time) for s in kept] == [("05:00", "05:40"), ("01:35", "02:10")]

    prompt = ai.build_transcript_analysis_prompt(
        "[00:00 - 00:10] hi", window=(0, 600), exclude_ranges=[(55, 100), (5000, 5040)]
    )
    assert "00:55 - 01:40" in prompt and "23:20" not in prompt  # only this window's ranges
    assert "already clipped" not in ai.build_transcript_analysis_prompt("[00:00 - 00:10] hi")


def test_strong_signals_the_ai_skipped_become_candidates():
    transcript = _transcript(20 * 60, line_seconds=5)
    lines, spans = ai._parse_transcript_lines(transcript), ai._parse_transcript_spans(transcript)
    signals = "\n".join(
        [
            "Deterministic clip-worthiness signals to consider before ranking:",
            "- [05:00 - 05:10] score=4.0: Twitch chat exploded here (viewers reacted to this moment)",
            "- [12:00 - 12:04] score=4.0: laughing heard in the audio",
            "- [15:00 - 15:04] score=3.0: loud spike: shouting, laughing or something loud on screen",
            "- [18:00 - 18:04] score=4.0: laughing heard in the audio",
        ]
    )
    picked = _segment("17:40", "18:20", total=80)
    result = ai.add_signal_candidates([picked], signals, lines, spans)
    # Chat at 05:00 and the laugh at 12:00 get a clip with their lead-up; the loud spike
    # and the laugh the AI already covered do not.
    assert [(s.start_time, s.end_time) for s in result] == [
        ("17:40", "18:20"), ("04:35", "05:10"), ("11:35", "12:05"),
    ]
    assert result[2].reasoning == "Stream signal: laughing heard in the audio."


def test_a_long_moment_is_cut_down_to_its_parts():
    transcript = _transcript(10 * 60, line_seconds=5)
    lines, spans = ai._parse_transcript_lines(transcript), ai._parse_transcript_spans(transcript)
    parts = [("01:00", "01:31"), ("02:40", "03:00"), ("04:31", "05:00")]  # 01:31 / 04:31 snap to lines
    segment = _segment("01:00", "05:00", total=80, text="the whole long moment here")
    segment.keep = [ai.KeepPart(start_time=a, end_time=b) for a, b in parts]

    [kept] = ai._validate_segments([segment], lines, spans)

    assert (kept.start_time, kept.end_time) == ("01:00", "05:00")
    assert ai.keep_part_seconds(kept) == [[60, 90], [160, 180], [270, 300]]
    assert kept.text.startswith("Line at 60 seconds") and " … Line at 160 seconds" in kept.text
    assert "Line at 120 seconds" not in kept.text  # the cut middle is not in the clip
    assert "cut down to 80s" in ai.build_candidate_rerank_prompt([kept])


def test_cut_down_parts_over_the_limit_lose_the_middle_first():
    transcript = _transcript(10 * 60, line_seconds=5)
    lines, spans = ai._parse_transcript_lines(transcript), ai._parse_transcript_spans(transcript)
    segment = _segment("00:00", "04:30")
    segment.keep = [
        ai.KeepPart(start_time=a, end_time=b)
        for a, b in [("00:00", "00:30"), ("01:00", "01:30"), ("02:00", "02:30"), ("04:00", "04:30")]
    ]
    [kept] = ai._validate_segments([segment], lines, spans)
    # 120 s of parts: one middle part goes; the setup and the payoff stay.
    assert ai.keep_part_seconds(kept) == [[0, 30], [60, 90], [240, 270]]


def test_unusable_parts_fall_back_to_a_normal_clip():
    transcript = _transcript(10 * 60, line_seconds=5)
    lines, spans = ai._parse_transcript_lines(transcript), ai._parse_transcript_spans(transcript)
    segment = _segment("01:00", "02:00")
    segment.keep = [ai.KeepPart(start_time="01:00", end_time="01:40")]  # one part is not a cut
    [kept] = ai._validate_segments([segment], lines, spans)
    assert kept.keep == [] and (kept.start_time, kept.end_time) == ("01:00", "02:00")

    too_far = _segment("00:00", "07:00")
    too_far.keep = [ai.KeepPart(start_time="00:00", end_time="00:30"), ai.KeepPart(start_time="06:30", end_time="07:00")]
    [kept] = ai._validate_segments([too_far], lines, spans)  # over 5 minutes apart: trimmed instead
    assert kept.keep == [] and ai._segment_bounds_seconds(kept)[1] <= 90
