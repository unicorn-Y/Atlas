import asyncio
import json
import sys
import uuid
from pathlib import Path

import pytest
from tools.tool_result_storage import extract_persisted_path, maybe_persist_tool_result

from atlas.engine.notifications import consume_notifications, publish_notification
from atlas.tools.local_execution import LocalExecutionRuntime


@pytest.mark.asyncio
async def test_notification_inbox_is_durable_consumable_and_conversation_scoped():
    assert await consume_notifications("empty") == []
    first_id = publish_notification(
        "parent", kind="watch", content="ready", source_id="exec:watch:1"
    )
    assert (
        publish_notification("parent", kind="watch", content="duplicate", source_id="exec:watch:1")
        == first_id
    )
    publish_notification("child", kind="completion", content="done")
    parent = await consume_notifications("parent")
    child = await consume_notifications("child")
    assert parent[0]["id"] == first_id
    assert parent[0]["kind"] == "watch" and parent[0]["content"] == "ready"
    assert len(child) == 1 and child[0]["content"] == "done"
    assert await consume_notifications("parent") == []


def test_large_native_read_result_is_spilled_and_can_be_read_again():
    # Hermes tool_executor sends Atlas' native read_file result through this
    # canonical storage path after the Atlas handler returns.
    native_result = "\n".join(f"line-{index:05d}-" + "x" * 80 for index in range(700))
    preview = maybe_persist_tool_result(
        native_result,
        tool_name="read_file",
        tool_use_id="c1-long-native-read",
        threshold=1000,
    )
    spill_path = extract_persisted_path(preview)
    assert spill_path and "line-00699" not in preview
    spill = Path(spill_path)
    assert spill.read_text(encoding="utf-8") == native_result
    # The model-visible block carries the spill path for a follow-up read_file call.
    assert spill_path in preview and "line-00699" in spill.read_text(encoding="utf-8")

    import tools.file_tools  # register Hermes canonical native file handlers
    from tools.registry import registry

    native_read = registry.get_entry("read_file").handler(
        {"path": spill_path, "offset": 690, "limit": 20},
        task_id="c1-native-read-follow-up",
    )
    assert "line-00699" in native_read

@pytest.mark.asyncio
async def test_failed_process_notification_is_durable_for_next_request(tmp_path):
    conversation_id = f"failed-{uuid.uuid4().hex}"
    runtime = LocalExecutionRuntime()
    try:
        started = await runtime.call_tool(
            "local_exec",
            {
                "executable": sys.executable,
                "args": ["-c", "import sys; sys.exit(7)"],
                "cwd": str(tmp_path),
                "detached": True,
                "notify": True,
                "_atlas_conversation_id": conversation_id,
            },
        )
        process = runtime._processes[started["data"]["execution_id"]]
        await process.wait_task

        next_request = await consume_notifications(conversation_id)
        assert len(next_request) == 1
        assert next_request[0]["kind"] == "process.completed"
        completion = json.loads(next_request[0]["content"])
        assert completion["exit_code"] == 7
        assert completion["state"] == "exited"
    finally:
        await runtime.shutdown()


@pytest.mark.asyncio
async def test_handoff_notification_moves_from_child_inbox_to_parent(tmp_path):
    child_id = f"child-{uuid.uuid4().hex}"
    parent_id = f"parent-{uuid.uuid4().hex}"
    runtime = LocalExecutionRuntime()
    try:
        started = await runtime.call_tool(
            "local_exec",
            {
                "executable": sys.executable,
                "args": ["-c", "import time; time.sleep(0.15)"],
                "cwd": str(tmp_path),
                "detached": True,
                "notify": True,
                "_atlas_conversation_id": child_id,
            },
        )
        process_id = started["data"]["execution_id"]
        handoff = await runtime.call_tool(
            "local_process",
            {
                "action": "handoff",
                "execution_id": process_id,
                "_atlas_conversation_id": parent_id,
            },
        )
        assert handoff["is_error"] is False
        await runtime._processes[process_id].wait_task

        assert await consume_notifications(child_id) == []
        parent_items = await consume_notifications(parent_id)
        assert len(parent_items) == 1
        completion = json.loads(parent_items[0]["content"])
        assert completion["execution_id"] == process_id
        assert completion["exit_code"] == 0
    finally:
        await runtime.shutdown()