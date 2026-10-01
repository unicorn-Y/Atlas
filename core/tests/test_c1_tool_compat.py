from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest

from atlas.engine.tool_registry import _translate
from atlas.tools.local_execution import LocalExecutionRuntime, _find_git_bash


def test_terminal_translation_keeps_shell_and_notification_parameters():
    _, cmd = _translate("terminal", {"command": "echo ok", "shell": "cmd"})
    _, bash = _translate(
        "terminal",
        {
            "command": "printf ok",
            "shell": "bash",
            "notify": ["READY"],
            "heartbeat": 0.25,
        },
    )
    assert cmd["shell"] == "cmd"
    assert bash["shell"] == "bash"
    assert bash["notify"] == ["READY"]
    assert bash["heartbeat"] == 0.25
    with pytest.raises(ValueError, match="heartbeat"):
        _translate("terminal", {"command": "echo no", "heartbeat": float("nan")})


def test_process_translation_preserves_line_offsets_and_parallel_delegate():
    _, log = _translate(
        "process_manage", {"action": "log", "session_id": "p", "offset": 2, "limit": 5}
    )
    _, poll = _translate(
        "process_manage", {"action": "poll", "session_id": "p", "offset": 2, "limit": 5}
    )
    target, delegated = _translate("delegate_task", {"tasks": [{"goal": "a"}, {"goal": "b"}]})
    assert (log["action"], log["execution_id"], log["_line_offsets"]) == ("read", "p", True)
    assert (poll["action"], poll["_native_poll"]) == ("status", True)
    assert target == "delegate_parallel" and len(delegated["tasks"]) == 2


def test_patch_translation_preserves_ssh_patch_mode_and_replace_all():
    target, args = _translate(
        "patch", {"mode": "patch", "patch": "*** Begin Patch", "replace_all": True}
    )
    assert target == "local_edit"
    assert args["mode"] == "patch"
    assert args["patch"] == "*** Begin Patch"
    assert args["replace_all"] is True


@pytest.mark.asyncio
async def test_real_shell_and_process_actions_keep_output_streams_and_line_paging(tmp_path):
    runtime = LocalExecutionRuntime()
    try:
        bash_available = _find_git_bash() is not None
        commands = [
            ("cmd", "echo CMD_OK"),
            ("bash", "printf BASH_OK" if bash_available else "Write-Output BASH_OK"),
        ]
        for shell, command in commands:
            result = await runtime.call_tool(
                "local_shell",
                {
                    "shell": shell,
                    "command": command,
                    "cwd": str(tmp_path),
                    "timeout": 10,
                },
            )
            assert result["data"]["state"] == "exited"
            assert f"{shell.upper()}_OK" in result["data"]["stdout"]

        started = await runtime.call_tool(
            "local_process",
            {
                "action": "start",
                "executable": sys.executable,
                "args": [
                    "-c",
                    "import sys; print('one', flush=True); print('err-one', file=sys.stderr, flush=True); x=sys.stdin.readline(); print('got:'+x.strip(), flush=True)",
                ],
                "cwd": str(tmp_path),
                "detached": True,
                "keep_stdin": True,
            },
        )
        execution_id = started["data"]["execution_id"]
        listed = await runtime.call_tool("local_process", {"action": "list"})
        assert any(item["execution_id"] == execution_id for item in listed["data"]["processes"])

        process = runtime._processes[execution_id]
        while process.stdout_size == 0 or process.stderr_size == 0:
            await asyncio.sleep(0.01)
        status = await runtime.call_tool(
            "local_process", {"action": "status", "execution_id": execution_id}
        )
        assert status["data"]["state"] == "running"
        polled = await runtime.call_tool(
            "local_process",
            {
                "action": "status",
                "execution_id": execution_id,
                "_native_poll": True,
                "offset": 0,
                "limit": 2,
            },
        )
        assert "one" in polled["data"]["new_output"]
        assert "err-one" in polled["data"]["new_stderr"]
        stdout = await runtime.call_tool(
            "local_process",
            {
                "action": "read",
                "execution_id": execution_id,
                "_line_offsets": True,
                "offset": 0,
                "limit": 1,
            },
        )
        assert stdout["data"]["next_offset"] == 1 and stdout["data"]["text"] == "one"
        stderr = await runtime.call_tool(
            "local_process",
            {
                "action": "read",
                "execution_id": execution_id,
                "stream": "stderr",
                "_line_offsets": True,
                "offset": 0,
                "limit": 1,
            },
        )
        assert stderr["data"]["text"] == "err-one"

        await runtime.call_tool(
            "local_process",
            {"action": "write_stdin", "execution_id": execution_id, "data": "hello"},
        )
        await runtime.call_tool(
            "local_process",
            {"action": "submit_stdin", "execution_id": execution_id, "data": "world"},
        )
        closed = await runtime.call_tool(
            "local_process", {"action": "close_stdin", "execution_id": execution_id}
        )
        assert closed["data"]["closed"] is True
        waited = await runtime.call_tool(
            "local_process", {"action": "wait", "execution_id": execution_id, "timeout": 10}
        )
        assert "got:hello" in waited["data"]["stdout"]

        cancelled = await runtime.call_tool(
            "local_process",
            {
                "action": "start",
                "executable": sys.executable,
                "args": ["-c", "import time; time.sleep(10)"],
                "cwd": str(tmp_path),
                "detached": True,
            },
        )
        cancelled_id = cancelled["data"]["execution_id"]
        handoff = await runtime.call_tool(
            "local_process",
            {
                "action": "handoff",
                "execution_id": cancelled_id,
                "data": "keep running",
            },
            event_callback=lambda _event: None,
        )
        assert handoff["data"]["detached"] is True
        killed = await runtime.call_tool(
            "local_process", {"action": "cancel", "execution_id": cancelled_id}
        )
        assert killed["data"]["state"] == "cancelled"
    finally:
        await runtime.shutdown()

