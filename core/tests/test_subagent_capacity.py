import asyncio

import pytest

from atlas.agent.subagent_capacity import SubagentCapacity


@pytest.mark.asyncio
async def test_global_limit_change_releases_fifo_waiters():
    capacity = SubagentCapacity(max_concurrent=1)
    first = await capacity.acquire(parent_id="one", depth=1)
    second_task = asyncio.create_task(capacity.acquire(parent_id="two", depth=1))
    await asyncio.sleep(0)
    assert capacity.waiting_count == 1

    await capacity.set_limits(max_concurrent=2)
    second = await asyncio.wait_for(second_task, timeout=1)
    assert capacity.active_count == 2

    await capacity.set_limits(max_concurrent=1)
    third_task = asyncio.create_task(capacity.acquire(parent_id="three", depth=1))
    await asyncio.sleep(0)
    assert capacity.waiting_count == 1
    await capacity.release(first)
    await capacity.release(second)
    third = await asyncio.wait_for(third_task, timeout=1)
    await capacity.release(third)


def test_capacity_limits_reject_non_positive_and_non_integer_values():
    with pytest.raises(ValueError):
        SubagentCapacity(max_concurrent=0)
    with pytest.raises(ValueError):
        SubagentCapacity(max_concurrent=1.5)
