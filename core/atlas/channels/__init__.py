"""Channel gateway — the single owner of channel lifecycle, routing and queues.

Every adapter implements the frozen :mod:`atlas.channels.contract`. The gateway
(:class:`ChannelManager`):

- registers adapter factories (:meth:`register_channel`) and starts/stops every
  enabled channel;
- reconciles runtime :meth:`ChannelManager.configure` changes per channel: an
  enabled/disabled/url edit restarts only that channel's supervisor;
- reads channel secrets from configs first, then the credential store
  (:mod:`atlas.channels.credentials`) so ``POST /api/channels/credential``
  values work for both webhook verification and outbound signing;
- supervises each adapter with reconnect backoff (1s ×2, cap 30s, jittered) and
  pauses on unrecoverable :class:`AdapterAuthError`;
- funnels inbound events through the durable ingress queue
  (:mod:`atlas.channels.ingress`), then gating (:mod:`atlas.channels.gating`)
  and route resolution (:mod:`atlas.channels.routing`) before handing the event
  to the injected dispatcher (Wave 2 wires the real agent dispatch);
- sends outbound traffic through the durable delivery queue
  (:mod:`atlas.channels.delivery`).

Adapters never import agent code; the dispatcher seam is the only outbound edge.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from atlas.channels.contract import (
    Attachment,
    ChannelAdapter,
    ChannelAdapterError,
    MessageEvent,
)
from atlas.channels.credentials import ChannelCredentialStore, channel_credentials
from atlas.channels.delivery import DeliveryQueue, OutboundRecord
from atlas.channels.gating import (
    MentionFacts,
    MentionPolicy,
    gate_dm,
    gate_group,
    gate_mention,
)
from atlas.channels.ingress import IngressQueue
from atlas.channels.routing import resolve_route

logger = logging.getLogger(__name__)

#: Gateway-side dispatch seam: routed event + resolved agent (Wave 2 wiring).
DispatchHandler = Callable[[MessageEvent, str | None], Awaitable[None]]
AdapterFactory = Callable[
    [dict[str, Any], Callable[[MessageEvent], Awaitable[None]]], ChannelAdapter
]

DEFAULT_POLICY: dict[str, Any] = {
    "dm_policy": "open",
    "dm_allowlist": ["*"],
    "allow_when_empty": True,
    "group_policy": "open",
    "group_allowlist": [],
    "require_mention": False,
}


class AdapterAuthError(ChannelAdapterError):
    """Unrecoverable credential/configuration failure — the channel is paused."""


class WebhookError(ChannelAdapterError):
    """Webhook request rejected (bad signature / bad payload)."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


def compute_backoff(
    attempt: int,
    *,
    initial: float = 1.0,
    factor: float = 2.0,
    cap: float = 30.0,
    jitter: float = 0.25,
    rng: random.Random | None = None,
) -> float:
    """OpenClaw reconnect backoff: ``min(cap, initial·factor^(n-1))`` plus jitter."""
    base = min(cap, initial * (factor ** max(0, attempt - 1)))
    if jitter <= 0:
        return base
    roll = rng.random() if rng is not None else random.random()
    return base * (1.0 + jitter * roll)


@dataclass(slots=True)
class ChannelState:
    name: str
    enabled: bool = False
    running: bool = False
    paused: bool = False
    last_error: str = ""
    received: int = 0
    delivered: int = 0
    dropped: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


