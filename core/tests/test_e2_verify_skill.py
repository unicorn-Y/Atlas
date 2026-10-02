"""E2 — the builtin ``verify`` skill follows the SKILL.md convention (CC 2.1.286)."""

from __future__ import annotations

from pathlib import Path

from atlas.skills import SKILLS_DIR, _frontmatter_to_skill_info, _parse_skill_md


def _load_verify_skill() -> tuple[Path, str]:
    path = SKILLS_DIR / "dev" / "verify" / "SKILL.md"
    assert path.is_file(), f"builtin verify skill missing at {path}"
    parsed = _parse_skill_md(path)
    assert parsed is not None, "verify SKILL.md must parse (frontmatter + body)"
    return path, parsed[1]


def test_verify_skill_has_required_frontmatter() -> None:
    path, _body = _load_verify_skill()
    fm, _fm_body = _parse_skill_md(path)
    info = _frontmatter_to_skill_info(fm, path, skills_dir=SKILLS_DIR)
    assert info is not None, "verify frontmatter must satisfy the skill contract"
    assert info.name == "verify"
    assert info.description.strip()
    assert info.category == "dev"
    assert info.version == "1.0.0"


def test_verify_skill_body_prescribes_the_verification_steps() -> None:
    _path, body = _load_verify_skill()
    # 1) focused tests for touched files, 2) typecheck, 3) explicit NOT-verified list.
    assert "pytest" in body
    assert "类型检查" in body
    assert "未验证" in body
    assert "commit" in body.lower()
