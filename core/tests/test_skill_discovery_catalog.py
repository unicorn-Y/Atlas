from pathlib import Path

import pytest

from atlas.skills.registry import SkillRegistry

pytestmark = pytest.mark.unit


def test_discovery_catalog_persists_digest_changes_and_retires_missing_skills(
    tmp_path: Path,
) -> None:
    database = tmp_path / "skills.db"
    skill_file = tmp_path / "alpha" / "SKILL.md"
    skill_file.parent.mkdir()
    skill_file.write_text("alpha v1", encoding="utf-8")
    skill = {"name": "alpha", "version": "1.0.0", "description": "Alpha", "path": str(skill_file)}

    registry = SkillRegistry(database)
    added = registry.reconcile_discovery_catalog([skill])
    unchanged = registry.reconcile_discovery_catalog([skill])
    skill_file.write_text("alpha v2", encoding="utf-8")
    updated = registry.reconcile_discovery_catalog([skill])
    retired = registry.reconcile_discovery_catalog([])

    assert added == {"added": ["alpha"], "updated": [], "retired": [], "unchanged": []}
    assert unchanged == {"added": [], "updated": [], "retired": [], "unchanged": ["alpha"]}
    assert updated == {"added": [], "updated": ["alpha"], "retired": [], "unchanged": []}
    assert retired == {"added": [], "updated": [], "retired": ["alpha"], "unchanged": []}
    assert SkillRegistry(database).discovery_catalog()[0]["status"] == "retired"