class ChannelManager:
    def __init__(
        self,
        *,
        db_path: str | Path,
        config_path: str | Path | None = None,
        dispatcher: DispatchHandler | None = None,
        credentials: ChannelCredentialStore | None = None,
        backoff_initial: float = 1.0,
        backoff_factor: float = 2.0,
        backoff_cap: float = 30.0,
        backoff_jitter: float = 0.25,
        stable_reset_seconds: float = 30.0,
        delivery_interval: float = 0.5,
        rng: random.Random | None = None,
    ) -> None:
        self.ingress = IngressQueue(db_path)
        self.delivery = DeliveryQueue(db_path)
        self.config_path = Path(config_path) if config_path else None
        self.credentials = credentials or channel_credentials
        self.registry: dict[str, AdapterFactory] = {}
        self.configs: dict[str, dict[str, Any]] = {}
        self.adapters: dict[str, ChannelAdapter] = {}
        self.states: dict[str, ChannelState] = {}
        self.bindings: list[dict[str, Any]] = []
        self.agent_ids: list[str] | None = None
        self.policies: dict[str, dict[str, Any]] = {}
        self._dispatcher = dispatcher
        self._control_handler: Callable[[MessageEvent], Awaitable[bool]] | None = None
        self._delivery_failure_handler: (
            Callable[[OutboundRecord, str], Awaitable[None]] | None
        ) = None
        self._backoff = (backoff_initial, backoff_factor, backoff_cap, backoff_jitter)
        self._stable_reset_seconds = stable_reset_seconds
        self._delivery_interval = delivery_interval
        self._rng = rng
        self._stopping = False
        self._started = False
        self._supervisor_tasks: dict[str, asyncio.Task[None]] = {}
        self._reconcile_task: asyncio.Task[None] | None = None
        self._pending_reconcile: set[str] = set()
        # Config snapshot each running adapter was constructed with — lets the
        # runtime reconcile tell "already running this exact config" apart from
        # "config changed, reconnect this one channel".
        self._adapter_configs: dict[str, dict[str, Any]] = {}
        self._delivery_task: asyncio.Task[None] | None = None
        self._drain_task: asyncio.Task[None] | None = None
        self._drain_requested = False
        self._drain_lock = asyncio.Lock()
        if self.config_path is not None and self.config_path.exists():
            self._load_configs()

    # -- registration / configuration -------------------------------------------

    def register_channel(self, name: str, factory: AdapterFactory) -> None:
        """Add an adapter factory; ``factory(config, dispatcher) -> ChannelAdapter``."""
        self.registry[str(name)] = factory
        self.states.setdefault(str(name), ChannelState(str(name)))

    def configure(
        self, name: str, config: dict[str, Any], *, persist: bool = True
    ) -> dict[str, Any]:
        """Merge non-secret channel config (secrets go through credentials).

        While the gateway is running, a change to the channel's connection
        shape (enabled flag or any other adapter-visible value) incrementally
        restarts only that channel's supervisor/adapter; other channels keep
        running untouched and a write that changes nothing reconnects nothing.
        Before ``start()`` (or after ``stop()``) there is nothing to reconcile:
        ``start()`` reads the already-updated config.
        """
        previous = dict(self.configs.get(name) or {})
        current = dict(previous)
        current.update(config or {})
        self.configs[name] = current
        state = self._state(name)
        state.enabled = bool(current.get("enabled", False))
        if self._started and self._connection_changed(previous, current):
            self._schedule_reconcile(name)
        if persist:
            self._save_configs()
        return dict(current)

    @staticmethod
    def _connection_changed(previous: dict[str, Any], current: dict[str, Any]) -> bool:
        """Whether the adapter must be (re)started to apply the new config."""
        if bool(previous.get("enabled", False)) != bool(current.get("enabled", False)):
            return True
        if not current.get("enabled", False):
            return False
        return any(
            key != "enabled" and previous.get(key) != value
            for key, value in current.items()
        )

    def _schedule_reconcile(self, name: str) -> None:
        """Queue one incremental supervisor restart for a configured channel.

        Safe under deferred startup: the task only exists while the gateway is
        started, and a sync caller without a running loop keeps the config
        change (it still applies on the channel's next natural reconnect).
        """
        self._pending_reconcile.add(name)
        if self._reconcile_task is not None and not self._reconcile_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._pending_reconcile.discard(name)
            logger.warning(
                "渠道 %s 配置变更落在无事件循环的调用里，将在下次重连时生效", name
            )
            return
        self._reconcile_task = loop.create_task(
            self._reconcile_loop(), name="atlas-channel-reconcile"
        )

    async def _reconcile_loop(self) -> None:
        while self._pending_reconcile and not self._stopping:
            name = next(iter(self._pending_reconcile))
            self._pending_reconcile.discard(name)
            await self._reconcile_channel(name)

    async def _reconcile_channel(self, name: str) -> None:
        """Start/stop/restart at most one channel's supervisor — never the gateway."""
        if name not in self.registry:
            return
        config = dict(self.configs.get(name) or {})
        enabled = bool(config.get("enabled", False))
        if (
            not self._stopping
            and enabled
            and name in self._supervisor_tasks
            and self._adapter_configs.get(name) == config
        ):
            return  # already running exactly this config
        old = self._supervisor_tasks.get(name)
        if old is not None:
            old.cancel()
            await asyncio.gather(old, return_exceptions=True)
            self._supervisor_tasks.pop(name, None)
        stale = self.adapters.pop(name, None)
        if stale is not None:
            with contextlib.suppress(Exception):
                await stale.stop()
        self._adapter_configs.pop(name, None)
        if self._stopping or not self._started or not enabled:
            return
        self._supervisor_tasks[name] = asyncio.create_task(
            self._supervise(name), name=f"atlas-channel-supervisor-{name}"
        )

    def set_policy(self, channel: str, policy: dict[str, Any]) -> None:
        merged = dict(DEFAULT_POLICY)
        merged.update(self.policies.get(channel) or {})
        merged.update(policy or {})
        self.policies[channel] = merged

    def set_bindings(self, bindings: list[dict[str, Any]]) -> None:
        self.bindings = list(bindings or [])

    def set_agent_ids(self, agent_ids: list[str] | None) -> None:
        self.agent_ids = list(agent_ids) if agent_ids is not None else None

    def set_dispatcher(self, dispatcher: DispatchHandler | None) -> None:
        self._dispatcher = dispatcher

    def set_control_handler(self, handler: Callable[[MessageEvent], Awaitable[bool]]) -> None:
        """Handle admitted approval replies even when a run occupies the drain."""
        self._control_handler = handler

    def set_delivery_failure_handler(
        self, handler: Callable[[OutboundRecord, str], Awaitable[None]],
    ) -> None:
        self._delivery_failure_handler = handler

    async def _report_delivery_failure(self, record: OutboundRecord, detail: str) -> None:
        if self._delivery_failure_handler is None:
            return
        try:
            await self._delivery_failure_handler(record, detail)
        except Exception:
            logger.exception("渠道发送失败通知未送达")

    def _state(self, name: str) -> ChannelState:
        return self.states.setdefault(name, ChannelState(name))

    def _load_configs(self) -> None:
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(data, dict):
            for name, config in data.items():
                if isinstance(config, dict):
                    self.configs[name] = dict(config)
                    self._state(name).enabled = bool(config.get("enabled", False))

    def _save_configs(self) -> None:
        if self.config_path is None:
            return
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(self.configs, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # -- lifecycle ----------------------------------------------------------------

    async def start(self) -> None:
        self._stopping = False
        self._started = True
        self._pending_reconcile.clear()
        self._reconcile_task = None
        for name in self.registry:
            config = self.configs.get(name) or {}
            state = self._state(name)
            state.enabled = bool(config.get("enabled", False))
            state.paused = False
            if not state.enabled:
                continue
            self._supervisor_tasks[name] = asyncio.create_task(
                self._supervise(name), name=f"atlas-channel-supervisor-{name}"
            )
        self._delivery_task = asyncio.create_task(
            self._delivery_loop(), name="atlas-channel-delivery"
        )

    async def stop(self) -> None:
        self._stopping = True
        self._started = False
        self._pending_reconcile.clear()
        # Stop the reconciler first so it cannot spawn a supervisor after the
        # snapshot below (deferred startup/shutdown safety).
        if self._reconcile_task is not None and not self._reconcile_task.done():
            self._reconcile_task.cancel()
            await asyncio.gather(self._reconcile_task, return_exceptions=True)
        self._reconcile_task = None
        tasks = list(self._supervisor_tasks.values())
        if self._delivery_task is not None:
            tasks.append(self._delivery_task)
        if self._drain_task is not None:
            tasks.append(self._drain_task)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._supervisor_tasks.clear()
        self._delivery_task = None
        self._drain_task = None
        for adapter in list(self.adapters.values()):
            with contextlib.suppress(Exception):
                await adapter.stop()
        self.adapters.clear()
        self._adapter_configs.clear()

    async def _supervise(self, name: str) -> None:
        initial, factor, cap, jitter = self._backoff
        state = self._state(name)
        attempt = 0
        while not self._stopping:
            config = dict(self.configs.get(name) or {})
            if not config.get("secret"):
                stored = self._credential_secret(name)
                if stored:
                    # Secrets live in the credential store, not configs: hand
                    # the adapter the same effective secret handle_webhook uses.
                    config["secret"] = stored
            self._adapter_configs[name] = dict(config)
            factory = self.registry.get(name)
            if factory is None:
                return
            adapter = factory(config, self._event_sink())
            self.adapters[name] = adapter
            stable_since = time.monotonic()
            try:
                state.running = True
                state.paused = False
                await adapter.start()
                worker = getattr(adapter, "worker_task", None)
                if worker is not None:
                    await worker
                else:  # passive adapters (webhook): idle until superseded/stopped
                    while not self._stopping and self.adapters.get(name) is adapter:
                        await asyncio.sleep(0.2)
            except asyncio.CancelledError:
                raise
            except AdapterAuthError as exc:
                state.running = False
                state.paused = True
                state.last_error = str(exc)
                logger.warning("渠道 %s 已暂停： %s", name, exc)
                return
            except Exception as exc:
                state.last_error = f"{type(exc).__name__}: {exc}"
                logger.exception("渠道 %s 连接中断", name)
            finally:
                state.running = False
                with contextlib.suppress(Exception):
                    await adapter.stop()
            if self._stopping or not (self.configs.get(name) or {}).get("enabled"):
                return
            if time.monotonic() - stable_since >= self._stable_reset_seconds:
                attempt = 0  # a stable run resets the reconnect ladder
            attempt += 1
            delay = compute_backoff(
                attempt, initial=initial, factor=factor, cap=cap, jitter=jitter, rng=self._rng
            )
            await asyncio.sleep(delay)

    # -- inbound pipeline ------------------------------------------------------------

    def _event_sink(self) -> Callable[[MessageEvent], Awaitable[None]]:
        async def sink(event: MessageEvent) -> None:
            state = self._state(event.channel)
            state.received += 1
            accepted = self.ingress.enqueue_inbound(event)
            if not accepted:
                logger.debug("丢弃重复入站事件 %s/%s", event.channel, event.event_id)
                return
            if self._control_handler is not None and self._admit(event):
                if await self._control_handler(event):
                    self.ingress.ack_event(event)
                    return
            self._schedule_drain()

        return sink

    def _schedule_drain(self) -> None:
        # Flag + single worker: a drain that is already exiting re-checks the
        # flag, so an event enqueued right after the last claim is not missed.
        self._drain_requested = True
        if self._drain_task is not None and not self._drain_task.done():
            return
        self._drain_task = asyncio.create_task(self._drain(), name="atlas-channel-drain")

    def _admit(self, event: MessageEvent) -> bool:
        policy = self.policies.get(event.channel) or dict(DEFAULT_POLICY)
        if event.is_group:
            decision = gate_group(
                str(policy.get("group_policy", "open")),
                event.sender_id,
                list(policy.get("group_allowlist") or []),
                dm_allowlist=list(policy.get("dm_allowlist") or []),
            )
            if decision.allowed and policy.get("require_mention"):
                implicit = ("reply_to_bot",) if event.reply_to_event_id else ()
                facts = MentionFacts(was_mentioned=event.is_mention, implicit=implicit)
                mention = gate_mention(facts, MentionPolicy(is_group=True, require_mention=True))
                return not mention.should_skip
            return decision.allowed
        decision = gate_dm(
            str(policy.get("dm_policy", "open")),
            event.sender_id,
            list(policy.get("dm_allowlist") or []),
            allow_when_empty=bool(policy.get("allow_when_empty", False)),
        )
        return decision.allowed

    async def _drain(self) -> None:
        async with self._drain_lock:
            while self._drain_requested and not self._stopping:
                self._drain_requested = False
                while True:
                    batch = self.ingress.claim_batch(limit=8, worker_id="gateway")
                    if not batch:
                        break
                    for record in batch:
                        event = record.event
                        state = self._state(event.channel)
                        if not self._admit(event):
                            state.dropped += 1
                            self.ingress.ack(record.id)
                            logger.info("入站事件被门控拒绝 %s/%s", event.channel, event.event_id)
                            continue
                        agent_id = resolve_route(self.bindings, event, agent_ids=self.agent_ids)
                        if agent_id is None and self.bindings:
                            state.dropped += 1
                            self.ingress.ack(record.id)
                            logger.warning(
                                "入站事件无路由 %s/%s（fail closed）", event.channel, event.event_id
                            )
                            continue
                        if self._dispatcher is None:
                            # Wave 2 wires the real dispatcher; keep the event queued.
                            self.ingress.fail(record.id, "dispatcher 未接入", retryable=True)
                            self._drain_requested = False
                            return
                        try:
                            await self._dispatcher(event, agent_id)
                        except Exception as exc:
                            logger.exception("渠道入站任务处理失败 %s", event.channel)
                            self.ingress.fail(
                                record.id, f"{type(exc).__name__}: {exc}", retryable=True
                            )
                        else:
                            self.ingress.ack(record.id)

    # -- outbound pipeline -------------------------------------------------------------

    async def send(
        self,
        channel: str,
        chat_id: str,
        content: str,
        *,
        account: str = "",
        reply_to: str = "",
        attachments: list[Attachment] | None = None,
        metadata: dict[str, Any] | None = None,
        key: str | None = None,
    ) -> str:
        """Queue one outbound message; returns its idempotency key."""
        payload = None
        if attachments:
            from dataclasses import asdict

            payload = [asdict(item) for item in attachments]
        return self.delivery.enqueue(
            channel, chat_id, content,
            account=account, reply_to=reply_to,
            attachments=payload, metadata=metadata, key=key,
        )

    async def send_test(self, channel: str, chat_id: str, text: str = "") -> str:
        return await self.send(
            channel, chat_id, text or "Atlas 渠道测试消息", metadata={"test": True}
        )

    async def _delivery_loop(self) -> None:
        # One failed cycle must not silently strand every queued reply: the
        # pump logs the exception and retries on the next interval. Only
        # cancellation ends the loop.
        while not self._stopping:
            try:
                await self.drain_delivery()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("渠道发送泵异常，将在下个周期重试")
            await asyncio.sleep(self._delivery_interval)

    async def drain_delivery(self) -> int:
        """Pump every due outbound message once; returns the processed count."""
        sent = 0
        while True:
            due = self.delivery.claim_due(limit=8, worker_id="gateway")
            if not due:
                return sent
            for record in due:
                sent += 1
                state = self._state(record.channel)
                adapter = self.adapters.get(record.channel)
                if adapter is None:
                    self.delivery.fail(record.id, f"渠道 {record.channel} 未运行", retryable=True)
                    await self._report_delivery_failure(record, "渠道未运行，消息已排队重试。")
                    continue
                attachments = [Attachment(**item) for item in (record.attachments or [])]
                try:
                    result = await adapter.send(
                        record.chat_id, record.content,
                        reply_to=record.reply_to,
                        attachments=attachments or None,
                        metadata=record.metadata,
                    )
                except AdapterAuthError as exc:
                    logger.exception("渠道鉴权失败 %s", record.channel)
                    self.delivery.fail(record.id, str(exc), retryable=False)
                    await self._report_delivery_failure(record, "渠道鉴权失败，消息未送达。")
                except Exception as exc:
                    logger.exception("渠道消息发送失败 %s", record.channel)
                    self.delivery.fail(record.id, f"{type(exc).__name__}: {exc}", retryable=True)
                    await self._report_delivery_failure(record, "渠道发送失败，消息已排队重试。")
                else:
                    if result.ok:
                        self.delivery.mark_delivered(record.id, result.message_id)
                        state.delivered += 1
                    else:
                        logger.warning("渠道发送未成功 %s", record.channel)
                        self.delivery.fail(
                            record.id, result.error or "发送失败", retryable=result.retryable
                        )
                        await self._report_delivery_failure(record, "渠道发送失败，消息未送达。")

    # -- webhook ingress ------------------------------------------------------------------

    def _credential_secret(self, name: str) -> str:
        """Secret kept in the credential store for one channel (never logged)."""
        try:
            stored = self.credentials.get(name, "secret")
        except Exception:
            logger.exception("渠道 %s 凭据读取失败", name)
            return ""
        return str(stored or "")

    def _effective_secret(self, name: str) -> str:
        """Explicit ``configs["secret"]`` wins; the credential store fills the gap."""
        configured = str((self.configs.get(name) or {}).get("secret") or "")
        if configured:
            return configured
        return self._credential_secret(name)

    async def handle_webhook(
        self,
        channel: str,
        headers: dict[str, str],
        body: bytes | str,
        *,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Verify + normalize one webhook request and push it through the pipeline."""
        config = self.configs.get(channel) or {}
        secret = self._effective_secret(channel)
        if secret:
            from atlas.channels.adapters.webhook import verify_hmac

            if not verify_hmac(secret, headers, body, now=now):
                raise WebhookError(401, "webhook 签名无效或已过期。")
        elif not config.get("allow_unsigned"):
            raise WebhookError(403, "该渠道未配置 webhook secret，拒绝未签名请求。")
        try:
            payload = json.loads(bytes(body).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise WebhookError(400, "webhook 载荷不是合法 JSON。") from exc
        if not isinstance(payload, dict):
            raise WebhookError(400, "webhook 载荷必须是 JSON 对象。")
        from atlas.channels.adapters.webhook import parse_inbound

        try:
            event = parse_inbound(
                payload, channel=channel, account=str(config.get("account") or "")
            )
        except ValueError as exc:
            raise WebhookError(422, str(exc)) from exc
        await self._event_sink()(event)
        return {"ok": True, "event_id": event.event_id, "channel": channel}

    # -- introspection ---------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        channels = []
        for name in self.registry:
            state = self._state(name)
            config = self.configs.get(name) or {}
            channels.append({
                "name": name,
                "enabled": state.enabled or bool(config.get("enabled", False)),
                "running": state.running,
                "paused": state.paused,
                "last_error": state.last_error,
                "counts": {
                    "received": state.received,
                    "delivered": state.delivered,
                    "dropped": state.dropped,
                    "inbound_pending": self.ingress.pending_count(channel=name),
                    "outbound": self.delivery.counts(channel=name),
                },
            })
        return {
            "channels": channels,
            "dispatcher_connected": self._dispatcher is not None,
        }

    def close(self) -> None:
        self.ingress.close()
        self.delivery.close()


__all__ = [
    "AdapterAuthError",
    "AdapterFactory",
    "ChannelManager",
    "ChannelState",
    "DispatchHandler",
    "DEFAULT_POLICY",
    "WebhookError",
    "compute_backoff",
]
