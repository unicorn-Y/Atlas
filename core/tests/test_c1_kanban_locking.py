import asyncio

import pytest

from atlas.kanban import KanbanStore, atlas_kanban_store
from atlas.memory import MemoryStore
from tests.test_c1_review_e2e import run_script
from tests.fakes.fake_llm_provider import Text, ToolCall


def test_atlas_kanban_store_migrates_existing_boards_to_its_own_database(tmp_path, monkeypatch):
    legacy = tmp_path / "atlas.db"
    original = KanbanStore(legacy)
    board = original.create_board("Existing board", "existing-board")
    original.create_task(board["id"], {"title": "Existing task", "id": "existing-task"})

    class FixtureConfig(dict):
        db_path = legacy

    monkeypatch.setattr("atlas.config.get_config", lambda: FixtureConfig())
    current = atlas_kanban_store()

    assert current.database == tmp_path / "kanban.db"
    assert current.boards() == original.boards()
    assert current.tasks("existing-board")[0]["id"] == "existing-task"


@pytest.mark.asyncio
async def test_kanban_tool_keeps_event_loop_live_while_shared_database_is_locked(tmp_path, monkeypatch):
    database = tmp_path / "store.db"
    memory = MemoryStore(db_path=database)
    await memory.init()
    class FixtureConfig(dict):
        db_path = database
        trajectory_reviewer_backend = ""
        trajectory_reviewer_model = ""
        trajectory_reviewer_enabled = False

    monkeypatch.setattr("atlas.config.get_config", lambda: FixtureConfig({
        "tools.servers": {}, "tools.auto_start": [], "agent.verify_before_stop": True,
    }))
    monkeypatch.setattr("atlas.agent.get_config", lambda: FixtureConfig({
        "tools.servers": {}, "tools.auto_start": [], "agent.verify_before_stop": True,
    }))
    kanban = atlas_kanban_store()

    original_connect = KanbanStore._connect

    def short_busy_timeout(store):
        connection = original_connect(store)
        connection.execute("PRAGMA busy_timeout=100")
        return connection

    monkeypatch.setattr(KanbanStore, "_connect", short_busy_timeout)
    await memory._db.execute("BEGIN IMMEDIATE")

    async def release_database_lock():
        await asyncio.sleep(0.03)
        await memory._db.commit()

    release = asyncio.create_task(release_database_lock())
    try:
        events, requests, _ = await run_script(tmp_path, monkeypatch, [
            ToolCall("tool_call", {"calls": [{
                "name": "kanban_create_board",
                "arguments": {"name": "Async board", "board_id": "async-board"},
            }]}),
            Text("board created"),
        ])
        await release
    finally:
        if not release.done():
            await memory._db.commit()
            await release
        await memory.close()

    assert any(board["id"] == "async-board" for board in kanban.boards()), {
        "database": str(kanban.database), "boards": kanban.boards(), "requests": requests,
    }
    tool_results = [
        str(item.get("content", "")) for request in requests
        for item in request["messages"] if item.get("role") == "tool"
    ]
    assert any("async-board" in content for content in tool_results)
    assert not any(
        "database is locked" in str(item.get("content", ""))
        for request in requests for item in request["messages"] if item.get("role") == "tool"
    )
