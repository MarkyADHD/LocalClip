from src.post_captions import build_prompt, clean


def test_prompt_carries_title_tags_and_transcript():
    prompt = build_prompt({"hook_title": "He did WHAT", "hashtags": "valorant clutch", "text": " one v five "}, "Ranked grind")
    assert prompt == (
        "Stream title: Ranked grind\nOn-screen title: He did WHAT\n"
        "Suggested hashtags: #valorant #clutch\nTranscript:\none v five"
    )
    assert build_prompt({"text": "hi", "hashtags": []}) == "Transcript:\nhi"


def test_clean_keeps_whole_words_inside_the_site_limit():
    long_title = "word " * 30 + "#shorts"
    cleaned = clean("youtube", f'"{long_title}"')
    assert len(cleaned) <= 100 and cleaned.endswith("word")
    assert clean("instagram", "Line one?\n\n#a  #b") == "Line one?\n\n#a #b"
