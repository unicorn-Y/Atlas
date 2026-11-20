import asyncio

import pytest

from atlas.engine.kernel.inbox import DurableInbox
from atlas.engine.session_sync import read_session_events


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
        inbox.set_current_turn_event(turn_id)
        assert await inbox.peek("next-turn") is None
        assert (await inbox.peek("next-step")).event_id == step_id
        inbox.set_current_turn_event(None)
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


@pytest.mark.unit
def test_inbox_enqueue_request_key_is_durable_idempotent_and_rejects_payload_reuse(tmp_path):
    async def scenario():
        home = tmp_path / "engine"
        inbox = DurableInbox(home, "session-idempotent-inbox")
        event_id = await inbox.inject("  exact prompt  ", lane="next-turn", request_id="client-req-1")
        assert await inbox.inject("exact prompt", lane="next-turn", request_id="client-req-1") == event_id

        recovered = DurableInbox(home, "session-idempotent-inbox")
        await recovered.restore()
        assert await recovered.inject("exact prompt", lane="next-turn", request_id="client-req-1") == event_id
        pending = await recovered.peek("next-turn")
        assert pending is not None and pending.event_id == event_id

        with pytest.raises(ValueError, match="request id.*different payload"):
            await recovered.inject("changed prompt", lane="next-turn", request_id="client-req-1")
        with pytest.raises(ValueError, match="request id.*different payload"):
            await recovered.inject("exact prompt", lane="next-step", request_id="client-req-1")

        assert await recovered.ack(event_id, lane="next-turn") is True
        after_consumed = DurableInbox(home, "session-idempotent-inbox")
        await after_consumed.restore()
        assert await after_consumed.inject("exact prompt", lane="next-turn", request_id="client-req-1") == event_id
        assert await after_consumed.peek("next-turn") is None

        events = await asyncio.to_thread(
            read_session_events, home, "session-idempotent-inbox", after_seq=0, limit=100,
        )
        enqueued = [event for event in events if event.get("event_type") == "inbox.enqueued"]
        assert len(enqueued) == 1
        assert enqueued[0]["payload"].get("request_id") == "client-req-1"

    asyncio.run(scenario())


@pytest.mark.unit
def test_inbox_persists_worker_start_identity_and_restores_quarantine(tmp_path):
    async def scenario():
        home = tmp_path / "engine"
        inbox = DurableInbox(home, "session-worker-start")
        event_id, created = await inbox.inject_with_receipt(
            "work exactly once", lane="next-turn", request_id="worker-req-1",
        )
        assert created is True
        assert await inbox.mark_started(
            event_id, lane="next-turn", run_id="worker-run-1",
        ) is True

        duplicate_id, duplicate_created = await inbox.inject_with_receipt(
            "work exactly once", lane="next-turn", request_id="worker-req-1",
        )
        assert duplicate_id == event_id
        assert duplicate_created is False

        restored = DurableInbox(home, "session-worker-start")
        item = await restored.peek("next-turn")
        assert item is not None
        assert item.event_id == event_id
        assert item.started_run_id == "worker-run-1"
        assert await restored.mark_started(
            event_id, lane="next-turn", run_id="different-run",
        ) is False

    asyncio.run(scenario())


@pytest.mark.unit
def test_inbox_restores_request_identity_and_cancels_only_unstarted_items(tmp_path):
    async def scenario():
        home = tmp_path / "engine"
        inbox = DurableInbox(home, "session-task-cancel")
        queued_id, _ = await inbox.inject_with_receipt(
            "queued work", lane="next-turn", request_id="task-queued",
        )
        started_id, _ = await inbox.inject_with_receipt(
            "started work", lane="next-turn", request_id="task-started",
        )
        assert await inbox.mark_started(
            started_id, lane="next-turn", run_id="run-started",
        ) is True

        restored = DurableInbox(home, "session-task-cancel")
        await restored.restore()
        queued = await restored.peek("next-turn")
        assert queued is not None and queued.request_id == "task-queued"
        started = await restored.peek("next-turn")
        assert started is not None and started.event_id == queued_id
        assert await restored.cancel(queued_id, lane="next-turn") is True
        assert await restored.cancel(started_id, lane="next-turn") is False
        remaining = await restored.peek("next-turn")
        assert remaining is not None
        assert remaining.event_id == started_id
        assert remaining.request_id == "task-started"
        assert remaining.started_run_id == "run-started"

        events = await asyncio.to_thread(
            read_session_events, home, "session-task-cancel", after_seq=0, limit=100,
        )
        cancelled = [event for event in events if event.get("event_type") == "inbox.cancelled"]
        assert len(cancelled) == 1
        assert cancelled[0]["payload"].get("request_id") == "task-queued"

    asyncio.run(scenario())
