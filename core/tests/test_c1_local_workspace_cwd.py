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


def _state(name, arguments, workspace):
    context = AgentRunContext(
        workspace=str(workspace), run_id="cwd-fixture", conversation_id="cwd-fixture",
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
