import asyncio

import pytest

from atlas.engine.kernel.inbox import DurableInbox


@pytest.mark.unit
def test_inbox_uses_ordered_lanes_and_inject_does_not_wake(tmp_path):
    async def scenario():
        wake = asyncio.Event()
        inbox = DurableInbox(tmp_path / "engine", "session-inbox")
        await inbox.restore()
        step_id = await inbox.inject("step note", lane="next-step")
        turn_id = await inbox.inject("turn note", lane="next-turn")

        assert not wake.is_set()
        assert (await inbox.peek("next-turn")).event_id == turn_id

        recovered = DurableInbox(tmp_path / "engine", "session-inbox")
        await recovered.restore()
        assert (await recovered.peek("next-step")).event_id == step_id
        assert await recovered.ack(step_id, lane="next-step") is True
        assert await recovered.ack(turn_id, lane="next-turn") is True
        assert await recovered.take("next-turn") is None

        third = DurableInbox(tmp_path / "engine", "session-inbox")
        await third.restore()
        assert await third.take("next-step") is None

    asyncio.run(scenario())
