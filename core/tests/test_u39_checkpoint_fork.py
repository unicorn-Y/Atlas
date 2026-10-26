"""Checkpoint fork acceptance: restore a historical workspace snapshot in an isolated copy."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import atlas.config
from atlas.agent.checkpoints import ShadowGitCheckpointStore
from atlas.api.app_services import AppServices
from atlas.api.conversations_router import router as conversations_router
from atlas.engine.session_sync import append_session_message, read_session_all_messages
from atlas.memory import MemoryStore


@pytest.mark.asyncio
async def test_checkpoint_fork_restores_files_and_keeps_source_unchanged(tmp_path, monkeypatch):
    data_root = tmp_path / "atlas-data"
    monkeypatch.setattr(atlas.config, "DATA_ROOT", data_root)
    memory = MemoryStore(data_root / "memory.db")
    await memory.init()
    conversation_id = await memory.create_conversation("checkpoint source")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_file = workspace / "state.txt"
    state_file.write_text("checkpoint state", encoding="utf-8")
    await memory.update_conversation(conversation_id, workspace=str(workspace))
    append_session_message(data_root / "engine", conversation_id, "user", "first turn")

    checkpoints = ShadowGitCheckpointStore(tmp_path / "checkpoints")
    checkpoint = checkpoints.create_checkpoint(
        workspace, ["state.txt"], run_id="run-before", conversation_id=conversation_id,
    )
    state_file.write_text("later source state", encoding="utf-8")

    app = FastAPI()
    app.state.services = AppServices(memory=memory, orchestrator=type("Orchestrator", (), {"checkpoints": checkpoints})())
    app.include_router(conversations_router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/conversations/{conversation_id}/fork-checkpoint",
            json={"checkpoint_id": checkpoint["id"]},
        )

    assert response.status_code == 201, response.text
    forked = response.json()
    fork_workspace = Path(forked["workspace"])
    assert forked["parent_conversation_id"] == conversation_id
    assert forked["fork_message_id"]
    assert (fork_workspace / "state.txt").read_text(encoding="utf-8") == "checkpoint state"
    assert state_file.read_text(encoding="utf-8") == "later source state"
    source_messages = read_session_all_messages(data_root / "engine", conversation_id)
    fork_messages = read_session_all_messages(data_root / "engine", forked["id"])
    assert [item["content"] for item in fork_messages] == [item["content"] for item in source_messages]
    await memory.close()
