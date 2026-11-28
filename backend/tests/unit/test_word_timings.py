from src.media.transcription import tighten_word_timings


def test_stretched_words_keep_the_side_next_to_their_neighbour():
    words = [
        {"word": " Okay,", "start": 0.0, "end": 0.4},
        {"word": " we", "start": 0.4, "end": 5.2},  # said right after "Okay," then held over the pause
        {"word": " Where's", "start": 10.0, "end": 16.2},  # said right before "Nico?"
        {"word": " Nico?", "start": 16.2, "end": 16.6},
    ]
    tighten_word_timings(words)
    assert words[1] == {"word": " we", "start": 0.4, "end": 1.06}
    assert words[2]["start"] == 15.14 and words[2]["end"] == 16.2
    assert words[0]["end"] == 0.4 and words[3]["start"] == 16.2


def test_millisecond_cache_words():
    words = [{"text": " yeah", "start": 1000, "end": 9000}]
    assert tighten_word_timings(words, 1000) == [{"text": " yeah", "start": 1000, "end": 1820}]


def test_generated_caption_line_ends_at_a_pause(tmp_path):
    from src import video_utils

    ass_path = tmp_path / "captions.ass"
    words = [
        {"text": "okay", "start": 0.0, "end": 0.4},
        {"text": "we", "start": 0.4, "end": 0.7},
        {"text": "have", "start": 6.0, "end": 6.2},
        {"text": "to", "start": 6.2, "end": 6.4},
    ]
    assert video_utils.build_assemblyai_ass_subtitles(
        tmp_path / "source.mp4", clip_start=0.0, clip_end=7.0, video_width=1080, video_height=1920,
        output_ass_path=ass_path, caption_template="minimal", caption_words=words,
    )
    lines = [line for line in ass_path.read_text().splitlines() if line.startswith("Dialogue: 0,")]
    # "okay we" leaves the screen when "we" ends, not when "have" starts 5 s later.
    assert [line.split(",")[1:3] for line in lines] == [["0:00:00.00", "0:00:00.70"], ["0:00:06.00", "0:00:06.40"]]
