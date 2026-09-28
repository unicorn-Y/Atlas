"""ProjectStore coverage for the long-lived personal agent wave."""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas.memory import MemoryStore
from atlas.projects import ProjectStore


@pytest.fixture
async def store(tmp_path: Path) -> ProjectStore:
    store = ProjectStore(tmp_path / "projects.db")
    await store.init()
    yield store
    await store.close()


async def test_create_get_and_duplicate_name(store: ProjectStore) -> None:
    project = await store.create_project(
        "Atlas", workspace_path="D:/Atlas", current_goal="become a real agent",
    )
    assert project.name == "Atlas"
    assert project.status == "active"
    assert project.current_goal == "become a real agent"

    fetched = await store.get(project.project_id)
    assert fetched is not None and fetched.name == "Atlas"
    assert await store.get_by_name("atlas") is not None

    with pytest.raises(ValueError, match="already exists"):
        await store.create_project("Atlas")


async def test_update_goal_state_and_status_transitions(store: ProjectStore) -> None:
    project = await store.create_project("Voice")
    updated = await store.update_project(
        project.project_id,
        current_goal="ship realtime voice",
        current_state="pipeline designed; pipecat pending",
    )
    assert updated is not None
    assert updated.current_goal == "ship realtime voice"
    assert "pipecat" in updated.current_state

    with pytest.raises(ValueError, match="invalid project status"):
        await store.update_project(project.project_id, status="bogus")

    archived = await store.archive(project.project_id)
    assert archived is not None and archived.status == "archived"
    active = await store.list_projects(status="active")
    assert all(p.project_id != project.project_id for p in active)


async def test_conversation_association_and_detach(store: ProjectStore) -> None:
    project = await store.create_project("Atlas")
    await store.attach_conversation(project.project_id, "conv-1")
    await store.attach_conversation(project.project_id, "conv-2")
    await store.attach_conversation(project.project_id, "conv-1")  # idempotent

    assert await store.list_conversations(project.project_id) == ["conv-1", "conv-2"]

    with pytest.raises(ValueError, match="unknown project"):
        await store.attach_conversation("missing", "conv-1")

    assert await store.detach_conversation(project.project_id, "conv-1") is True
    assert await store.detach_conversation(project.project_id, "conv-1") is False
    assert await store.list_conversations(project.project_id) == ["conv-2"]


async def test_delete_project_removes_associations(store: ProjectStore) -> None:
    project = await store.create_project("Temp")
    await store.attach_conversation(project.project_id, "conv-9")
    assert await store.delete_project(project.project_id) is True
    assert await store.get(project.project_id) is None
    assert await store.list_conversations(project.project_id) == []


async def test_session_search_scopes_to_project_conversations(
    store: ProjectStore, tmp_path: Path,
) -> None:
    memory = MemoryStore(db_path=tmp_path / "memory.db")
    await memory.init()
    try:
        project = await store.create_project("Atlas")
        inside = await memory.create_conversation("Atlas work")
        await memory.save_message(inside, "user", "the hybrid router needs a fallback")
        outside = await memory.create_conversation("Random")
        await memory.save_message(outside, "user", "hybrid cookies recipe")
        await store.attach_conversation(project.project_id, inside)

        unscoped = await memory.session_search("hybrid")
        assert len(unscoped) == 2

        scoped = await memory.session_search(
            "hybrid", conversation_ids=await store.list_conversations(project.project_id),
        )
        assert len(scoped) == 1
        assert scoped[0]["conversation_title"] == "Atlas work"
    finally:
        await memory.close()
