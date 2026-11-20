import json
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage

from atlas.agent import AgentOrchestrator, AgentRunContext
from atlas.tools.local_execution import LocalExecutionRuntime


class FixtureConfig(dict):
    def __init__(self, db_path):
        super().__init__({"agent.verify_before_stop": False})
        self.db_path = db_path
        self.local_execution_permission_mode = "full_access"
        self.trajectory_reviewer_enabled = False
        self.trajectory_reviewer_backend = ""
        self.trajectory_reviewer_model = ""


class CaptureExecution:
    def __init__(self, runtime):
        self.runtime = runtime
        self.calls = []

    def get_tools_for_llm(self):
        return self.runtime.get_tools_for_llm()

    async def call_tool(self, name, arguments, **kwargs):
        self.calls.append((name, dict(arguments)))
        return await self.runtime.call_tool(name, arguments, **kwargs)


def _agent(local_execution):
    models = SimpleNamespace(current_model="fake-model", current_litellm_model="fake-model")
    return AgentOrchestrator(
        models, MagicMock(), mcp_client=MagicMock(), local_execution=local_execution,
        trajectory_reviewer=SimpleNamespace(reviewer=None),
    )


def _state(name, arguments, workspace, working_directory=None):
    context = AgentRunContext(
        workspace=str(workspace), run_id="cwd-fixture", conversation_id="cwd-fixture",
        working_directory=str(working_directory) if working_directory is not None else None,
    )
    message = AIMessage(content="", tool_calls=[{
        "name": name, "args": arguments, "id": "cwd-tool-call", "type": "tool_call",
    }])
    return {
        "messages": [message], "pending_events": [], "tool_rounds": 0,
        "cancelled": False, "runtime": context,
    }


@pytest.mark.asyncio
async def test_direct_local_exec_defaults_to_isolated_workspace_for_pwd(tmp_path, monkeypatch):
    config = FixtureConfig(tmp_path / "atlas.db")
    monkeypatch.setattr("atlas.agent.get_config", lambda: config)
    monkeypatch.setattr("atlas.tools.local_execution.get_config", lambda: config)
    runtime = LocalExecutionRuntime()
    capture = CaptureExecution(runtime)
    agent = _agent(capture)
    try:
        result = await agent._execute_tools_node(_state("local_exec", {
            "executable": sys.executable,
            "args": ["-c", "import os; print(os.getcwd())"],
            "cwd": "",
        }, tmp_path))
    finally:
        await runtime.shutdown()

    assert capture.calls[0][1]["cwd"] == str(tmp_path)
    assert tmp_path.name in str(result["messages"][0].content)


@pytest.mark.asyncio
async def test_direct_local_exec_preserves_explicit_workspace_directory(tmp_path, monkeypatch):
    explicit = tmp_path / "chosen"
    explicit.mkdir()
    config = FixtureConfig(tmp_path / "atlas.db")
    monkeypatch.setattr("atlas.agent.get_config", lambda: config)
    monkeypatch.setattr("atlas.tools.local_execution.get_config", lambda: config)
    runtime = LocalExecutionRuntime()
    capture = CaptureExecution(runtime)
    agent = _agent(capture)
    try:
        result = await agent._execute_tools_node(_state("local_exec", {
            "executable": sys.executable,
            "args": ["-c", "import os; print(os.getcwd())"],
            "cwd": str(explicit),
        }, tmp_path))
    finally:
        await runtime.shutdown()

    assert capture.calls[0][1]["cwd"] == str(explicit)
    assert explicit.name in str(result["messages"][0].content)


