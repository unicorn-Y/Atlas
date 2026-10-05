"""ChannelManager tests — lifecycle, reconnect backoff, auth pause, inbound pipeline, delivery."""

from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace
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
async def test_stable_run_resets_backoff_ladder(tmp_path, monkeypatch):
    # Each fake run advances the supervisor's clock by 60ms before failing. With a
    # 50ms stable reset, every retry decision must use the first ladder step.
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(
        "atlas.channels.time", SimpleNamespace(monotonic=lambda: clock.now),
    )

    async def fail_after_virtual_stable_run(adapter):
        clock.now += float(adapter.config.get("run_seconds", 0.06))
        raise RuntimeError("run failed after stable window")

    monkeypatch.setattr(FakeAdapter, "_idle", fail_after_virtual_stable_run)
    attempts: list[int] = []
    delays: list[float] = []
    decisions_ready = asyncio.Event()
    real_compute_backoff = compute_backoff

    def record_attempt(attempt, *args, **kwargs):
        attempts.append(attempt)
        delay = real_compute_backoff(attempt, *args, **kwargs)
        delays.append(delay)
        if len(attempts) >= 2:
            decisions_ready.set()
        return delay

    monkeypatch.setattr("atlas.channels.compute_backoff", record_attempt)
    manager = make_manager(tmp_path, stable_reset_seconds=0.05)
    manager.configure(
        "fake", {"enabled": True, "behaviour": "run", "run_seconds": 0.06}, persist=False
    )
    await manager.start()
    try:
        await asyncio.wait_for(decisions_ready.wait(), timeout=2.0)
        assert len(attempts) >= 2, "expected to observe at least two reconnect decisions"
        assert attempts == [1] * len(attempts), f"stable runs did not reset backoff: {attempts}"
        assert delays == [0.02] * len(delays), f"stable runs used a later backoff delay: {delays}"
    finally:
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


# --- GAP-1: /credential secrets are read back by the webhook path ---------------------
#
# REST shape under test: PUT /accounts configures the channel WITHOUT a secret
# (the router strips secret fields), POST /credential stores it in the OS
# credential store, and handle_webhook must verify the HMAC against that stored
# value instead of answering 403 「该渠道未配置 webhook secret」.


class _DictStore:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)


def make_store():
    from atlas.channels.credentials import ChannelCredentialStore

    return ChannelCredentialStore(_DictStore(), environ={})  # isolate from real env/keyring


@pytest.mark.asyncio
async def test_handle_webhook_reads_secret_from_credential_store(tmp_path):
    from atlas.channels import WebhookError
    from atlas.channels.adapters.webhook import sign_payload

    seen: list = []

    async def dispatcher(event, agent_id):
        seen.append(event.event_id)

    manager = make_manager(tmp_path, dispatcher=dispatcher, credentials=make_store())
    manager.configure("fake", {"enabled": True}, persist=False)  # no secret in configs
    manager.credentials.set("fake", "secret", "stored-s3cret")  # what POST /credential does
    payload = json_dumps({"event_id": "w9", "chat_id": "cart-9", "text": "hi"})
    signed = {"x-atlas-signature": sign_payload("stored-s3cret", int(time.time()), payload)}
    result = await manager.handle_webhook("fake", signed, payload)
    assert result["ok"] is True
    assert await wait_for(lambda: seen == ["w9"])
    # a wrong-key signature is still rejected against the stored secret
    wrong = {"x-atlas-signature": sign_payload("not-the-secret", int(time.time()), payload)}
    with pytest.raises(WebhookError) as exc:
        await manager.handle_webhook("fake", wrong, payload)
    assert exc.value.status_code == 401
    # with no secret anywhere, unsigned ingress is still a 403
    manager.credentials.delete("fake", "secret")
    with pytest.raises(WebhookError) as exc:
        await manager.handle_webhook("fake", {}, payload)
    assert exc.value.status_code == 403
    await manager.stop()


