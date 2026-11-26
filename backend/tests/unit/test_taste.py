from types import SimpleNamespace

from src import ai, taste


def test_kept_and_deleted_clips_reach_the_rerank(monkeypatch, tmp_path):
    monkeypatch.setattr(taste, "get_config", lambda: SimpleNamespace(temp_dir=str(tmp_path)))
    funny = {"hook_title": "He jumped off the roof", "text": "watch this okay here we go"}
    assert taste.taste_note() == ""  # nothing known yet
    taste.remember("kept", funny)
    taste.remember("kept", {"hook_title": "Bank job goes wrong", "text": "the cops are here run"})
    taste.remember("deleted", {"hook_title": None, "text": "settings menu talk " * 20})
    note = taste.taste_note()
    assert '- "He jumped off the roof": watch this okay here we go' in note
    assert note.index("Bank job") < note.index("He jumped")  # newest first
    assert '- "untitled": settings menu talk' in note and len(note.split("Clips they deleted:")[1].split()) < 40

    taste.remember("deleted", funny)  # changed their mind
    assert note.count("He jumped") == 1 and taste.taste_note().split("Clips they deleted:")[1].count("He jumped") == 1
    assert "He jumped" not in taste.taste_note().split("Clips they deleted:")[0]

    prompt = ai.build_candidate_rerank_prompt([ai.TranscriptSegment(start_time="00:10", end_time="00:40", text="a b c")])
    assert "Bank job goes wrong" in prompt