@pytest.mark.asyncio
async def test_local_process_start_defaults_missing_cwd_to_workspace(tmp_path, monkeypatch):
    config = FixtureConfig(tmp_path / "atlas.db")
    monkeypatch.setattr("atlas.agent.get_config", lambda: config)
    runtime = LocalExecutionRuntime()
    capture = CaptureExecution(runtime)
    agent = _agent(capture)
    try:
        await agent._execute_tools_node(_state("local_process", {
            "action": "start", "executable": sys.executable,
            "args": ["-c", "import os; print(os.getcwd())"], "cwd": "",
        }, tmp_path))
    finally:
        await runtime.shutdown()

    assert capture.calls[0][1]["cwd"] == str(tmp_path)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_direct_local_exec_defaults_to_session_working_directory(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    selected = workspace / "nested" / "selected"
    selected.mkdir(parents=True)
    config = FixtureConfig(tmp_path / "atlas.db")
    monkeypatch.setattr("atlas.agent.get_config", lambda: config)
    monkeypatch.setattr("atlas.tools.local_execution.get_config", lambda: config)
    runtime = LocalExecutionRuntime()
    capture = CaptureExecution(runtime)
    agent = _agent(capture)
    try:
        result = await agent._execute_tools_node(_state("local_exec", {
            "executable": sys.executable,
            "args": ["-c", "from pathlib import Path; Path('cwd-marker.txt').write_text('cwd-ok')"],
        }, workspace, working_directory=selected))
    finally:
        await runtime.shutdown()

    assert capture.calls[0][1]["cwd"] == str(selected)
    assert (selected / "cwd-marker.txt").read_text(encoding="utf-8") == "cwd-ok"
    assert not (workspace / "cwd-marker.txt").exists()
    assert "cwd-ok" in str(result["messages"][0].content)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_working_directory_tool_reads_and_changes_relative_to_current_directory(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    selected = workspace / "nested"
    child = selected / "child"
    child.mkdir(parents=True)
    config = FixtureConfig(tmp_path / "atlas.db")
    monkeypatch.setattr("atlas.agent.get_config", lambda: config)
    monkeypatch.setattr("atlas.tools.local_execution.get_config", lambda: config)
    runtime = LocalExecutionRuntime()
    agent = _agent(runtime)
    agent._mcp = None
    try:
        names = {item["function"]["name"] for item in agent._model_facing_tools()}
        assert "working_directory" in names

        state = _state("working_directory", {"cd": "child"}, workspace, selected)
        changed = await agent._execute_tools_node(state)
        assert json.loads(changed["messages"][-1].content)["cwd"] == str(child.resolve())
        assert state["runtime"].working_directory == str(child.resolve())

        read_state = _state("working_directory", {}, workspace, child)
        read = await agent._execute_tools_node(read_state)
        assert json.loads(read["messages"][-1].content)["cwd"] == str(child.resolve())

        rejected = _state("working_directory", {"cd": str(tmp_path)}, workspace, child)
        denied = await agent._execute_tools_node(rejected)
        assert "inside the trusted workspace" in str(denied["messages"][-1].content)
        assert rejected["runtime"].working_directory == str(child)
        assert rejected["runtime"].workspace == str(workspace)

        missing = _state("working_directory", {"cd": "missing"}, workspace, child)
        missing_result = await agent._execute_tools_node(missing)
        assert "missing" in str(missing_result["messages"][-1].content)
        assert missing["runtime"].working_directory == str(child)

        recovery = _state("working_directory", {}, workspace, selected / "removed")
        recovered = await agent._execute_tools_node(recovery)
        assert json.loads(recovered["messages"][-1].content)["cwd"] == str(workspace.resolve())
        assert recovery["runtime"].working_directory == str(workspace.resolve())
    finally:
        await runtime.shutdown()


@pytest.mark.unit
def test_tool_registry_process_cwd_keeps_workspace_authority_separate(tmp_path):
    from atlas.engine.tool_registry import _default_process_cwd

    workspace = tmp_path / "workspace"
    selected = workspace / "nested"
    selected.mkdir(parents=True)
    runtime = SimpleNamespace(workspace=str(workspace), working_directory=str(selected))
    assert _default_process_cwd(runtime) == str(selected.resolve())
    runtime.working_directory = str(tmp_path)
    with pytest.raises(ValueError, match="inside the trusted workspace"):
        _default_process_cwd(runtime)

    remote = SimpleNamespace(workspace="ssh://build-host/srv/project", working_directory="/tmp/elsewhere")
    assert _default_process_cwd(remote) == "/srv/project"
