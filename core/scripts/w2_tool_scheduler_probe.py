"""Probe ordered fan-out, fail-fast cancellation, and terminal receipts."""
from __future__ import annotations

import asyncio

from atlas.kernel.tools import ToolScheduler


async def main() -> None:
    cancelled: list[str] = []

    async def dispatch(call_id: str, name: str, args: dict) -> dict:
        if args.get("fail"):
            await asyncio.sleep(0.01)
            return {"is_error": True, "error": "fixture failure"}
        try:
            await asyncio.sleep(1)
            return {"data": call_id}
        except asyncio.CancelledError:
            cancelled.append(call_id)
            raise

    scheduler = ToolScheduler(dispatch, max_concurrency=3)
    calls = [{"id": "a", "function": {"name": "read_file", "arguments": "{}"}},
             {"id": "b", "function": {"name": "read_file", "arguments": '{"fail":true}'}},
             {"id": "c", "function": {"name": "read_file", "arguments": "{}"}}]
    results = await scheduler.run(calls)
    assert [item.call_id for item in results] == ["a", "b", "c"]
    assert [item.receipt.state for item in results] == ["cancelled", "failed", "cancelled"]
    assert set(cancelled) == {"a", "c"}
    print("W2-1 ordered receipts and sibling cancellation: PASS")


if __name__ == "__main__":
    asyncio.run(main())
