from __future__ import annotations

import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest
from websockets.asyncio.client import connect

from atlas.kernel.loop import _cleanup_tool_waiters, _unverified_code_paths
from atlas.kernel.tools import ToolScheduler
from tests.fakes.fake_llm_provider import ToolCall
from tests.fakes.k1_harness import k1_backend


@pytest.mark.asyncio
async def test_cancelled_tool_batch_keeps_partial_result_and_does_not_dispatch_later_call():
    started = asyncio.Event()
    dispatched: list[str] = []

    async def dispatch(call_id: str, name: str, _args: dict):
        dispatched.append(name)
        if name == "local_file":
            started.set()
            await asyncio.Event().wait()
        return {"content": "done"}

    scheduler = ToolScheduler(dispatch, read_only=lambda name, _args: name == "local_file")
    task = asyncio.create_task(scheduler.run([
        {"id": "call-1", "name": "local_file", "args": {"action": "read"}},
        {"id": "call-2", "name": "write_file", "args": {"path": "x", "content": "y"}},
    ]))
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()
    results = await asyncio.wait_for(task, timeout=1)

    assert len(results) == 2
    assert [item.call_id for item in results] == ["call-1", "call-2"]
    assert results[0].receipt.state == "cancelled"
    assert results[1].receipt.state == "cancelled"
    assert dispatched == ["local_file"]


@pytest.mark.asyncio
async def test_tool_batch_waiter_cleanup_allows_missing_cancel_event():
    queue_get = asyncio.create_task(asyncio.Event().wait())

    await _cleanup_tool_waiters(queue_get, None)

    assert queue_get.cancelled()


@pytest.mark.asyncio
async def test_api_stop_cancels_slow_atlas_kernel_tool(k1_backend):
    backend = k1_backend
    backend.fake._responder = lambda _record: ToolCall(
        "clock.sleep", {"seconds": 30},
    )
    stop_sent = False
    conversation = await backend.conversation()
    run_id = uuid.uuid4().hex
    events = []
    url = backend.url.replace("http", "ws", 1) + "/ws/chat"
    async with connect(
        url, additional_headers={"x-atlas-api-token": "c1-isolated-token"},
        max_size=8_000_000, ping_interval=None,
    ) as ws:
        await ws.send(json.dumps({
            "type": "run.start", "run_id": run_id,
            "content": "Wait for thirty seconds", "conversation_id": conversation,
            "workspace": str(backend.root / "workspace"), "model": "fake-model",
        }))
        async with asyncio.timeout(90):
            while True:
                event = json.loads(await ws.recv())
                events.append(event)
                if (event.get("run_id") == run_id
                        and event.get("event") == "tool.started"
                        and event.get("data", {}).get("name") == "clock.sleep"
                        and not stop_sent):
                    stop_sent = True
                    await ws.send(json.dumps({
                        "type": "run.cancel", "run_id": run_id,
                    }))
                if (event.get("run_id") == run_id
                        and event.get("event") in {
                            "run.completed", "run.failed", "run.cancelled",
                        }):
                    break

    assert stop_sent
    assert any(
        event.get("event") == "run.started"
        and event.get("data", {}).get("executor") == "atlas"
        for event in events
    )
    assert any(
        event.get("event") == "tool.started"
        and event.get("data", {}).get("name") == "clock.sleep"
        for event in events
    )
    assert events[-1]["event"] == "run.cancelled"
    assert not any(
        event.get("event") == "tool.completed"
        and event.get("data", {}).get("name") == "clock.sleep"
        for event in events
    )


def test_unverified_code_paths_only_returns_unchecked_code_changes_once_bounded():
    paths = {f"src/file-{index}.py" for index in range(10)} | {"notes.md"}

    result = _unverified_code_paths(SimpleNamespace(
        changed_paths=paths, verification_passed=False,
    ))
    assert len(result) == 8
    assert all(path.endswith(".py") for path in result)
    assert _unverified_code_paths(SimpleNamespace(
        changed_paths=paths, verification_passed=True,
    )) == []
    assert _unverified_code_paths(SimpleNamespace(changed_paths=set())) == []
