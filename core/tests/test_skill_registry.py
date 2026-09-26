"""Tests for the persistent, descriptive Skill Registry."""

from __future__ import annotations

import pytest

from atlas.skills.registry import SkillRegistry


def _skill(name: str = "research", version: str = "1.0.0", **changes):
    metadata = {
        "name": name,
        "version": version,
        "description": "Find scientific papers",
        "capabilities": ["paper-search"],
        "tools": ["arxiv"],
        "requirements": ["network"],
        "examples": ["Find papers about agents"],
    }
    metadata.update(changes)
    return metadata


def test_registration_survives_restart_and_has_provenance(tmp_path):
    path = tmp_path / "registry.db"
    first = SkillRegistry(path)
    registered = first.register(_skill(), source="test")

    restarted = SkillRegistry(path)
    result = restarted.get("research", "1.0.0")
    assert result == registered
    assert result["source"] == "test"
    assert result["validation_status"] == "valid"
    assert result["status"] == "active"
    assert result["registered_at"] == result["updated_at"]


@pytest.mark.parametrize("metadata", [
    {"name": "research", "version": "1.0.0"},
    _skill(name="bad name"),
    _skill(version="not-semver"),
    _skill(capabilities="paper-search"),
    _skill(api_key="secret-value"),
    _skill(requirements=["api_key=secret-value"]),
])
def test_invalid_metadata_is_rejected_without_registry_pollution(tmp_path, metadata):
    registry = SkillRegistry(tmp_path / "registry.db")
    with pytest.raises(ValueError):
        registry.register(metadata)
    assert registry.list() == []


def test_duplicate_identity_updates_in_place_and_list_is_sorted(tmp_path):
    registry = SkillRegistry(tmp_path / "registry.db")
    registry.register(_skill("zeta"))
    registry.register(_skill("alpha"))
    updated = registry.register(_skill(description="Updated description"), source="refresh")

    assert [item["name"] for item in registry.list()] == ["alpha", "research", "zeta"]
    assert len([item for item in registry.list() if item["name"] == "research"]) == 1
    assert updated["description"] == "Updated description"
    assert updated["source"] == "refresh"


def test_search_matches_each_supported_field_in_stable_order(tmp_path):
    registry = SkillRegistry(tmp_path / "registry.db")
    registry.register(_skill("zeta", capabilities=["paper-search"]))
    registry.register(_skill("alpha", tools=["paper-search"]))
    registry.register(_skill("beta", description="Paper-search helper"))

    assert [item["name"] for item in registry.search("paper-search")] == [
        "alpha", "beta", "zeta",
    ]


def test_disable_and_remove_change_registry_state_only(tmp_path):
    registry = SkillRegistry(tmp_path / "registry.db")
    registry.register(_skill())
    disabled = registry.disable("research", "1.0.0")
    assert disabled["status"] == "disabled"
    assert registry.get("research", "1.0.0")["status"] == "disabled"
    assert registry.remove("research", "1.0.0") is True
    assert registry.get("research", "1.0.0") is None


async def test_registry_metadata_does_not_grant_agent_capability(tmp_path):
    from atlas.agent.capabilities import AgentCapabilityRegistry

    registry = SkillRegistry(tmp_path / "registry.db")
    capabilities = AgentCapabilityRegistry()
    registry.register(_skill(tools=["filesystem.delete"]))

    assert capabilities.discover() == []
    with pytest.raises(KeyError, match="research"):
        await capabilities.invoke("research")
