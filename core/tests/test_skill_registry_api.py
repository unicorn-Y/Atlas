"""API contract tests for the descriptive Skill Registry."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from atlas import server
from atlas.server import app
from atlas.skills import SkillManager
from atlas.skills.registry import SkillRegistry


@pytest.mark.asyncio
async def test_registry_api_registers_queries_disables_and_removes(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(server, "skill_registry", SkillRegistry(tmp_path / "skills.db"))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        metadata = {
            "name": "research",
            "version": "1.0.0",
            "description": "Find scientific papers",
            "capabilities": ["paper-search"],
            "tools": ["arxiv"],
            "requirements": ["network"],
            "examples": ["Find papers about agents"],
        }
        created = await client.post("/api/skill-registry", json=metadata)
        assert created.status_code == 200
        assert created.json()["status"] == "active"

        listed = await client.get("/api/skill-registry")
        assert listed.json()["count"] == 1
        found = await client.get("/api/skill-registry/research/1.0.0")
        assert found.json()["name"] == "research"
        status = await client.get("/api/skill-registry/research/1.0.0/status")
        assert status.json() == {
            "name": "research", "version": "1.0.0", "status": "active",
        }
        searched = await client.get("/api/skill-registry/search", params={"q": "arxiv"})
        assert [item["name"] for item in searched.json()["skills"]] == ["research"]
        disabled = await client.post("/api/skill-registry/research/1.0.0/disable")
        assert disabled.json()["status"] == "disabled"
        removed = await client.delete("/api/skill-registry/research/1.0.0")
        assert removed.status_code == 204


@pytest.mark.asyncio
async def test_registry_api_rejects_invalid_or_secret_metadata(tmp_path, monkeypatch) -> None:
    registry = SkillRegistry(tmp_path / "skills.db")
    monkeypatch.setattr(server, "skill_registry", registry)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/skill-registry", json={
            "name": "unsafe",
            "version": "1.0.0",
            "description": "Never persist credentials",
            "requirements": {"api_key": "must-not-be-stored"},
        })
    assert response.status_code == 422
    assert registry.list() == []


@pytest.mark.asyncio
async def test_existing_skill_api_contract_remains_available(tmp_path, monkeypatch) -> None:
    skill_file = tmp_path / "research" / "papers" / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text(
        '---\nname: papers\ndescription: "Search scientific papers"\nversion: 1.0.0\n---\n',
        encoding="utf-8",
    )
    manager = SkillManager(skills_dir=tmp_path)
    manager.scan_skills_sync()
    monkeypatch.setattr(server, "skill_mgr", manager)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        listing = await client.get("/api/skills")
        single = await client.get("/api/skills/papers")
        search = await client.get("/api/skills/search/paper")

    assert listing.status_code == 200
    assert listing.json()["skills"][0]["name"] == "papers"
    assert single.json()["version"] == "1.0.0"
    assert search.json()["skills"][0]["name"] == "papers"
