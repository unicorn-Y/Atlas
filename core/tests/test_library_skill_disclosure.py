from pathlib import Path
from types import SimpleNamespace

import pytest

from atlas.library import runtime
from atlas.skills.registry import SkillRegistry

pytestmark = pytest.mark.unit


class _Store:
    version = 1

    def catalog(self):
        return {}

    def assignment(self, _key):
        return None

    def category(self, _category):
        return None


class _Manager:
    def __init__(self, skill_file: Path) -> None:
        self.skill = SimpleNamespace(
            name="demo", version="1.0.0", path=str(skill_file), description="Demo skill",
            tags=[], category="dev", source="atlas", disable_model_invocation=False,
            user_invocable=True,
        )

    def list_skills(self):
        return [self.skill]


def test_skill_index_cache_tracks_skill_content_digest_and_durable_retirement(tmp_path: Path, monkeypatch) -> None:
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text("first body", encoding="utf-8")
    manager = _Manager(skill_file)
    runtime._SKILL_INDEX_CACHE.clear()
    registry_db = tmp_path / "registry.db"
    monkeypatch.setenv("ATLAS_SKILL_REGISTRY_DB", str(registry_db))
    runtime._DISCOVERY_REGISTRY = None
    runtime._DISCOVERY_REGISTRY_PATH = None
    monkeypatch.setattr(runtime, "get_store", lambda: _Store())
    monkeypatch.setattr(runtime, "_skill_usage_counts", lambda: {})

    runtime._skill_index(manager)
    first_signature = runtime._SKILL_INDEX_CACHE["sig"]
    assert SkillRegistry(registry_db).discovery_catalog()[0]["status"] == "active"
    skill_file.write_text("changed body", encoding="utf-8")
    runtime._skill_index(manager)

    assert runtime._SKILL_INDEX_CACHE["sig"] != first_signature
    manager.skill_list = []
    manager.list_skills = lambda: manager.skill_list
    runtime._skill_index(manager)
    assert SkillRegistry(registry_db).discovery_catalog()[0]["status"] == "retired"


def test_skill_index_message_uses_available_skills_block(tmp_path: Path, monkeypatch) -> None:
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text("body", encoding="utf-8")
    runtime._SKILL_INDEX_CACHE.clear()
    monkeypatch.setattr(runtime, "get_store", lambda: _Store())
    monkeypatch.setattr(runtime, "_skill_usage_counts", lambda: {})

    message = runtime.skill_index_message(_Manager(skill_file), "demo")

    assert message is not None
    assert "<available_skills revision=\"" in message
    assert "</available_skills>" in message
    assert "revision=\"" in message
    assert '"name": "demo"' in message


def test_model_disabled_skill_is_not_disclosed(tmp_path: Path, monkeypatch) -> None:
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text("body", encoding="utf-8")
    manager = _Manager(skill_file)
    manager.skill.disable_model_invocation = True
    runtime._SKILL_INDEX_CACHE.clear()
    monkeypatch.setattr(runtime, "get_store", lambda: _Store())
    monkeypatch.setattr(runtime, "_skill_usage_counts", lambda: {})

    assert runtime.skill_index_message(manager, "demo") is None
