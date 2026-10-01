import asyncio
import sys

import pytest

from atlas.tools.local_execution import LocalExecutionRuntime
from atlas.engine.tool_registry import _translate


@pytest.mark.asyncio
async def test_background_watch_heartbeat_and_completion_are_delivered(tmp_path):
    runtime = LocalExecutionRuntime()
    events = []
    async def notify(event):
        events.append(event)
    try:
        result = await runtime.call_tool("local_exec", {
            "executable": sys.executable, "args": ["-c", "import time; print('READY', flush=True); time.sleep(.3)"],
            "cwd": str(tmp_path), "detached": True, "notify": True,
            "watch_patterns": ["READY"], "heartbeat": .05,
        }, run_id="notifications", event_callback=notify)
        process = runtime._processes[result["data"]["execution_id"]]
        await process.wait_task
        assert any(item["type"] == "process.completed" and item["data"]["exit_code"] == 0 for item in events)
        assert any(item["data"].get("reason") == "watch" and "READY" in item["data"]["text"] for item in events)
        assert any(item["data"].get("reason") == "heartbeat" for item in events)
        assert process.notification_task.done()
    finally:
        await runtime.shutdown()


def test_terminal_translation_preserves_notification_options():
    _, args = _translate("terminal", {"command": "echo ok", "background": True,
        "notify": ["READY"], "watch_patterns": ["DONE"], "heartbeat": 60})
    assert args["notify"] == ["READY"]
    assert args["watch_patterns"] == ["DONE"]
    assert args["heartbeat"] == 60


@pytest.mark.asyncio
async def test_handoff_retargets_completion_to_parent_after_child_cleanup(tmp_path):
    runtime = LocalExecutionRuntime()
    child_events, parent_events = [], []
    try:
        result = await runtime.call_tool("local_exec", {
            "executable": sys.executable, "args": ["-c", "import time; time.sleep(.2)"],
            "cwd": str(tmp_path), "detached": True, "notify": True,
        }, run_id="child", event_callback=child_events.append)
        process_id = result["data"]["execution_id"]
        handoff = await runtime.call_tool("local_process", {"action": "handoff", "execution_id": process_id},
            run_id="child", event_callback=parent_events.append)
        assert not handoff["is_error"]
        await runtime.cancel_run("child")
        await runtime._processes[process_id].wait_task
        assert not child_events
        assert len(parent_events) == 1 and parent_events[0]["type"] == "process.completed"
        assert parent_events[0]["data"]["exit_code"] == 0
    finally:
        await runtime.shutdown()
