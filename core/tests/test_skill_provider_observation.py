"""Provider observations retry incomplete reads and accept explicit invalidation."""

from pathlib import Path

import pytest

import atlas.skills as skills

pytestmark = pytest.mark.unit


def _skill(root):
    path = root / "tools" / "demo" / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text("---\nname: demo\ndescription: Demo\n---\nBody", encoding="utf-8")
    return path


def test_provider_list_get_and_change_event(tmp_path, monkeypatch):
    _skill(tmp_path)
    manager = skills.SkillManager(tmp_path)
    assert [item.name for item in manager.list()] == ["demo"]
    assert manager.get("demo").description == "Demo"
    calls = []
    original = manager.scan_skills_sync

    def scan():
        calls.append(True)
        original()

    monkeypatch.setattr(manager, "scan_skills_sync", scan)
    assert manager.handle_change("other/change") is False
    assert manager.handle_change("skills/change") is True
    assert manager.get("demo") is not None
    assert len(calls) == 1


def test_incomplete_read_is_retried_even_with_identical_stat(tmp_path, monkeypatch):
    _skill(tmp_path)
    manager = skills.SkillManager(tmp_path)
    original = skills._parse_skill_md
    monkeypatch.setattr(skills, "_parse_skill_md", lambda path: None)
    assert manager.list() == []
    assert manager._scan_fingerprint is None
    monkeypatch.setattr(skills, "_parse_skill_md", original)
    assert manager.get("demo") is not None
    assert manager._scan_fingerprint is not None


def test_scan_error_preserves_previous_complete_observation(tmp_path, monkeypatch):
    _skill(tmp_path)
    manager = skills.SkillManager(tmp_path)
    manager.scan_skills_sync()

    def broken(self, pattern):
        raise PermissionError("temporarily unreadable source")

    monkeypatch.setattr(Path, "rglob", broken)
    manager.scan_skills_sync()
    assert manager._index["demo"].description == "Demo"
    assert manager._scan_fingerprint is None
