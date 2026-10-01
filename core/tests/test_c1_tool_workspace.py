import os
import sys
import asyncio
from types import SimpleNamespace

import pytest

from tests.fakes.fake_llm_provider import Text, ToolCall
from tests.test_c1_review_e2e import run_script
from atlas.engine.tool_registry import _active_contexts, bind_atlas_tools


@pytest.mark.asyncio
async def test_terminal_defaults_to_run_workspace_and_honors_explicit_workdir(tmp_path, monkeypatch):
    explicit = tmp_path / "explicit-cwd"
    explicit.mkdir()
    command = 'python -c "import os; print(os.getcwd())"'
    events, _, _ = await run_script(
        tmp_path, monkeypatch,
        [
            ToolCall("terminal", {"command": command}),
            ToolCall("terminal", {"command": command, "workdir": str(explicit)}),
            Text("cwd checks complete"),
        ],
    )
    tool_messages = [
        str(item.get("content", ""))
        for item in events[-1]["result"]["messages"]
        if item.get("role") == "tool"
    ]
    assert len(tool_messages) == 2, tool_messages
    workspace_text = tool_messages[0].replace("\\\\", "\\").replace("/", "\\").casefold()
    explicit_text = tool_messages[1].replace("\\\\", "\\").replace("/", "\\").casefold()
    assert os.path.normcase(str(tmp_path.resolve())).replace("/", "\\").casefold() in workspace_text
    assert os.path.normcase(str(explicit.resolve())).replace("/", "\\").casefold() in explicit_text


@pytest.mark.asyncio
async def test_local_exec_and_process_start_inherit_runtime_workspace(tmp_path, monkeypatch):
    from tools.registry import registry

    captured = []

    class Agent:
        def _model_facing_tools(self):
            return []

        async def _execute_tools_node(self, state):
            call = state["messages"][0].tool_calls[0]
            captured.append((call["name"], call["args"]))
            return {"messages": [SimpleNamespace(content="captured")]}

    agent = Agent()
    queue = asyncio.Queue()
    runtime = SimpleNamespace(
        workspace=str(tmp_path), conversation_id="workspace-cwd-session",
        event_queue=queue,
    )
    ssh_runtime = SimpleNamespace(
        workspace="ssh://build-host/srv/project", conversation_id="workspace-ssh-session",
        event_queue=asyncio.Queue(),
    )
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(registry, "_tools", dict(registry._tools))
    _active_contexts[runtime.conversation_id] = (agent, runtime, loop)
    _active_contexts[ssh_runtime.conversation_id] = (agent, ssh_runtime, loop)
    try:
        bind_atlas_tools(agent, runtime, loop)
        process_handler = registry.get_entry("process_manage").handler
        terminal_handler = registry.get_entry("terminal").handler
        await asyncio.to_thread(process_handler, {
            "action": "start", "executable": sys.executable, "args": ["-c", "pass"],
        }, session_id=runtime.conversation_id)
        await asyncio.to_thread(terminal_handler, {"command": "pwd"}, session_id=ssh_runtime.conversation_id)
        assert captured[0][0] == "local_process"
        assert captured[0][1]["cwd"] == str(tmp_path)
        assert captured[1][0] == "local_shell"
        assert captured[1][1]["cwd"] == "/srv/project"
        assert not captured[1][1]["cwd"].startswith("ssh://")
    finally:
        _active_contexts.pop(runtime.conversation_id, None)
        _active_contexts.pop(ssh_runtime.conversation_id, None)
