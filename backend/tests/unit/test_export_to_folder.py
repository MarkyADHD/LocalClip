from src.api.routes.post import EXPORT_ROOT, export_folder, export_name, safe_name


def test_names_are_safe_for_windows():
    assert safe_name('He said: "WHAT?" <no/way>...', "x") == "He said WHAT no way"
    assert safe_name(" .. ", "fallback") == "fallback"
    assert len(safe_name("a" * 300, "x")) == 80


def test_export_paths():
    assert export_name({"clip_order": 3, "hook_title": "1v4 clutch?!"}, "original") == "03 1v4 clutch !.mp4"
    assert export_name({"clip_order": 12, "hook_title": None}, "tiktok") == "12 clip (tiktok).mp4"
    assert export_folder({"id": "abcdef123456", "source_title": "Ranked: day 4"}) == EXPORT_ROOT / "Ranked day 4"
    assert export_folder({"id": "abcdef123456", "source_title": None}) == EXPORT_ROOT / "abcdef12"
