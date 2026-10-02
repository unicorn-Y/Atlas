import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from atlas.engine import hermes_policy
from atlas.engine.tool_registry import _active_contexts


def _runtime(queue, **overrides):
    values = dict(
        pause_event=asyncio.Event(), cancel_event=asyncio.Event(),
        permission_mode="full_access", mode="act", read_only=False,
        tool_allow=None, tool_deny=[], workspace="", allowed_paths=[],
        event_queue=queue, user_hook_callback=None,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_policy_pause_waits_resume_and_cancel_emits_one_block_result():
    queue = asyncio.Queue()
    runtime = _runtime(queue)
    agent = SimpleNamespace(_model_facing_tools=lambda: [])
    _active_contexts["compat-policy"] = (agent, runtime, asyncio.get_running_loop())
    try:
        waiting = asyncio.create_task(asyncio.to_thread(
            hermes_policy._pre_tool_call, "read_file", {},
            session_id="compat-policy", tool_call_id="paused-call",
        ))
        await asyncio.sleep(0.04)
        assert not waiting.done()
        runtime.pause_event.set()
        assert await waiting is None
        assert queue.empty()

        runtime.pause_event.clear()
        runtime.cancel_event.set()
        blocked = await asyncio.to_thread(
            hermes_policy._pre_tool_call, "read_file", {},
            session_id="compat-policy", tool_call_id="cancelled-call",
        )
        assert blocked["action"] == "block"
        result = queue.get_nowait()
        assert result["id"] == "cancelled-call" and result["is_error"] is True
        assert queue.empty()

        runtime.cancel_event.clear()
        runtime.pause_event.set()
        runtime.permission_mode = "read_only"
        denied = await asyncio.to_thread(
            hermes_policy._pre_tool_call, "write_file", {"path": "blocked.txt"},
            session_id="compat-policy", tool_call_id="denied-call",
        )
        assert denied["action"] == "block"
        failure = queue.get_nowait()
        assert failure["id"] == "denied-call" and failure["name"] == "write_file"
        assert failure["is_error"] is True
        assert queue.empty()
    finally:
        _active_contexts.pop("compat-policy", None)


@pytest.mark.asyncio
async def test_ssh_rich_patch_is_rejected_with_native_failure_event():
    queue = asyncio.Queue()
    pause_event = asyncio.Event()
    pause_event.set()
    runtime = _runtime(queue, pause_event=pause_event, workspace="ssh://host/workspace")
    agent = SimpleNamespace(_model_facing_tools=lambda: [])
    _active_contexts["compat-ssh-patch"] = (agent, runtime, asyncio.get_running_loop())
    try:
        blocked = await asyncio.to_thread(
            hermes_policy._pre_tool_call, "patch",
            {"path": "file.txt", "mode": "patch", "patch": "*** Begin Patch"},
            session_id="compat-ssh-patch", tool_call_id="ssh-rich-patch",
        )
        assert blocked["action"] == "block"
        event = queue.get_nowait()
        assert (event["id"], event["name"], event["is_error"]) == (
            "ssh-rich-patch", "patch", True,
        )
        assert "不支持 V4A patch" in event["content"][0]["text"]
        assert queue.empty()

        allowed = await asyncio.to_thread(
            hermes_policy._pre_tool_call, "patch",
            {"path": "file.txt", "mode": "replace", "old_string": "a", "new_string": "b"},
            session_id="compat-ssh-patch", tool_call_id="ssh-exact-patch",
        )
        assert allowed is None
        assert queue.empty()
    finally:
        _active_contexts.pop("compat-ssh-patch", None)


@pytest.mark.asyncio
async def test_approval_and_user_hook_outcomes_emit_only_matching_native_failures():
    queue = asyncio.Queue()
    pause_event = asyncio.Event()
    pause_event.set()

    async def approval_deny(_event_id, _name, _args):
        return "deny"

    async def hook_block(_event_name, _payload):
        return {"blocked": True, "reason": "fixture hook denied"}

    runtime = _runtime(
        queue, pause_event=pause_event, permission_mode="ask_writes",
        approval_callback=approval_deny, user_hook_callback=hook_block,
    )
    agent = SimpleNamespace(_model_facing_tools=lambda: [])
    _active_contexts["compat-approval-results"] = (
        agent, runtime, asyncio.get_running_loop(),
    )
    try:
        denied = await asyncio.to_thread(
            hermes_policy._pre_tool_call, "terminal", {"command": "echo no"},
            session_id="compat-approval-results", tool_call_id="approval-denied",
        )
        assert denied["action"] == "block"
        approval_event = queue.get_nowait()
        assert approval_event["id"] == "approval-denied"
        assert approval_event["name"] == "terminal"
        assert approval_event["is_error"] is True
        assert queue.empty()

        runtime.permission_mode = "full_access"
        blocked = await asyncio.to_thread(
            hermes_policy._pre_tool_call, "read_file", {"path": "blocked.txt"},
            session_id="compat-approval-results", tool_call_id="hook-blocked",
        )
        assert blocked["action"] == "block"
        hook_event = queue.get_nowait()
        assert hook_event["id"] == "hook-blocked"
        assert hook_event["name"] == "read_file"
        assert hook_event["is_error"] is True
        assert "fixture hook denied" in hook_event["content"][0]["text"]
        assert queue.empty()

        runtime.user_hook_callback = None
        runtime.approval_callback = lambda *_args: "allow"
        runtime.permission_mode = "ask_writes"
        allowed = await asyncio.to_thread(
            hermes_policy._pre_tool_call, "terminal", {"command": "echo yes"},
            session_id="compat-approval-results", tool_call_id="approval-allowed",
        )
        assert allowed is None
        assert queue.empty()
    finally:
        _active_contexts.pop("compat-approval-results", None)


@pytest.mark.asyncio
async def test_plan_mode_read_only_terminal_allowlist_and_shell_redirection_block():
    queue = asyncio.Queue()
    pause = asyncio.Event(); pause.set()
    runtime = _runtime(queue, pause_event=pause, mode="plan")
    _active_contexts["plan-read-shell"] = (SimpleNamespace(_model_facing_tools=lambda: []), runtime, asyncio.get_running_loop())
    try:
        for command in ("git status --short", "git log -3", "rg needle .", "Get-Content notes.txt"):
            assert await asyncio.to_thread(hermes_policy._pre_tool_call, "terminal", {"command": command},
                session_id="plan-read-shell", tool_call_id=command) is None
        for command in ("git status > out.txt", "git status; Remove-Item file", "Write-Output $env:PATH"):
            blocked = await asyncio.to_thread(hermes_policy._pre_tool_call, "terminal", {"command": command},
                session_id="plan-read-shell", tool_call_id=command)
            assert blocked["action"] == "block"
        assert queue.qsize() == 3
    finally:
        _active_contexts.pop("plan-read-shell", None)


@pytest.mark.asyncio
async def test_ask_each_and_auto_file_request_only_their_configured_approvals():
    queue = asyncio.Queue()
    pause = asyncio.Event(); pause.set()
    calls = []
    async def approve(event_id, name, _args):
        calls.append((event_id, name))
        return "allow"
    runtime = _runtime(queue, pause_event=pause, permission_mode="ask_each", approval_callback=approve,
                       workspace="C:/fixture", hermes_write_checkpoint_created=True)
    agent = SimpleNamespace(_model_facing_tools=lambda: [], _checkpoint_path=lambda *_args: {"id": "checkpoint-fixture"})
    runtime.run_id = "run-fixture"
    runtime.conversation_id = "conversation-fixture"
    _active_contexts["permission-modes"] = (agent, runtime, asyncio.get_running_loop())
    try:
        assert await asyncio.to_thread(hermes_policy._pre_tool_call, "read_file", {}, session_id="permission-modes", tool_call_id="read") is None
        assert calls == [("approval:read", "read_file")]
        runtime.permission_mode = "auto_file"
        assert await asyncio.to_thread(hermes_policy._pre_tool_call, "write_file", {}, session_id="permission-modes", tool_call_id="file") is None
        assert await asyncio.to_thread(hermes_policy._pre_tool_call, "terminal", {"command": "echo fixture"}, session_id="permission-modes", tool_call_id="shell") is None
        assert calls == [("approval:read", "read_file"), ("approval:shell", "terminal")]
    finally:
        _active_contexts.pop("permission-modes", None)


@pytest.mark.asyncio
async def test_real_hermes_deferred_atlas_calls_apply_nested_allow_and_deny(tmp_path, monkeypatch):
    from tests.fakes.fake_llm_provider import Text, ToolCall
    from tests.test_c1_review_e2e import run_script

    target = tmp_path / "denied.md"
    events, _, ctx = await run_script(
        tmp_path, monkeypatch,
        [
            ToolCall("tool_call", {"calls": [{"name": "todo_list", "arguments": {
                "todos": [{"id": "allowed", "content": "allowed through bridge", "status": "pending"}],
            }}]}),
            ToolCall("tool_call", {"calls": [{"name": "create_document", "arguments": {
                "path": str(target), "blocks": [],
            }}]}),
            Text("finished"),
        ],
        tool_allow=["todo_list"],
    )
    assert ctx.todo_store.snapshot()["todos"][0]["text"] == "allowed through bridge"
    assert not target.exists()
    tool_messages = [
        row for row in events[-1]["result"]["messages"]
        if row.get("role") == "tool"
    ]
    assert any("不允许" in str(row.get("content", "")) for row in tool_messages)
    queued = []
    while not ctx.event_queue.empty():
        queued.append(ctx.event_queue.get_nowait())
    assert any(
        item.get("type") == "tool_result" and item.get("is_error")
        and item.get("name") == "create_document"
        for item in queued
    )


@pytest.mark.asyncio
async def test_native_v4a_move_checks_destination_and_rewinds_both_paths(tmp_path):
    import tools.file_tools  # register the actual Hermes native patch handler
    from tools.registry import registry
    from atlas.agent.checkpoints import ShadowGitCheckpointStore

    store = ShadowGitCheckpointStore(tmp_path / "checkpoints")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "source.txt"
    destination = workspace / "nested" / "destination.txt"
    destination.parent.mkdir()
    source.write_text("original\n", encoding="utf-8")

    def checkpoint_path(raw_path, cwd=None, run_id=None, conversation_id=None):
        path = Path(raw_path)
        resolved = (path if path.is_absolute() else workspace / path).resolve()
        relative = resolved.relative_to(workspace).as_posix()
        return store.create_checkpoint(
            workspace, [relative], run_id=run_id, conversation_id=conversation_id,
        )

    queue = asyncio.Queue()
    pause_event = asyncio.Event()
    pause_event.set()
    runtime = _runtime(
        queue, pause_event=pause_event, workspace=str(workspace),
        allowed_paths=[str(workspace)], run_id="move-run", conversation_id="move-conversation",
    )
    agent = SimpleNamespace(_model_facing_tools=lambda: [], _checkpoint_path=checkpoint_path)
    _active_contexts["compat-v4a-move"] = (agent, runtime, asyncio.get_running_loop())
    try:
        outside = tmp_path / "outside.txt"
        outside_patch = (
            f"*** Begin Patch\n*** Move File: {source} -> {outside}\n*** End Patch"
        )
        blocked = await asyncio.to_thread(
            hermes_policy._pre_tool_call, "patch", {"patch": outside_patch},
            session_id="compat-v4a-move", tool_call_id="move-outside",
        )
        assert blocked["action"] == "block"
        denied = queue.get_nowait()
        assert denied["id"] == "move-outside" and denied["is_error"] is True
        assert not outside.exists()
        assert source.read_text(encoding="utf-8") == "original\n"

        runtime.event_queue = asyncio.Queue()
        internal_patch = (
            f"*** Begin Patch\n*** Move File: {source} -> {destination}\n*** End Patch"
        )
        allowed = await asyncio.to_thread(
            hermes_policy._pre_tool_call, "patch", {"patch": internal_patch},
            session_id="compat-v4a-move", tool_call_id="move-internal",
        )
        assert allowed is None
        checkpoints = []
        while not runtime.event_queue.empty():
            event = runtime.event_queue.get_nowait()
            if event["type"] == "checkpoint_created":
                checkpoints.append(event["checkpoint"])
        assert len(checkpoints) == 2
        assert {item["files"][0]["path"] for item in checkpoints} == {
            "source.txt", "nested/destination.txt",
        }

        handler = registry.get_entry("patch").handler
        result = handler(
            {"path": str(source), "mode": "patch", "patch": internal_patch},
            task_id="c1-v4a-internal-move",
        )
        assert not source.exists(), result
        assert destination.read_text(encoding="utf-8") == "original\n"
        assert "error" not in result.lower()

        for checkpoint in checkpoints:
            store.restore_checkpoint(checkpoint["id"])
        assert source.read_text(encoding="utf-8") == "original\n"
        assert not destination.exists()
    finally:
        _active_contexts.pop("compat-v4a-move", None)
