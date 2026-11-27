"""Authored visual nicknames for components used by the story seed."""

from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_CUES: dict[str, str] = {}
with (ROOT / "data/story-cue-candidates.tsv").open(encoding="utf-8", newline="") as stream:
    for row in csv.reader(stream, delimiter="\t"):
        if len(row) != 2 or not row[0] or not row[1] or row[0] in _CUES:
            raise ValueError("story-cue-candidates.tsv must contain unique glyph and nickname pairs")
        _CUES[row[0]] = row[1]


def component_label(form: str, authored_form: str, character: str, attributes: dict) -> str:
    """Return an authored visual cue; the exact glyph evidence is attached by the caller."""
    key = authored_form if authored_form in _CUES else form
    if form == "月" and attributes.get("original") == "肉" and character in {"胆", "肝", "肩"}:
        return "flesh"
    nickname = _CUES.get(key)
    if nickname is None:
        raise ValueError(f"no authored story cue for source form {form!r} (authored form {authored_form!r})")
    return nickname
