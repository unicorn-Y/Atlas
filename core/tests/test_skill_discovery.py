"""Ranking, filtering, API, and explicit Agent primitive tests for Discovery."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from atlas import server
from atlas.agent.capabilities import AgentCapabilityRegistry, register_skill_discovery_capability
from atlas.server import app
from atlas.skills.discovery import SkillDiscovery
from atlas.skills.registry import SkillRegistry


@pytest.fixture(autouse=True)
def clear_stale_app_skill_services(monkeypatch) -> None:
    """Keep global-singleton fallback tests independent of prior app lifespans."""
    services = getattr(server.app.state, "services", None)
    if services is not None:
        monkeypatch.setattr(services, "skill_mgr", None)
        monkeypatch.setattr(services, "skill_registry", None)


def _register(registry: SkillRegistry, name: str, **extra: object) -> dict[str, object]:
    metadata: dict[str, object] = {
        "name": name, "version": "1.0.0", "description": f"Find {name} information",
        "capabilities": ["research"], "tools": ["arxiv"], "requirements": ["python"],
        **extra,
    }
    return registry.register(metadata, source="local")


def test_discovery_ranks_explains_and_breaks_ties_deterministically(tmp_path) -> None:
    registry = SkillRegistry(tmp_path / "skills.db")
    _register(registry, "papers", aliases=["paper-search"], examples=["Search papers"])
    _register(registry, "research", aliases=["papers"])
    discovery = SkillDiscovery(registry)

    first = discovery.discover(query="papers")
    second = discovery.discover(query="papers")
    assert [item["name"] for item in first["results"]] == ["papers", "research"]
    assert [item["name"] for item in first["results"]] == [
        item["name"] for item in second["results"]
    ]
    assert first["results"][0]["relevance_score"] > first["results"][1]["relevance_score"]
    assert "name" in first["results"][0]["matched_fields"]
    assert first["results"][0]["match_reasons"]
    description = discovery.discover(query="information")["results"][0]
    assert "description" in description["matched_fields"]
    requirements = discovery.discover(query="python")["results"][0]
    assert "requirements" in requirements["matched_fields"]

    _register(registry, "zeta", aliases=["shared-term"])
    _register(registry, "alpha", aliases=["shared-term"])
    tied = discovery.discover(query="shared-term")["results"]
    assert [item["name"] for item in tied] == ["alpha", "zeta"]


def test_discovery_filters_active_capability_tool_source_and_pages(tmp_path) -> None:
    registry = SkillRegistry(tmp_path / "skills.db")
    _register(registry, "alpha", category="research", tags=["papers"])
    _register(registry, "beta", tools=["browser"])
    discovery = SkillDiscovery(registry)

    assert [
        item["name"] for item in discovery.discover(capability="research")["results"]
    ] == ["alpha", "beta"]
    assert [item["name"] for item in discovery.discover(tool="browser")["results"]] == ["beta"]
    assert [
        item["name"] for item in discovery.discover(source="local")["results"]
    ] == ["alpha", "beta"]
    page = discovery.discover(limit=1, offset=1)
    assert page["count"] == 2 and page["offset"] == 1 and page["results"][0]["name"] == "beta"


def test_disabled_records_are_excluded_by_default_and_legacy_metadata_reads(tmp_path) -> None:
    registry = SkillRegistry(tmp_path / "skills.db")
    legacy = registry.register({
        "name": "legacy", "version": "1.0.0", "description": "Old Registry record",
        "capabilities": [], "tools": [], "requirements": [], "examples": [],
    }, source="legacy-import")
    registry.disable("legacy", "1.0.0")
    discovery = SkillDiscovery(registry)
    assert legacy["source"] == "legacy-import"
    assert discovery.discover(query="legacy")["count"] == 0
    disabled = discovery.discover(query="legacy", status="disabled")["results"][0]
    assert disabled["status"] == "disabled" and disabled["source"] == "legacy-import"
    assert discovery.discover(query="legacy", status="all")["results"][0]["version"] == "1.0.0"


def test_metadata_extension_remains_secret_validated(tmp_path) -> None:
    registry = SkillRegistry(tmp_path / "skills.db")
    with pytest.raises(ValueError, match="must not contain credentials"):
        _register(registry, "unsafe", aliases=["api_key=example-value"])
    assert registry.list() == []


@pytest.mark.asyncio
async def test_discovery_api_and_agent_primitive_return_candidates_without_activation(
    tmp_path, monkeypatch,
) -> None:
    registry = SkillRegistry(tmp_path / "skills.db")
    _register(registry, "papers")
    monkeypatch.setattr(server, "skill_registry", registry)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/skills/discover", params={"q": "papers", "tool": "arxiv"})
        detail = await client.get("/api/skills/discover/papers", params={"version": "1.0.0"})
    assert response.status_code == 200
    record = response.json()["results"][0]
    assert record["name"] == "papers" and record["source"] == "local"
    assert record["matched_fields"] and record["match_reasons"]
    assert detail.status_code == 200 and detail.json()["version"] == "1.0.0"

    capabilities = AgentCapabilityRegistry()
    register_skill_discovery_capability(capabilities, registry)
    result = await capabilities.invoke("skill.discovery.search", {"task": "find papers"})
    assert result["results"][0]["name"] == "papers"
    assert registry.status("papers", "1.0.0") == "active"
