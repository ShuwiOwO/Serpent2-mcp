"""The bundled skill must stay identical in both locations."""

from __future__ import annotations

from pathlib import Path


def test_skill_copies_are_identical():
    root = Path(__file__).parents[1]
    portable = root / "skills" / "serpent2" / "SKILL.md"
    project = root / ".opencode" / "skill" / "serpent2" / "SKILL.md"
    assert portable.is_file(), "portable skill copy is missing"
    assert project.is_file(), "project skill copy is missing"
    assert portable.read_text(encoding="utf-8") == project.read_text(encoding="utf-8"), (
        "skills/serpent2/SKILL.md and .opencode/skill/serpent2/SKILL.md have diverged; "
        "copy the file instead of editing one of them"
    )
