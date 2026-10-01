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
