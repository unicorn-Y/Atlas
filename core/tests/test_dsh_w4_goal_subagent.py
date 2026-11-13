from __future__ import annotations

import pytest

from atlas.agent import AgentOrchestrator
from atlas.engine.session_sync import read_session_all_messages
from atlas.engine.state.atlas_state import SessionDB


@pytest.mark.asyncio
@pytest.mark.unit
async def test_native_subagent_forks_completed_parent_prefix_and_adds_persona(tmp_path, monkeypatch):
    home = tmp_path / "engine"
    parent_id = "parent-session"
    child_id = "child-session"
    with SessionDB(db_path=home / "state.db") as db:
        db.create_session(parent_id, "api_server")
        db.append_message(parent_id, "user", content="completed request")
        db.append_message(parent_id, "assistant", content="completed answer")
        db.append_message(parent_id, "user", content="active request")

    orchestrator = object.__new__(AgentOrchestrator)
    calls = []
    metadata_updates = []

    class FakeMemory:
        async def create_conversation(self, _title):
            return child_id

        async def update_conversation(self, conversation_id, **kwargs):
            metadata_updates.append((conversation_id, kwargs))
            return True

    async def fake_run(prompt, **kwargs):
        calls.append((prompt, kwargs))
        yield {"type": "chunk", "content": "child reply"}

    monkeypatch.setattr(orchestrator, "_memory", FakeMemory(), raising=False)
    monkeypatch.setattr(orchestrator, "run", fake_run)

    result = await orchestrator._run_atlas_subtask(
        goal="Inspect the task", context="Keep the answer focused", cwd=None,
        subtask_id="child-task",
        atlas_options={
            "parent_conversation_id": parent_id,
            "session_db_home": str(home),
            "persona": "Use concise, evidence-based language.",
        },
        on_progress=lambda _text: None,
    )

    assert result["result"] == "child reply"
    assert calls[0][1]["conversation_id"] == child_id
    assert "Use concise, evidence-based language." in calls[0][0]
    assert metadata_updates == [(child_id, {
        "parent_conversation_id": parent_id, "source": "subagent",
    })]
    inherited = read_session_all_messages(home, child_id)
    assert [(item["role"], item["content"]) for item in inherited] == [
        ("user", "completed request"), ("assistant", "completed answer"),
    ]
    with SessionDB(db_path=home / "state.db") as db:
        child = db.get_session(child_id)
        assert child["parent_session_id"] == parent_id
        assert db.get_session_model_config_value(child_id, "_delegate_from") == parent_id
