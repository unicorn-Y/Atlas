"""Batch C regression coverage for permission presets and per-call requests."""

import asyncio
import pytest
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

from atlas import approval_policy
from atlas.api.run_drive import _resolve_permission_policy
from atlas.engine.tool_permissions import (
    authorize_sandbox_escalation,
    normalize_sandbox_escalation,
)
from atlas.sandbox import DockerSandboxManager
import atlas.sandbox as sandbox_module
from atlas.tools.local_execution import LOCAL_TOOLS, _process_owner_allowed, _wait_reason
from atlas.tools.local_execution import LocalExecutionRuntime


@pytest.mark.unit
def test_permission_presets_bind_sandbox_and_approval_policy():
    observe = approval_policy.preset("observe")
    assert observe["sandbox_mode"] == "read-only"
    assert observe["approval_policy"] == "never"

    ask = approval_policy.preset("ask")
    assert ask["sandbox_mode"] == "workspace-write"
    assert ask["approval_policy"] == "ask"


@pytest.mark.unit
def test_run_permission_preset_keeps_all_three_policy_dimensions():
    resolved = _resolve_permission_policy({"permission_preset": "trusted"})
    assert (resolved["name"], resolved["mode"], resolved["sandbox_mode"],
            resolved["approval_policy"]) == (
                "trusted", "auto_file", "workspace-write", "never",
            )


@pytest.mark.unit
def test_run_explicit_permission_mismatch_derives_custom_preset():
    resolved = _resolve_permission_policy({
        "permission_preset": "ask", "permission_mode": "full_access",
    })
    assert resolved["name"] == "custom"
    assert resolved["mode"] == "full_access"
    assert resolved["sandbox_mode"] == "workspace-write"
    assert resolved["approval_policy"] == "ask"


@pytest.mark.unit
def test_runtime_persists_permission_preset_dimensions_for_resume():
    from atlas.api.run_drive import _restore_permission_policy
    from atlas.api.runtime import RunState, _resume_context

    run = RunState("run-1", "conversation-1", "model")
    run.permission_mode = "auto_file"
    run.sandbox_mode = "workspace-write"
    run.approval_policy = "never"
    run.permission_preset = "trusted"

    context = _resume_context(run)
    assert context["sandbox_mode"] == "workspace-write"
    assert context["approval_policy"] == "never"
    assert context["permission_preset"] == "trusted"

    resumed = RunState("run-2", "conversation-1", "model")
    _restore_permission_policy(resumed, context)
    assert resumed.sandbox_mode == "workspace-write"
    assert resumed.approval_policy == "never"
    assert resumed.permission_preset == "trusted"


@pytest.mark.unit
def test_preset_pair_derives_custom_when_no_named_pair_matches():
    custom = approval_policy.preset_for_policy(
        permission_mode="ask_writes",
        sandbox_mode="danger-full-access",
        approval_policy="never",
    )
    assert custom["name"] == "custom"
    assert custom["sandbox_mode"] == "danger-full-access"
    assert custom["approval_policy"] == "never"


@pytest.mark.unit
def test_sandbox_escalation_requires_supported_mode_and_reason():
    request = normalize_sandbox_escalation({
        "sandbox_permissions": "workspace-write",
        "justification": "Need to update the generated source file.",
    })
    assert request == {
        "sandbox_permissions": "workspace-write",
        "justification": "Need to update the generated source file.",
    }

    with pytest.raises(ValueError, match="justification"):
        normalize_sandbox_escalation({"sandbox_permissions": "danger-full-access"})


@pytest.mark.unit
def test_sandbox_escalation_rejects_unknown_mode():
    with pytest.raises(ValueError, match="sandbox_permissions"):
        normalize_sandbox_escalation({
            "sandbox_permissions": "full-access",
            "justification": "required for the action",
        })


