import json
from pathlib import Path
import re

from src.caption_templates import CAPTION_TEMPLATES
from src.editor_document import CaptionStyle

INSPECTOR = Path(__file__).parents[3] / "frontend/src/components/editor/inspector.tsx"


def test_generation_looks_match_the_editor_presets():
    source = INSPECTOR.read_text(encoding="utf-8")
    block = source[source.index("export const PRESETS") :].split("\n];", 1)[0]
    rows = re.findall(r'\["([^"]+)", (\{[^}]*\})\]', block)
    assert len(rows) >= 12
    for name, fields in rows:
        style = json.loads(re.sub(r"(\w+): ", r'"\1": ', fields))
        CaptionStyle.model_validate(style)
        assert CAPTION_TEMPLATES[name.lower()]["name"] == name
        assert CAPTION_TEMPLATES[name.lower()]["editor"] == style