@pytest.mark.asyncio
async def test_invalid_process_parameters_fail_before_spawn_and_callback_errors_do_not_fail_child(tmp_path):
    runtime = LocalExecutionRuntime()
    try:
        invalid = await runtime.call_tool(
            "local_exec",
            {
                "executable": sys.executable,
                "args": ["-c", "raise SystemExit(0)"],
                "cwd": str(tmp_path),
                "detached": True,
                "heartbeat": float("nan"),
            },
        )
        assert invalid["is_error"] is True
        assert runtime._processes == {}

        def broken_notification(_event):
            raise RuntimeError("notification transport unavailable")

        valid = await runtime.call_tool(
            "local_exec",
            {
                "executable": sys.executable,
                "args": ["-c", "print('child-ok')"],
                "cwd": str(tmp_path),
                "detached": True,
                "notify": True,
            },
            event_callback=broken_notification,
        )
        child = runtime._processes[valid["data"]["execution_id"]]
        await child.wait_task
        assert child.state == "exited"
        assert child.exit_code == 0
    finally:
        await runtime.shutdown()
@pytest.mark.asyncio
async def test_legacy_parallel_delegate_reaches_atlas_handler_with_parent_policy(tmp_path, monkeypatch):
    from langchain_core.messages import AIMessage

    from atlas.agent import AgentOrchestrator
    from atlas.engine.tool_permissions import tool_allowed

    definitions = [{
        "name": "general", "warnings": [], "trusted": True, "role": "leaf",
        "model": "inherit", "tools": None, "permission_mode": None,
    }]
    monkeypatch.setattr(
        "atlas.agent.definitions.list_agent_types", lambda *_args, **_kwargs: definitions,
    )
    tasks = [{"goal": "first"}, {"goal": "second"}]
    tool_name, tool_args = _translate("delegate_task", {"tasks": tasks})
    assert tool_name == "delegate_parallel"

    class DelegationFake:
        calls = []

        async def delegate_parallel(self, received, **kwargs):
            self.calls.append((received, kwargs))
            return {"summary": "parallel complete", "evidence": []}

    delegation = DelegationFake()
    agent = object.__new__(AgentOrchestrator)
    agent._model_mgr = SimpleNamespace(current_model="fake-model")
    agent._delegation = delegation
    agent._mcp = None
    agent.trajectory_reviewer = SimpleNamespace(reviewer=None)
    agent._model_facing_tools = lambda: []
    agent._emit_hook = lambda *_args, **_kwargs: asyncio.sleep(0)
    agent._summarize_parallel_results = lambda _results: "summary"

    cancel_event = asyncio.Event()
    pause_event = asyncio.Event()
    pause_event.set()
    event_queue = asyncio.Queue()
    runtime = SimpleNamespace(
        workspace=str(tmp_path), allowed_paths=[], permission_mode="full_access",
        user_hook_callback=None, ssh_tool_callback=None, ssh_checkpoint_callback=None,
        tool_allow=["delegate_task"], tool_deny=["write_file"], read_only=False,
        cancel_event=cancel_event, pause_event=pause_event, approval_callback=None,
        hermes_preapproved_writes=set(), sandbox_tool_callback=None,
        sandbox_enabled=False, workspace_trusted=True, agent_role="general",
        agent_type="general", agent_depth=0, model="fake-model", event_queue=event_queue,
        subtask_started=None, subtask_progress=None, subtask_completed=None,
        subtask_group_completed=None, conversation_id="parent", run_id="run",
        goal="parallel parent",
    )
    assert tool_allowed("delegate_parallel", runtime.tool_allow, runtime.tool_deny)
    result = await agent._execute_tools_node({
        "messages": [AIMessage(content="", tool_calls=[{
            "name": tool_name, "args": tool_args, "id": "legacy-parallel-call",
        }])],
        "pending_events": [], "tool_rounds": 0, "runtime": runtime,
    })
    assert len(delegation.calls) == 1
    received, options = delegation.calls[0]
    assert [item["goal"] for item in received] == ["first", "second"]
    assert options["atlas_options"]["tool_allow"] == ["delegate_task"]
    assert options["atlas_options"]["tool_deny"] == ["write_file"]
    assert options["atlas_options"]["permission_mode"] == "full_access"
    assert options["cancel_event"] is cancel_event
    assert result["pending_events"][-1]["name"] == "delegate_parallel"

    runtime.tool_allow = None
    runtime.tool_deny = ["delegate_task"]
    denied = await agent._execute_tools_node({
        "messages": [AIMessage(content="", tool_calls=[{
            "name": tool_name, "args": tool_args, "id": "denied-parallel-call",
        }])],
        "pending_events": [], "tool_rounds": 0, "runtime": runtime,
    })
    assert len(delegation.calls) == 1
    assert denied["pending_events"][-1]["is_error"] is True