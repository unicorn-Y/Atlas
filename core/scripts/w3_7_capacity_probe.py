"""Small executable proof of W3-7 capacity queueing and its three limits."""

from __future__ import annotations

import asyncio

from atlas.agent.subagent_capacity import SubagentCapacity


async def main() -> None:
    capacity = SubagentCapacity(max_concurrent=1, max_children_per_parent=1, max_spawn_depth=1)
    first = await capacity.acquire(parent_id="root", depth=1)
    waiting = asyncio.create_task(capacity.acquire(parent_id="root", depth=1))
    await asyncio.sleep(0)
    assert capacity.active_count == 1 and capacity.waiting_count == 1
    await capacity.release(first)
    second = await asyncio.wait_for(waiting, timeout=1)
    await capacity.release(second)

    too_deep = asyncio.create_task(capacity.acquire(parent_id="root", depth=2))
    await asyncio.sleep(0)
    assert not too_deep.done() and capacity.waiting_count == 1
    await capacity.set_limits(max_spawn_depth=2)
    third = await asyncio.wait_for(too_deep, timeout=1)
    await capacity.release(third)
    print("W3-7 CAPACITY PROBE PASS: concurrent, per-parent, and depth limits queue FIFO")


if __name__ == "__main__":
    asyncio.run(main())
