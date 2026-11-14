from src.project_ai import Edit, add_proposal, read_proposals, remove_proposal, source_edits, transcript_text
from src.project_document import Clip, new_document

WORDS = [
    {"text": "hello", "start": 0.0, "end": 0.4},
    {"text": "there.", "start": 0.5, "end": 0.9},
    {"text": "um", "start": 2.0, "end": 2.2},
    {"text": "so", "start": 2.3, "end": 2.5},
    {"text": "anyway", "start": 4.0, "end": 4.5},
]


def document():
    doc = new_document()
    # Two pieces of one recording, back to back: 10-13 s of the source, then 20-23 s.
    doc.clips = [
        Clip(id="a", track="v1", asset="x", start=0, duration=3, offset=10),
        Clip(id="b", track="v1", asset="x", start=3, duration=3, offset=20),
        Clip(id="m", track="a1", asset="music", start=0, duration=6),
    ]
    return doc


def test_transcript_breaks_on_sentences_and_pauses():
    assert transcript_text(WORDS) == "[0.0-0.9] hello there.\n[2.0-2.5] um so\n[4.0-4.5] anyway"


def test_cut_lands_on_word_edges_in_each_source_piece():
    edits = source_edits(
        document(),
        WORDS,
        [
            Edit(kind="cut", start=1.9, end=4.6, note="filler"),
            Edit(kind="chapter", start=99, text="End"),
            Edit(kind="title", text="  A title "),
            Edit(kind="text", start=1, end=1.05, text="too short"),
            Edit(kind="description", text=""),
        ],
    )
    cut = edits[0]
    assert cut["text"] == "um so anyway" and cut["note"] == "filler"
    # 0.15 s of the pause before "um" goes too; the music on another track is left alone.
    assert cut["ranges"] == [
        {"asset": "x", "start": 11.85, "end": 13.0},
        {"asset": "x", "start": 20.0, "end": 21.65},
    ]
    assert edits[1:] == [{"kind": "chapter", "time": 6.0, "text": "End"}, {"kind": "title", "text": "A title"}]


def test_proposals_wait_in_the_project_folder(tmp_path):
    first = add_proposal(tmp_path, "one", [{"kind": "title", "text": "T"}], "mcp")
    add_proposal(tmp_path, "two", [], "mcp")
    remove_proposal(tmp_path, first["id"])
    assert [p["reply"] for p in read_proposals(tmp_path)] == ["two"]