@pytest.mark.asyncio
async def test_configured_secret_overrides_credential_store(tmp_path):
    from atlas.channels import WebhookError
    from atlas.channels.adapters.webhook import sign_payload

    manager = make_manager(tmp_path, credentials=make_store())
    manager.credentials.set("fake", "secret", "stored-s3cret")
    manager.configure("fake", {"enabled": True, "secret": "config-s3cret"}, persist=False)
    payload = json_dumps({"event_id": "w2", "chat_id": "cart-9"})
    good = {"x-atlas-signature": sign_payload("config-s3cret", int(time.time()), payload)}
    assert (await manager.handle_webhook("fake", good, payload))["ok"] is True
    stale = {"x-atlas-signature": sign_payload("stored-s3cret", int(time.time()), payload)}
    with pytest.raises(WebhookError) as exc:
        await manager.handle_webhook("fake", stale, payload)
    assert exc.value.status_code == 401  # explicit configs value keeps priority
    await manager.stop()


@pytest.mark.asyncio
async def test_started_adapter_receives_credential_store_secret(tmp_path):
    manager = make_manager(tmp_path, credentials=make_store())
    manager.credentials.set("fake", "secret", "stored-s3cret")
    await manager.start()
    assert await wait_for(lambda: "fake" in manager.adapters)
    assert manager.adapters["fake"].config.get("secret") == "stored-s3cret"
    await manager.stop()


# --- GAP-2: runtime configure starts/stops/reconnects only the changed channel --------


@pytest.mark.asyncio
async def test_runtime_enable_starts_adapter_and_disable_stops_it(tmp_path):
    manager = make_manager(tmp_path)
    manager.configure("fake", {"enabled": False}, persist=False)
    await manager.start()
    await asyncio.sleep(0.05)
    assert manager.adapters == {}  # disabled at boot: nothing running
    manager.configure("fake", {"enabled": True}, persist=False)
    assert await wait_for(lambda: "fake" in manager.adapters)
    assert await wait_for(lambda: manager.status()["channels"][0]["running"] is True)
    adapter = manager.adapters["fake"]
    # outbound works right after the runtime enable (approval receipts flow)
    await manager.send("fake", "100", "运行时启用后的第一封")
    assert await wait_for(lambda: adapter.sent == [("100", "运行时启用后的第一封", {})])
    stopped_before = FakeAdapter.total_stopped
    manager.configure("fake", {"enabled": False}, persist=False)
    assert await wait_for(lambda: "fake" not in manager.adapters)
    assert await wait_for(lambda: "fake" not in manager._supervisor_tasks)
    assert FakeAdapter.total_stopped >= stopped_before + 1
    status = manager.status()["channels"][0]
    assert status["running"] is False and status["enabled"] is False
    await manager.stop()


@pytest.mark.asyncio
async def test_runtime_config_change_reconnects_only_changed_channel(tmp_path):
    manager = make_manager(tmp_path)
    manager.register_channel("other", FakeAdapter)
    manager.configure("other", {"enabled": True}, persist=False)
    await manager.start()
    assert await wait_for(lambda: "fake" in manager.adapters and "other" in manager.adapters)
    fake_before, other_before = manager.adapters["fake"], manager.adapters["other"]
    manager.configure("fake", {"enabled": True, "url": "http://changed"}, persist=False)
    assert await wait_for(
        lambda: manager.adapters.get("fake") is not fake_before
        and manager.adapters["fake"].config.get("url") == "http://changed"
    )
    await asyncio.sleep(0.08)
    assert manager.adapters.get("other") is other_before  # untouched channel keeps its adapter
    assert FakeAdapter.total_started == 3  # fake+other at start, one targeted reconnect
    await manager.stop()


@pytest.mark.asyncio
async def test_noop_configure_keeps_running_adapter(tmp_path):
    manager = make_manager(tmp_path)
    await manager.start()
    assert await wait_for(lambda: "fake" in manager.adapters)
    adapter = manager.adapters["fake"]
    manager.configure("fake", {"enabled": True}, persist=False)  # identical values
    await asyncio.sleep(0.08)
    assert manager.adapters.get("fake") is adapter
    assert FakeAdapter.total_started == 1  # a write that changes nothing reconnects nothing
    await manager.stop()


def json_dumps(payload):
    return json.dumps(payload).encode("utf-8")
