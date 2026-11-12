"""Probe ordered fan-out, partial-failure semantics, and terminal receipts.

Contract as of the tool-timeout work: a single failing call no longer cancels
its siblings. Every sibling runs to completion with its real output, the batch
is marked ``partial``, and ``cancelled`` is reserved for a genuine external
``asyncio.CancelledError``.
"""
from __future__ import annotations

import asyncio

from atlas.kernel.tools import ToolScheduler


async def main() -> None:
    cancelled: list[str] = []
    completed: list[str] = []

    async def dispatch(call_id: str, name: str, args: dict) -> dict:
        if args.get("fail"):
            await asyncio.sleep(0.01)
            return {"is_error": True, "error": "fixture failure"}
        try:
            await asyncio.sleep(0.05)
            completed.append(call_id)
            return {"data": call_id}
        except asyncio.CancelledError:
            cancelled.append(call_id)
            raise

    scheduler = ToolScheduler(dispatch, max_concurrency=3)
    calls = [{"id": "a", "function": {"name": "read_file", "arguments": "{}"}},
             {"id": "b", "function": {"name": "read_file", "arguments": '{"fail":true}'}},
             {"id": "c", "function": {"name": "read_file", "arguments": "{}"}}]
    results = await scheduler.run(calls)

    # Order is preserved regardless of completion order.
    assert [item.call_id for item in results] == ["a", "b", "c"]

    # A failing sibling must not destroy the others' evidence.
    assert [item.receipt.state for item in results] == ["completed", "failed", "completed"], (
        "one failing call cancelled its siblings — fail-fast regressed"
    )
    assert set(completed) == {"a", "c"}
    assert cancelled == [], f"siblings were cancelled: {cancelled}"

    # The surviving siblings still carry their real output.
    assert results[0].output == {"data": "a"}
    assert results[2].output == {"data": "c"}

    # Batch verdict travels on the receipts without touching per-call state.
    assert results[0].receipt.batch_state == "partial"
    assert results[1].receipt.batch_state == "partial"
    assert list(results[1].receipt.failed_calls) == ["b"]

    print("W2-1 ordered receipts, partial batch, siblings preserved: PASS")

    # An all-failing batch is 'failed', not 'partial'.
    async def always_fail(call_id: str, name: str, args: dict) -> dict:
        return {"is_error": True, "error": "nope"}

    failed_results = await ToolScheduler(always_fail, max_concurrency=3).run(calls)
    assert all(item.receipt.state == "failed" for item in failed_results)
    assert failed_results[0].receipt.batch_state == "failed"
    print("W2-2 all-failed batch reports 'failed': PASS")

    # A clean batch is 'completed'.
    async def always_ok(call_id: str, name: str, args: dict) -> dict:
        return {"data": call_id}

    ok_results = await ToolScheduler(always_ok, max_concurrency=3).run(calls)
    assert all(item.receipt.state == "completed" for item in ok_results)
    assert ok_results[0].receipt.batch_state == "completed"
    print("W2-3 clean batch reports 'completed': PASS")


if __name__ == "__main__":
    asyncio.run(main())
