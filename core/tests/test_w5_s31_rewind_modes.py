"""W5 S31 — regression: the conversations router's three-mode rewind.

DSH has no rewind at all (``rewind`` is only a type literal in
``conversation-context.ts:6``); Atlas is PRESENT-STRONGER with a three-mode
point rewind (``code`` / ``conversation`` / ``both``), preview, redo and file
restore. The legacy ``message_id``+``files`` mode was already covered by
``test_backend_parity_wave5.py``; this file pins the point-based modes through
the router functions themselves.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
@pytest.mark.parametrize("mode, expect_restored, expect_removed", [
    ("conversation", [], 2),
    ("code", ["result.txt"], 0),
    ("both", ["result.txt"], 2),
])
async def test_s31_point_rewind_modes(tmp_path, monkeypatch, mode, expect_restored, expect_removed):
    from atlas import server
    from atlas.agent.checkpoints import ShadowGitCheckpointStore
    from atlas.config import DATA_ROOT as _unused_data_root
    from atlas.memory import MemoryStore
    from atlas.rewind import RewindManager

    data_root = tmp_path / "atlas-data"
    (data_root / "engine").mkdir(parents=True)
    monkeypatch.setattr("atlas.config.DATA_ROOT", data_root)

    memory = MemoryStore(tmp_path / "memory.sqlite3")
    await memory.init()
    store = ShadowGitCheckpointStore(tmp_path / "checkpoints")
    manager = RewindManager(store=store)
    monkeypatch.setattr("atlas.rewind._default_manager", manager)
    monkeypatch.setattr(server.runtime_mgr, "runs", {})

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "result.txt"
    target.write_text("before", encoding="utf-8")
    conversation_id = await memory.create_conversation("rewind-modes")

    from tests.fakes.session_store import save_memory_fixture_message

    first = await save_memory_fixture_message(memory, conversation_id, "user", "first")
    first_answer = await save_memory_fixture_message(
        memory, conversation_id, "assistant", "first done")
    # The pre-turn checkpoint binds the conversation to the boundary after turn 1.
    point_id = manager.checkpoint_before_turn(
        conversation_id, "turn-2", str(workspace),
        after_message_id=first_answer,
    )
    await save_memory_fixture_message(memory, conversation_id, "user", "second")
    await save_memory_fixture_message(memory, conversation_id, "assistant", "second done")
    target.write_text("round two", encoding="utf-8")

    from atlas.api.conversations_router import rewind_conversation
    from atlas.engine.session_sync import read_session_all_messages

    try:
        result = await rewind_conversation(
            SimpleNamespace(memory=memory),
            conversation_id,
            {"mode": mode, "point_id": point_id},
        )
        assert result["point_id"] == point_id
        assert sorted(result["restored_files"]) == sorted(expect_restored)
        assert result["removed_messages"] == expect_removed

        messages = read_session_all_messages(data_root / "engine", conversation_id)
        if mode in ("conversation", "both"):
            assert [item["content"] for item in messages] == ["first", "first done"]
        else:
            assert [item["content"] for item in messages] == [
                "first", "first done", "second", "second done",
            ]
        if mode in ("code", "both"):
            assert target.read_text(encoding="utf-8") == "before"
        else:
            assert target.read_text(encoding="utf-8") == "round two"
    finally:
        await memory.close()


@pytest.mark.asyncio
async def test_s31_rewind_rejects_unknown_mode(tmp_path):
    from atlas.memory import MemoryStore

    memory = MemoryStore(tmp_path / "memory.sqlite3")
    await memory.init()
    conversation_id = await memory.create_conversation("rewind-modes")
    from fastapi import HTTPException

    from atlas.api.conversations_router import rewind_conversation
    try:
        with pytest.raises(HTTPException) as excinfo:
            await rewind_conversation(
                SimpleNamespace(memory=memory),
                conversation_id,
                {"mode": "everything", "point_id": "point-1"},
            )
        assert "mode" in str(excinfo.value.detail)
    finally:
        await memory.close()


@pytest.mark.asyncio
async def test_s31_redo_after_point_rewind_restores_messages(tmp_path, monkeypatch):
    from atlas import server
    from atlas.agent.checkpoints import ShadowGitCheckpointStore
    from atlas.memory import MemoryStore
    from atlas.rewind import RewindManager

    data_root = tmp_path / "atlas-data"
    (data_root / "engine").mkdir(parents=True)
    monkeypatch.setattr("atlas.config.DATA_ROOT", data_root)

    memory = MemoryStore(tmp_path / "memory.sqlite3")
    await memory.init()
    manager = RewindManager(store=ShadowGitCheckpointStore(tmp_path / "checkpoints"))
    monkeypatch.setattr("atlas.rewind._default_manager", manager)
    monkeypatch.setattr(server.runtime_mgr, "runs", {})

    conversation_id = await memory.create_conversation("rewind-redo")
    from tests.fakes.session_store import save_memory_fixture_message

    await save_memory_fixture_message(memory, conversation_id, "user", "first")
    first_answer = await save_memory_fixture_message(
        memory, conversation_id, "assistant", "first done")
    point_id = manager.checkpoint_before_turn(
        conversation_id, "turn-2", str(tmp_path), after_message_id=first_answer,
    )
    await save_memory_fixture_message(memory, conversation_id, "user", "second")
    await save_memory_fixture_message(memory, conversation_id, "assistant", "second done")

    from atlas.api.conversations_router import (
        list_conversation_rewinds, redo_conversation_rewind, rewind_conversation,
    )
    from atlas.engine.session_sync import read_session_all_messages

    try:
        result = await rewind_conversation(
            SimpleNamespace(memory=memory), conversation_id,
            {"mode": "conversation", "point_id": point_id},
        )
        assert [item["content"] for item in
                read_session_all_messages(data_root / "engine", conversation_id)] == [
            "first", "first done",
        ]
        await redo_conversation_rewind(
            SimpleNamespace(memory=memory), conversation_id, result["rewind_id"],
        )
        assert [item["content"] for item in
                read_session_all_messages(data_root / "engine", conversation_id)] == [
            "first", "first done", "second", "second done",
        ]
        listed = await list_conversation_rewinds(SimpleNamespace(memory=memory), conversation_id)
        assert listed and listed[0]["redone"] is True
    finally:
        await memory.close()
