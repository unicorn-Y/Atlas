"""ChannelManager tests — lifecycle, reconnect backoff, auth pause, inbound pipeline, delivery."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, ClassVar

import pytest

from atlas.channels import AdapterAuthError, ChannelManager, compute_backoff
from atlas.channels.contract import ChannelAdapter, MessageEvent, SendResult


class FakeAdapter(ChannelAdapter):
    name = "fake"

    total_started: ClassVar[int] = 0
    total_stopped: ClassVar[int] = 0
    instances: ClassVar[list[FakeAdapter]] = []

    def __init__(self, config, dispatcher):
        super().__init__(config, dispatcher)
        self.sent: list[tuple] = []
        self.worker: asyncio.Task | None = None
        self.events: list[MessageEvent] = []
        type(self).instances.append(self)

    @property
    def worker_task(self) -> asyncio.Task | None:
        return self.worker

    async def start(self):
        type(self).total_started += 1
        behaviour = self.config.get("behaviour", "run")
        if behaviour == "auth_fail":
            raise AdapterAuthError("令牌无效")
        if behaviour == "crash":
            raise RuntimeError("boom")
        self.worker = asyncio.create_task(self._idle())

    async def _idle(self):
        run_seconds = float(self.config.get("run_seconds", 0))
        if run_seconds:
            await asyncio.sleep(run_seconds)
            raise RuntimeError("run failed after stable window")
        await asyncio.Event().wait()

    async def stop(self):
        type(self).total_stopped += 1
        worker, self.worker = self.worker, None
        if worker is not None:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)

    async def send(self, chat_id, content, *, reply_to="", attachments=None, metadata=None):
        self.sent.append((chat_id, content, dict(metadata or {})))
        return SendResult(ok=True, message_id=f"m-{len(self.sent)}")

    def emit(self, event: MessageEvent):
        self.events.append(event)
        return self._dispatch(event)

    @classmethod
    def reset(cls):
        cls.total_started = 0
        cls.total_stopped = 0
        cls.instances = []


def make_event(event_id, *, sender="42", chat_id="100", is_group=False, channel="fake"):
    return MessageEvent(
        channel=channel, account="", event_id=event_id, chat_id=chat_id,
        sender_id=sender, is_group=is_group, text="hello",
    )


def make_manager(tmp_path, *, dispatcher=None, **kwargs):
    defaults = dict(
        backoff_initial=0.02, backoff_factor=2.0, backoff_cap=0.2, backoff_jitter=0.0,
        delivery_interval=0.02,
    )
    defaults.update(kwargs)
    manager = ChannelManager(db_path=tmp_path / "channels.db", dispatcher=dispatcher, **defaults)
    manager.register_channel("fake", FakeAdapter)
    manager.configure("fake", {"enabled": True}, persist=False)
    return manager


async def wait_for(condition, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        await asyncio.sleep(0.01)
    return condition()


@pytest.fixture(autouse=True)
def _reset_fake_adapter():
    FakeAdapter.reset()
    yield
    FakeAdapter.reset()


# --- compute_backoff --------------------------------------------------------------


def test_compute_backoff_ladder_with_cap():
    values = [
        compute_backoff(n, initial=1.0, factor=2.0, cap=30.0, jitter=0.0) for n in range(1, 8)
    ]
    assert values == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0]


def test_compute_backoff_jitter_stays_bounded():
    for _ in range(50):
        value = compute_backoff(3, initial=1.0, factor=2.0, cap=30.0, jitter=0.5)
        assert 4.0 <= value <= 6.0


# --- lifecycle --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_stop_runs_enabled_adapter_once(tmp_path):
    manager = make_manager(tmp_path)
    await manager.start()
    assert await wait_for(lambda: "fake" in manager.adapters)
    assert await wait_for(lambda: manager.status()["channels"][0]["running"] is True)
    await asyncio.sleep(0.08)
    assert FakeAdapter.total_started == 1  # stable run: no reconnect churn
    await manager.stop()
    assert FakeAdapter.total_stopped >= 1
    assert manager.status()["channels"][0]["running"] is False


@pytest.mark.asyncio
async def test_disabled_channel_never_starts(tmp_path):
    manager = make_manager(tmp_path)
    manager.configure("fake", {"enabled": False}, persist=False)
    await manager.start()
    await asyncio.sleep(0.05)
    assert manager.adapters == {}
    await manager.stop()


@pytest.mark.asyncio
async def test_auth_failure_pauses_without_retry(tmp_path):
    manager = make_manager(tmp_path)
    manager.configure("fake", {"enabled": True, "behaviour": "auth_fail"}, persist=False)
    await manager.start()
    assert await wait_for(lambda: manager.status()["channels"][0]["paused"] is True)
    started = FakeAdapter.total_started
    await asyncio.sleep(0.1)
    status = manager.status()["channels"][0]
    assert FakeAdapter.total_started == started  # auth failures pause, never retry
    assert status["running"] is False and "令牌无效" in status["last_error"]
    await manager.stop()


@pytest.mark.asyncio
async def test_transient_failure_reconnects_with_backoff(tmp_path):
    manager = make_manager(tmp_path)
    manager.configure("fake", {"enabled": True, "behaviour": "crash"}, persist=False)
    await manager.start()
    await asyncio.sleep(0.15)
    assert FakeAdapter.total_started >= 2  # supervisor kept retrying
    assert "boom" in manager.status()["channels"][0]["last_error"]
    await manager.stop()


@pytest.mark.asyncio
async def test_stable_run_resets_backoff_ladder(tmp_path):
    # each run stays stable 60ms then dies; with a 50ms stable-reset the ladder
    # never grows past the initial 20ms, so restarts keep coming quickly.
    manager = make_manager(tmp_path, stable_reset_seconds=0.05)
    manager.configure(
        "fake", {"enabled": True, "behaviour": "run", "run_seconds": 0.06}, persist=False
    )
    await manager.start()
    await asyncio.sleep(0.4)
    assert FakeAdapter.total_started >= 5  # would be ~3 if the ladder kept growing
    await manager.stop()


# --- inbound pipeline ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_inbound_event_flows_through_gating_routing_to_dispatcher(tmp_path):
    seen: list = []

    async def dispatcher(event, agent_id):
        seen.append((event.event_id, agent_id))

    manager = make_manager(tmp_path, dispatcher=dispatcher)
    manager.set_bindings(
        [{"agent_id": "main", "channel": "fake", "account": "*", "peer_id": "100"}]
    )
    manager.set_policy("fake", {"dm_policy": "allowlist", "dm_allowlist": ["42"]})
    await manager.start()
    assert await wait_for(lambda: "fake" in manager.adapters)
    adapter = manager.adapters["fake"]
    await adapter.emit(make_event("m1", sender="42"))
    await adapter.emit(make_event("m2", sender="blocked"))
    await adapter.emit(make_event("m1", sender="42"))  # duplicate
    assert await wait_for(lambda: len(seen) == 1)
    await asyncio.sleep(0.05)
    await manager.stop()
    assert seen == [("m1", "main")]
    status = manager.status()["channels"][0]
    assert status["counts"]["inbound_pending"] == 0
    assert status["counts"]["dropped"] >= 1
    assert manager.ingress.has_tombstone("fake", "", "m1")


@pytest.mark.asyncio
async def test_without_dispatcher_events_stay_queued(tmp_path):
    manager = make_manager(tmp_path)
    await manager.start()
    assert await wait_for(lambda: "fake" in manager.adapters)
    await manager.adapters["fake"].emit(make_event("m1"))
    assert await wait_for(lambda: manager.ingress.pending_count() == 1)
    await asyncio.sleep(0.05)
    assert manager.ingress.pending_count() == 1  # not claimed, waiting for wave 2
    await manager.stop()


@pytest.mark.asyncio
async def test_no_route_fails_closed_when_multi_agent_bindings(tmp_path):
    seen: list = []

    async def dispatcher(event, agent_id):
        seen.append(event.event_id)

    manager = make_manager(tmp_path, dispatcher=dispatcher)
    manager.set_bindings([
        {"agent_id": "a", "channel": "fake", "peer_id": "1"},
        {"agent_id": "b", "channel": "fake", "peer_id": "2"},
    ])
    await manager.start()
    assert await wait_for(lambda: "fake" in manager.adapters)
    await manager.adapters["fake"].emit(make_event("m9", chat_id="3"))
    assert await wait_for(lambda: manager.ingress.pending_count() == 0)
    await manager.stop()
    assert seen == []


@pytest.mark.asyncio
async def test_dispatcher_failure_requeues_event(tmp_path):
    attempts: list = []

    async def dispatcher(event, agent_id):
        attempts.append(event.event_id)
        raise RuntimeError("agent exploded")

    manager = make_manager(tmp_path, dispatcher=dispatcher)
    await manager.start()
    assert await wait_for(lambda: "fake" in manager.adapters)
    await manager.adapters["fake"].emit(make_event("m1"))
    await asyncio.sleep(0.1)
    await manager.stop()
    # ingress retry backoff is 1s, so within the window it is only attempted once
    assert attempts.count("m1") == 1
    assert manager.ingress.pending_count() == 1


# --- outbound delivery ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_goes_through_delivery_queue(tmp_path):
    manager = make_manager(tmp_path)
    await manager.start()
    assert await wait_for(lambda: "fake" in manager.adapters)
    adapter = manager.adapters["fake"]
    key = await manager.send("fake", "100", "你好")
    assert await wait_for(lambda: adapter.sent != [])
    await manager.stop()
    assert adapter.sent == [("100", "你好", {})]
    row = manager.delivery.get(key)
    assert row.status == "delivered" and row.metadata.get("message_id") == "m-1"


@pytest.mark.asyncio
async def test_send_is_idempotent(tmp_path):
    manager = make_manager(tmp_path)
    await manager.start()
    assert await wait_for(lambda: "fake" in manager.adapters)
    adapter = manager.adapters["fake"]
    key1 = await manager.send("fake", "100", "你好")
    key2 = await manager.send("fake", "100", "你好")
    assert key1 == key2
    assert await wait_for(lambda: len(adapter.sent) == 1)
    await asyncio.sleep(0.05)
    await manager.stop()
    assert len(adapter.sent) == 1  # duplicate enqueue never double-sends


@pytest.mark.asyncio
async def test_send_failure_marks_retry_with_backoff(tmp_path):
    manager = make_manager(tmp_path)
    await manager.start()
    assert await wait_for(lambda: "fake" in manager.adapters)
    adapter = manager.adapters["fake"]

    async def failing_send(*args, **kwargs):
        return SendResult(ok=False, error="rate limited", retryable=True)

    adapter.send = failing_send  # type: ignore[method-assign]
    key = await manager.send("fake", "100", "hi")
    assert await wait_for(lambda: manager.delivery.get(key).attempts == 1)
    await asyncio.sleep(0.05)
    await manager.stop()
    row = manager.delivery.get(key)
    assert row.status == "pending" and row.attempts == 1
    assert row.next_retry_at > time.time() + 20  # first retry delay is 30s


@pytest.mark.asyncio
async def test_send_test_message_uses_test_metadata(tmp_path):
    manager = make_manager(tmp_path)
    await manager.start()
    assert await wait_for(lambda: "fake" in manager.adapters)
    adapter = manager.adapters["fake"]
    await manager.send_test("fake", "100")
    assert await wait_for(lambda: adapter.sent != [])
    await manager.stop()
    assert adapter.sent[0][2] == {"test": True}


# --- H6: delivery failures stay visible and never kill the pump ---------------------


@pytest.mark.asyncio
async def test_delivery_pump_survives_queue_failure_and_keeps_delivering(
    tmp_path, caplog,
):
    """A crashed cycle in the delivery pump used to strand every queued reply
    silently; now the exception is logged and the next interval recovers."""
    import logging

    manager = make_manager(tmp_path)
    await manager.start()
    assert await wait_for(lambda: "fake" in manager.adapters)
    adapter = manager.adapters["fake"]
    original_claim = manager.delivery.claim_due
    calls = {"n": 0}

    def failing_claim(*args, **kwargs):
        calls["n"] += 1
        raise RuntimeError("injected queue failure")

    with caplog.at_level(logging.ERROR):
        manager.delivery.claim_due = failing_claim  # type: ignore[method-assign]
        await manager.send("fake", "100", "泵崩溃前入队")
        assert await wait_for(lambda: calls["n"] >= 1)
        assert "injected queue failure" in caplog.text

        manager.delivery.claim_due = original_claim
        await manager.send("fake", "100", "泵恢复后的信")
        assert await wait_for(
            lambda: any("泵恢复后的信" in item[1] for item in adapter.sent), timeout=2.0,
        )
    await manager.stop()


@pytest.mark.asyncio
async def test_delivery_failure_notice_handler_error_does_not_break_pump(
    tmp_path, caplog,
):
    """The recovery-notice handler itself failing is logged; the delivery loop
    keeps running and later messages still reach the channel."""
    import logging

    manager = make_manager(tmp_path)

    async def broken_handler(record, message):
        raise RuntimeError("notice handler exploded")

    manager.set_delivery_failure_handler(broken_handler)
    await manager.start()
    assert await wait_for(lambda: "fake" in manager.adapters)
    adapter = manager.adapters["fake"]
    healthy = adapter

    async def failing_send(*args, **kwargs):
        raise RuntimeError("injected channel send failure")

    with caplog.at_level(logging.ERROR):
        healthy.send = failing_send  # type: ignore[method-assign]
        await manager.send("fake", "100", "必失败的一封")
        assert await wait_for(
            lambda: "渠道发送失败通知未送达" in caplog.text
            or "notice handler exploded" in caplog.text,
        )
        # The pump is still alive: a healthy adapter receives the next message.
        del healthy.send  # restore the real bound method
        await manager.send("fake", "100", "恢复后的一封")
        assert await wait_for(
            lambda: any("恢复后的一封" in item[1] for item in healthy.sent), timeout=2.0,
        )
    await manager.stop()


# --- webhook ingress --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_webhook_rejects_unsigned_and_bad_signature(tmp_path):
    from atlas.channels import WebhookError

    manager = make_manager(tmp_path)
    manager.configure("fake", {"enabled": True, "secret": "s3cret"}, persist=False)
    body = json_dumps({"event_id": "w1", "chat_id": "100"})
    with pytest.raises(WebhookError) as exc:
        await manager.handle_webhook("fake", {}, body)
    assert exc.value.status_code == 401
    bad_sig = {"x-atlas-signature": "t=1,v1=deadbeef"}
    with pytest.raises(WebhookError):
        await manager.handle_webhook("fake", bad_sig, body)


@pytest.mark.asyncio
async def test_handle_webhook_good_signature_queues_event(tmp_path):
    seen: list = []

    async def dispatcher(event: MessageEvent, agent_id):
        seen.append(event.event_id)

    from atlas.channels.adapters.webhook import sign_payload

    manager = make_manager(tmp_path, dispatcher=dispatcher)
    manager.configure("fake", {"enabled": True, "secret": "s3cret"}, persist=False)
    payload = json_dumps({"event_id": "w1", "chat_id": "cart-9", "text": "hi"})
    signed = {"x-atlas-signature": sign_payload("s3cret", int(time.time()), payload)}
    result: dict[str, Any] = await manager.handle_webhook("fake", signed, payload)
    assert result["ok"] is True
    assert await wait_for(lambda: seen == ["w1"])
    await manager.stop()


@pytest.mark.asyncio
async def test_handle_webhook_without_secret_rejects_unsigned(tmp_path):
    from atlas.channels import WebhookError

    manager = make_manager(tmp_path)
    body = json_dumps({"event_id": "w1", "chat_id": "100"})
    with pytest.raises(WebhookError) as exc:
        await manager.handle_webhook("fake", {}, body)
    assert exc.value.status_code == 403
    # explicit opt-out allows unsigned ingress (internal sources)
    manager.configure("fake", {"allow_unsigned": True}, persist=False)
    result = await manager.handle_webhook("fake", {}, body)
    assert result["ok"] is True
    await manager.stop()


def json_dumps(payload):
    return json.dumps(payload).encode("utf-8")
