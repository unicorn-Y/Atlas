from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from atlas.agent import AgentOrchestrator
from atlas.engine.session_sync import capture_session
from atlas.memory import MemoryStore
from atlas.tools.local_execution import LocalExecutionRuntime
from tests.fakes.fake_llm_provider import FakeLLMServer, Text, write_hermes_home


class _Memory:
    def __init__(self):
        self.conversations = {}
        self.deleted = []

    async def create_conversation(self, title):
        conversation_id = f"child-{len(self.conversations) + 1}"
        self.conversations[conversation_id] = {"title": title}
        return conversation_id

    async def delete_conversation(self, conversation_id):
        self.deleted.append(conversation_id)
        self.conversations.pop(conversation_id, None)


@pytest.mark.asyncio
async def test_real_hermes_atlas_child_keeps_context_and_permissions_then_cleans_up(tmp_path, monkeypatch):
    class FixtureConfig(dict):
        db_path = tmp_path / "config.db"

    monkeypatch.setattr("atlas.config.get_config", lambda: FixtureConfig({
        "tools.servers": {}, "tools.auto_start": [],
        "agent.verify_before_stop": True,
    }))
    data_root = tmp_path / "atlas-data"
    monkeypatch.setattr("atlas.config.DATA_ROOT", data_root)
    monkeypatch.setenv("ATLAS_DATA_DIR", str(data_root))

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with FakeLLMServer([Text("real child result")]) as fake:
        home = data_root / "engine"
        write_hermes_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        model_rows = [{
            "id": "child-model", "litellm_model": "openai/child-model",
            "max_output_tokens": 256,
        }]
        models = SimpleNamespace(
            current_model="parent-model", current_litellm_model="openai/parent-model",
            gateway_base_url=fake.base_url, _api_key="sk-fake-e2e",
            list_models=lambda: model_rows,
        )
        memory = MemoryStore(db_path=tmp_path / "memory.sqlite3")
        await memory.init()
        local = LocalExecutionRuntime()
        parent = AgentOrchestrator(models, memory, local_execution=local)
        progress = []
        child_conversation = None
        try:
            result = await parent._run_atlas_subtask(
                goal="inspect the allowed fixture",
                context="Only use the explicitly provided context.",
                cwd=str(workspace), subtask_id="real-child-run",
                atlas_options={
                    "model": "child-model", "permission_mode": "read_only",
                    "allowed_paths": [str(workspace)], "tool_allow": ["read_file"],
                },
                on_progress=progress.append,
            )
            child_conversation = await memory.get_conversation("real-child-run")
        finally:
            await local.shutdown()
            await memory.close()

        child_requests = [request for request in fake.main_requests()
                          if request.get("model") == "child-model"]
        assert child_requests
        assert "inspect the allowed fixture" in str(child_requests[0]["messages"])
        assert "Only use the explicitly provided context." in str(child_requests[0]["messages"])
        assert result["status"] == "completed"
        assert "real child result" in result["result"]
        assert progress and "real child result" in "".join(progress)
        assert capture_session(home, "real-child-run") is None
        assert child_conversation is None


@pytest.mark.asyncio
async def test_atlas_child_lifecycle_isolated_and_sessiondb_is_cleaned(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "engine"))
    monkeypatch.setattr("atlas.config.DATA_ROOT", tmp_path)
    memory = _Memory()
    agent = AgentOrchestrator(
        SimpleNamespace(current_model="parent", list_models=lambda: [{"id": "parent"}]),
        memory,
    )
    lifecycle = []
    options = {
        "model": "child-model", "permission_mode": "read_only",
        "allowed_paths": [str(tmp_path / "workspace")],
        "tool_allow": ["read_file"],
        "subtask_started": lambda *args: lifecycle.append(("started", args)),
        "subtask_progress": lambda *args: lifecycle.append(("progress", args)),
        "subtask_completed": lambda *args: lifecycle.append(("completed", args)),
    }
    observed = {}

    async def fake_child_run(message, *, conversation_id, **kwargs):
        observed.update({"message": message, "conversation_id": conversation_id, **kwargs})
        from hermes_state import SessionDB

        with SessionDB(db_path=tmp_path / "engine" / "state.db") as db:
            db.ensure_session(conversation_id, source="atlas-child", model=kwargs.get("model"))
        kwargs["subtask_started"](kwargs["run_id"], message, "atlas")
        kwargs["subtask_progress"](kwargs["run_id"], "正在检查子任务输入。")
        yield {"type": "chunk", "content": "child progress"}
        kwargs["subtask_completed"](kwargs["run_id"], "completed", "child result", 1)
        yield {"type": "done"}

    agent.run = fake_child_run
    progress = []
    result = await agent._run_atlas_subtask(
        goal="inspect the fixture", context="explicit child context", cwd=str(tmp_path),
        subtask_id="subtask-1", atlas_options=options,
        on_progress=lambda text: progress.append(text),
    )

    child_id = observed["conversation_id"]
    assert child_id != "parent-conversation"
    assert "inspect the fixture" in observed["message"]
    assert "explicit child context" in observed["message"]
    assert observed["model"] == "child-model"
    assert observed["permission_mode"] == "read_only"
    assert observed["allowed_paths"] == [str(tmp_path / "workspace")]
    assert "delegate_task" in observed["tool_deny"]
    assert result["status"] == "completed" and result["result"] == "child progress"
    assert progress == ["child progress"]
    assert [item[0] for item in lifecycle] == ["started", "progress", "completed"]
    assert child_id in memory.deleted and child_id not in memory.conversations
    assert capture_session(tmp_path / "engine", child_id) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["cancelled", "failed"])
async def test_atlas_child_cancel_and_failure_both_remove_hermes_session(tmp_path, monkeypatch, outcome):
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "engine"))
    monkeypatch.setattr("atlas.config.DATA_ROOT", tmp_path)
    memory = _Memory()
    agent = AgentOrchestrator(
        SimpleNamespace(current_model="parent", list_models=lambda: [{"id": "parent"}]),
        memory,
    )
    cancel_event = asyncio.Event()

    async def fake_child_run(_message, *, conversation_id, **kwargs):
        from hermes_state import SessionDB

        with SessionDB(db_path=tmp_path / "engine" / "state.db") as db:
            db.ensure_session(conversation_id, source="atlas-child", model=kwargs.get("model"))
        if outcome == "cancelled":
            cancel_event.set()
            yield {"type": "cancelled"}
        else:
            yield {"type": "error", "detail": "fixture child error"}

    agent.run = fake_child_run
    options = {"cancel_event": cancel_event}
    if outcome == "failed":
        with pytest.raises(RuntimeError, match="fixture child error"):
            await agent._run_atlas_subtask(
                goal="fail fixture", context=None, cwd=str(tmp_path),
                subtask_id="subtask-failure", atlas_options=options,
                on_progress=lambda _text: None,
            )
    else:
        result = await agent._run_atlas_subtask(
            goal="cancel fixture", context=None, cwd=str(tmp_path),
            subtask_id="subtask-cancel", atlas_options=options,
            on_progress=lambda _text: None,
        )
        assert result["status"] == "cancelled"

    child_id = memory.deleted[-1]
    assert child_id not in memory.conversations
    assert capture_session(tmp_path / "engine", child_id) is None
