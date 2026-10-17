from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from atlas.kernel.loop import _unverified_code_paths
from atlas.kernel.tools import ToolScheduler


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
