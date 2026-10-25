from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from atlas.api.app_services import AppServices
from atlas.api.projects_router import get_project_settings, put_project_settings
from atlas.projects import ProjectStore


class FakeSkillManager:
    def __init__(self, names: set[str]):
        self.names = names

    def get_skill(self, name: str):
        return {"name": name} if name in self.names else None


@pytest.fixture
async def project_services(tmp_path: Path, monkeypatch):
    from atlas import server
    from atlas import project_settings

    store = ProjectStore(tmp_path / "projects.db")
    await store.init()
    monkeypatch.setattr(server, "projects", store)
    monkeypatch.setattr(server, "skill_mgr", FakeSkillManager({"release-notes", "repo-map"}))
    monkeypatch.setattr(project_settings, "_PATH", tmp_path / "project-settings.json")
    project = await store.create_project("Skills project")
    yield AppServices(projects=store), project.project_id
    await store.close()


async def test_project_skills_persist_and_validate(project_services):
    services, project_id = project_services
    updated = await put_project_settings(services, project_id, {
        "active_skills": ["release-notes", "repo-map", "release-notes"],
    })
    assert updated["config"]["active_skills"] == ["release-notes", "repo-map"]
    fetched = await get_project_settings(services, project_id)
    assert fetched["config"]["active_skills"] == ["release-notes", "repo-map"]

    with pytest.raises(HTTPException) as missing:
        await put_project_settings(services, project_id, {"active_skills": ["ghost"]})
    assert missing.value.status_code == 422

    with pytest.raises(HTTPException) as too_many:
        await put_project_settings(services, project_id, {
            "active_skills": [f"skill-{index}" for index in range(9)],
        })
    assert too_many.value.status_code == 422