@pytest.mark.unit
@pytest.mark.asyncio
async def test_read_only_sandbox_request_uses_read_only_mount(tmp_path, monkeypatch):
    manager = DockerSandboxManager()
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[1] == "run":
            return SimpleNamespace(returncode=0, stdout="container-id\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(sandbox_module.shutil, "which", lambda _name: "docker-mock")
    monkeypatch.setattr(sandbox_module.subprocess, "run", fake_run)
    await manager.start("run", str(tmp_path), {"type": "docker"})
    result = await manager.call_tool("run", "local_shell", {
        "command": "cat file.txt", "cwd": str(tmp_path),
        "sandbox_permissions": "read-only",
    })

    assert "--mount" in calls[1]
    assert "readonly" in calls[1][calls[1].index("--mount") + 1]
    assert result["data"]["sandbox_permissions"] == "read-only"
    assert result["data"]["sandbox_enforced"] is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_danger_full_access_request_fails_closed_in_docker_sandbox(tmp_path, monkeypatch):
    manager = DockerSandboxManager()
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="container-id\n", stderr="")

    monkeypatch.setattr(sandbox_module.shutil, "which", lambda _name: "docker-mock")
    monkeypatch.setattr(sandbox_module.subprocess, "run", fake_run)
    await manager.start("run", str(tmp_path), {"type": "docker"})
    result = await manager.call_tool("run", "local_shell", {
        "command": "echo unsafe", "cwd": str(tmp_path),
        "sandbox_permissions": "danger-full-access",
    })

    assert len(calls) == 1
    assert result["is_error"] is True
    assert result["data"]["sandbox_enforced"] is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sandbox_escalation_runs_through_per_call_approval():
    answer = AsyncMock(return_value="allow_once")
    arguments = {
        "sandbox_permissions": "danger-full-access",
        "justification": "Need to inspect a system-wide config file.",
    }

    result = await authorize_sandbox_escalation(
        arguments, answer, tool_name="local_exec", tool_call_id="call-1",
    )

    assert result["approved"] is True
    assert result["request"]["sandbox_permissions"] == "danger-full-access"
    answer.assert_awaited_once()
    args = answer.await_args.args
    assert args[:2] == ("call-1", "local_exec")
    assert args[2]["_approval_reason"] == arguments["justification"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sandbox_escalation_denial_is_not_granted():
    answer = AsyncMock(return_value="deny")
    result = await authorize_sandbox_escalation(
        {"sandbox_permissions": "workspace-write", "justification": "Build output."},
        answer, tool_name="local_exec", tool_call_id="call-2",
    )
    assert result["approved"] is False
    assert result["approval_outcome"] == "rejected"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sandbox_escalation_without_approval_channel_is_unavailable():
    result = await authorize_sandbox_escalation(
        {"sandbox_permissions": "workspace-write", "justification": "Build output."},
        None, tool_name="local_exec", tool_call_id="call-3",
    )
    assert result["approved"] is False
    assert result["approval_outcome"] == "unavailable"


@pytest.mark.unit
def test_process_owner_fence_rejects_a_different_run():
    assert _process_owner_allowed(SimpleNamespace(owner_run_id="run-a"), "run-a")
    assert not _process_owner_allowed(SimpleNamespace(owner_run_id="run-a"), "run-b")
    assert not _process_owner_allowed(SimpleNamespace(owner_run_id="run-a"), None)
    assert _process_owner_allowed(SimpleNamespace(owner_run_id=None), "run-b")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_local_process_status_is_fenced_to_starting_run(tmp_path):
    runtime = LocalExecutionRuntime()
    started = await runtime.call_tool(
        "local_process", {
            "action": "start", "executable": sys.executable,
            "args": ["-u", "-c", "import time; time.sleep(5)"],
            "cwd": str(tmp_path), "detached": True,
        },
        run_id="owner-run",
    )
    execution_id = started["data"]["execution_id"]
    try:
        foreign = await runtime.call_tool(
            "local_process", {"action": "status", "execution_id": execution_id},
            run_id="other-run",
        )
        owner = await runtime.call_tool(
            "local_process", {"action": "status", "execution_id": execution_id},
            run_id="owner-run",
        )
    finally:
        await runtime.shutdown()

    assert foreign["is_error"] is True
    assert "different run" in foreign["data"]["error"]
    assert owner["data"]["state"] == "running"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_process_wait_returns_inferred_idle_reason_without_killing(tmp_path):
    runtime = LocalExecutionRuntime()
    started = await runtime.call_tool(
        "local_process", {
            "action": "start", "executable": sys.executable,
            "args": ["-u", "-c", "import time; time.sleep(5)"],
            "cwd": str(tmp_path), "detached": True,
        },
        run_id="idle-run",
    )
    execution_id = started["data"]["execution_id"]
    try:
        waited = await runtime.call_tool(
            "local_process", {
                "action": "wait", "execution_id": execution_id, "idle_timeout": 0.1,
            },
            run_id="idle-run",
        )
    finally:
        await runtime.call_tool(
            "local_process", {"action": "cancel", "execution_id": execution_id},
            run_id="idle-run",
        )
        await runtime.shutdown()

    assert waited["data"]["state"] == "running"
    assert waited["data"]["waitReason"] == "inferred_idle"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_native_local_execution_rejects_unapproved_sandbox_request(tmp_path):
    runtime = LocalExecutionRuntime()
    target = tmp_path / "should-not-run.txt"
    result = await runtime.call_tool(
        "local_exec", {
            "executable": sys.executable,
            "args": ["-c", f"open({str(target)!r}, 'w').write('ran')"],
            "cwd": str(tmp_path),
            "sandbox_permissions": "danger-full-access",
            "justification": "Need to write a marker.",
        },
        run_id="sandbox-run",
    )
    await runtime.shutdown()

    assert result["is_error"] is True
    assert not target.exists()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_native_local_execution_reports_approved_full_access(tmp_path):
    runtime = LocalExecutionRuntime()
    result = await runtime.call_tool(
        "local_exec", {
            "executable": sys.executable,
            "args": ["-c", "print('approved')"],
            "cwd": str(tmp_path),
            "sandbox_permissions": "danger-full-access",
            "justification": "Need the host environment for this command.",
            "_sandbox_approval_outcome": "allowed-once",
        },
        run_id="sandbox-run",
    )
    await runtime.shutdown()

    assert result["data"]["sandbox_permissions"] == "danger-full-access"
    assert result["data"]["sandbox_enforced"] is True
    assert "approved" in result["data"]["stdout"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_inject_routes_to_durable_inbox_without_waking(tmp_path, monkeypatch):
    from atlas.api.run_drive import _inject_run_message
    from atlas.api.runtime import RunState
    from atlas.engine.session_sync import read_session_events

    run = RunState("run-inject", "conversation-inject", "model")
    run.status = "running"
    run.steer_queue = asyncio.Queue()
    monkeypatch.setattr("atlas.config.DATA_ROOT", tmp_path)

    reason, event_id = await _inject_run_message(run, {
        "inject": True, "lane": "next-step", "content": "check this after the current step",
    })

    events = await asyncio.to_thread(
        read_session_events, tmp_path / "engine", run.conversation_id,
    )
    assert reason is None
    assert event_id
    assert run.steer_queue.empty()
    assert events[0]["event_type"] == "inbox.enqueued"
    assert events[0]["payload"]["lane"] == "next-step"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_websocket_inject_branch_uses_durable_inbox_without_steer_event(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace

    from fastapi import WebSocketDisconnect

    from atlas.api.runtime import RunState
    from atlas.api.runtime_ws_router import ws_chat
    from atlas.engine.session_sync import read_session_events

    monkeypatch.setattr("atlas.config.DATA_ROOT", tmp_path)
    run = RunState("ws-inject", "conversation-ws-inject", "model")
    run.status = "running"
    run.steer_queue = asyncio.Queue()

    class Manager:
        def __init__(self):
            self.runs = {run.run_id: run}
            self.sent = []

        async def connect(self, _ws, _conn_id):
            pass

        async def send(self, _conn_id, envelope):
            self.sent.append(envelope)

        def disconnect(self, _conn_id):
            pass

    class Socket:
        def __init__(self):
            self.messages = iter([json.dumps({
                "type": "run.steer", "run_id": run.run_id,
                "inject": True, "lane": "next-step", "content": "route fixture",
            })])

        async def receive_text(self):
            try:
                return next(self.messages)
            except StopIteration:
                raise WebSocketDisconnect()

    manager = Manager()
    services = SimpleNamespace(
        runtime_mgr=manager, runtime_start_handler=None,
        runtime_resume_handler=None, rules_trust_handler=None, orchestrator=None,
    )
    await ws_chat(Socket(), services)

    events = await asyncio.to_thread(
        read_session_events, tmp_path / "engine", run.conversation_id,
    )
    assert run.steer_queue.empty()
    assert [event["event_type"] for event in events] == ["inbox.enqueued"]
    assert events[0]["payload"]["content"] == "route fixture"
    assert manager.sent == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_automation_dispatch_forwards_validated_presets(monkeypatch):
    from types import SimpleNamespace

    from atlas.api import run_drive
    from atlas.config import get_config
    from atlas.task_artifacts import AgentPresetStore

    calls = []
    AgentPresetStore(get_config().db_path.parent).put({
        "id": "researcher_v2", "capabilities": {
            "tools": {"allow": ["local_file"], "deny": ["local_exec"]},
            "skills": [], "mcp_servers": [], "model": "inherit", "mode": "plan",
        },
    })

    async def collect(message, conversation_id, **kwargs):
        calls.append((message, conversation_id, kwargs))
        return "automation response"

    monkeypatch.setattr(run_drive, "_server", lambda: SimpleNamespace(
        app=None, _collect_orchestrator_text=collect,
    ))

    result = await run_drive._automation_dispatch_turn({
        "message": "run this", "agent_preset_id": "researcher_v2",
        "permission_preset": "trusted",
    })

    assert result["text"] == "automation response"
    assert calls[0][2]["agent_preset_id"] == "researcher_v2"
    assert calls[0][2]["permission_preset"] == "trusted"
    assert calls[0][2]["agent_preset_capabilities"]["tools"]["deny"] == ["local_exec"]
    assert calls[0][2]["mode"] == "plan"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_automation_dispatch_rejects_invalid_presets(monkeypatch):
    from types import SimpleNamespace

    from atlas.api import run_drive

    async def collect(*_args, **_kwargs):
        return "should not run"

    monkeypatch.setattr(run_drive, "_server", lambda: SimpleNamespace(
        app=None, _collect_orchestrator_text=collect,
    ))

    with pytest.raises(ValueError, match="agent_preset_id"):
        await run_drive._automation_dispatch_turn({"agent_preset_id": "bad preset"})
    with pytest.raises(ValueError, match="permission_preset"):
        await run_drive._automation_dispatch_turn({"permission_preset": "unknown"})
    with pytest.raises(KeyError, match="unknown agent preset"):
        await run_drive._automation_dispatch_turn({"agent_preset_id": "missing"})


@pytest.mark.unit
def test_pty_wait_reason_is_a_closed_taxonomy():
    assert _wait_reason(SimpleNamespace(state="running", pty=True)) == "stdin_read"
    assert _wait_reason(SimpleNamespace(state="running", pty=False)) == "inferred_idle"
    assert _wait_reason(SimpleNamespace(state="exited", pty=True)) == "session_exit"
    assert _wait_reason(SimpleNamespace(state="running", pty=True), timed_out=True) == "timeout"


@pytest.mark.unit
def test_local_process_tools_expose_per_call_sandbox_request_fields():
    schemas = {
        item["function"]["name"]: item["function"]["parameters"]["properties"]
        for item in LOCAL_TOOLS
    }
    for name in ("local_shell", "local_exec", "local_process"):
        assert schemas[name]["sandbox_permissions"]["enum"] == [
            "read-only", "workspace-write", "danger-full-access",
        ]
        assert schemas[name]["justification"]["type"] == "string"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_approval_lifecycle_helper_appends_to_session_event_store(tmp_path, monkeypatch):
    from atlas.api import run_drive
    from atlas.engine import session_sync

    calls = []
    monkeypatch.setattr(session_sync, "append_session_event", lambda *args: calls.append(args))
    monkeypatch.setattr("atlas.config.DATA_ROOT", tmp_path)

    await run_drive._persist_approval_lifecycle(
        "conversation-1", "approval/asked", {"approval_id": "approval-1"},
    )

    assert calls == [(
        tmp_path / "engine", "conversation-1", "approval/asked",
        {"approval_id": "approval-1"},
    )]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_approval_lifecycle_event_is_durable_without_changing_messages(tmp_path, monkeypatch):
    from atlas.api import run_drive
    from atlas.engine import session_sync

    home = tmp_path / "engine"
    with session_sync._open_db(home) as db:
        db.ensure_session("conversation-2", "api_server")
    monkeypatch.setattr("atlas.config.DATA_ROOT", tmp_path)
    before = await asyncio.to_thread(session_sync.read_session_messages, home, "conversation-2")

    await run_drive._persist_approval_lifecycle(
        "conversation-2", "approval/asked", {"approval_id": "approval-2", "tool": "local_exec"},
    )
    events = await asyncio.to_thread(session_sync.read_session_events, home, "conversation-2")
    after = await asyncio.to_thread(session_sync.read_session_messages, home, "conversation-2")

    assert [(event["event_type"], event["payload"]["approval_id"]) for event in events] == [
        ("approval/asked", "approval-2"),
    ]
    assert after == before
