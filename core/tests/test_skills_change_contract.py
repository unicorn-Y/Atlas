"""skills/change invalidation and catalog revision (S27)."""

from pathlib import Path

import pytest

import atlas.skills as skills

pytestmark = pytest.mark.unit


def _category_skill(root: Path, name="demo", category="tools"):
    path = root / category / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nname: {name}\ndescription: Demo {name}\n---\nBody", encoding="utf-8")
    return path


def _flat_skill(root: Path, name="added"):
    path = root / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nname: {name}\ndescription: Demo {name}\n---\nBody", encoding="utf-8")
    return path


def test_source_registration_invalidates_a_complete_observation(tmp_path):
    skills_dir = tmp_path / "skills"
    _category_skill(skills_dir)
    manager = skills.SkillManager(skills_dir)
    assert [item.name for item in manager.list()] == ["demo"]
    assert manager._scan_fingerprint is not None

    extra = tmp_path / "extra-root"  # outside the atlas source tree
    _flat_skill(extra, "added")
    manager.register_skill_source(skills.SkillSource("extra", extra, 20, layout="flat"))
    assert manager._scan_fingerprint is None  # skills/change fired on provider-layer change

    names = [item.name for item in manager.list()]
    assert names == ["added", "demo"]  # next read rescans with the new source


def test_source_removal_invalidates_too(tmp_path):
    skills_dir = tmp_path / "skills"
    extra = tmp_path / "extra-root"  # outside the atlas source tree
    _flat_skill(extra, "added")
    manager = skills.SkillManager(skills_dir)
    manager.register_skill_source(skills.SkillSource("extra", extra, 20, layout="flat"))
    assert [item.name for item in manager.list()] == ["added"]
    manager.unregister_skill_source("extra")
    assert manager._scan_fingerprint is None
    assert [item.name for item in manager.list()] == []


def test_revision_bumps_only_on_complete_changed_scans(tmp_path):
    skills_dir = tmp_path / "skills"
    _category_skill(skills_dir)
    manager = skills.SkillManager(skills_dir)
    before = manager.revision
    manager.list()
    assert manager.revision == before + 1  # initial catalog is a change

    manager.list()
    assert manager.revision == before + 1  # unchanged complete scan does not bump

    _category_skill(skills_dir, "second")
    manager.list()
    assert manager.revision == before + 2  # new skill bumps once


def test_incomplete_scan_never_bumps_revision(tmp_path, monkeypatch):
    skills_dir = tmp_path / "skills"
    _category_skill(skills_dir)
    manager = skills.SkillManager(skills_dir)
    manager.scan_skills_sync()
    base = manager.revision
    monkeypatch.setattr(skills, "_parse_skill_md", lambda path: None)
    _category_skill(skills_dir, "unparseable")
    manager.scan_skills_sync()
    assert manager._scan_fingerprint is None  # observation incomplete: not cached as fresh
    assert manager.revision == base  # revision only advances on complete observations
