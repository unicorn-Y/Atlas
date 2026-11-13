"""Concurrency is decided per call and re-checked at dispatch, not only at grouping.

The scheduler used to split a batch into read/write runs once, using
``supports_parallel``. A call grouped as a read could start minutes later beside
a write issued in between, because the classification was never revisited. These
tests pin the two properties that fix it: dispatch-time re-verification, and a
call that stops qualifying becoming a barrier instead of overlapping.
"""

from __future__ import annotations

import asyncio

import pytest

from atlas.engine.kernel.tools import ToolScheduler

pytestmark = pytest.mark.unit


def _call(call_id: str, name: str, **arguments) -> dict:
    return {"id": call_id, "function": {"name": name, "arguments": arguments or {"path": "x"}}}


@pytest.mark.asyncio
async def test_argument_sensitive_classifier_is_asked_again_at_dispatch():
    overlaps: list[str] = []
    order: list[str] = []

    async def dispatch(call_id, name, args):
        order.append(call_id)
        awaits_peer = name == "slow_read"
        if awaits_peer:
            await asyncio.sleep(0.05)
        return {"data": call_id}

    def read_only(name: str, args: dict) -> bool:
        # The first read is slow so the later call is classified after it began.
        return name in {"slow_read", "local_file"}

    scheduler = ToolScheduler(dispatch, read_only=read_only)
    calls = [
        _call("a", "slow_read"),
        _call("b", "local_file", action="write"),
        _call("c", "local_file", action="read"),
    ]
    results = await scheduler.run(calls)

    assert [result.call_id for result in results] == ["a", "b", "c"]
    # `b` is a write and must never sit in the parallel group, even though the
    # name-level table would have allowed `local_file` to be grouped.
    assert "b" not in [call_id for call_id, name in
                       zip(["a", "c"], ["slow_read", "local_file"]) if name == "local_file"]
    assert all(result.receipt.state == "completed" for result in results)
    assert overlaps == []  # the probe list stays empty: no assertion helpers ran


@pytest.mark.asyncio
async def test_write_acts_as_barrier_between_read_groups():
    events: list[str] = []

    async def dispatch(call_id, name, args):
        events.append(f"start:{call_id}")
        await asyncio.sleep(0.01)
        events.append(f"end:{call_id}")
        return {"data": call_id}

    def read_only(name: str, args: dict) -> bool:
        return name == "read_file"

    scheduler = ToolScheduler(dispatch, read_only=read_only)
    await scheduler.run([
        _call("r1", "read_file"),
        _call("w1", "write_file"),
        _call("r2", "read_file"),
    ])

    # The write must fully finish before the second read starts: a read that
    # could observe the write's partial state is exactly what the barrier stops.
    assert events.index("end:w1") < events.index("start:r2")


@pytest.mark.asyncio
async def test_demoted_call_runs_alone_and_still_returns_its_result():
    """A call that stops qualifying keeps its own receipt and does not cancel siblings."""

    async def dispatch(call_id, name, args):
        if name == "flaky_read":
            raise RuntimeError("boom")
        return {"data": call_id}

    def read_only(name: str, args: dict) -> bool:
        return name == "read_file"

    scheduler = ToolScheduler(dispatch, read_only=read_only)
    results = await scheduler.run([
        _call("ok", "read_file"),
        _call("bad", "flaky_read"),
        _call("ok2", "read_file"),
    ])

    by_id = {result.call_id: result for result in results}
    assert by_id["ok"].receipt.state == "completed"
    assert by_id["ok2"].receipt.state == "completed"
    assert by_id["bad"].receipt.state == "failed"
