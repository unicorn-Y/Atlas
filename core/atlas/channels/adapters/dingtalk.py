"""DingTalk channel adapter — Stream Mode via ``dingtalk-stream`` (lazy-loaded).

Inbound: the SDK keeps a long-lived WebSocket; chatbot callbacks are prepared from
the raw payload dict (``ChatbotMessage.from_dict`` + ``sessionWebhook``/
``isInAtList`` backfill, ported from the hermes handler) and normalized through the
ported :mod:`..._vendor.dingtalk_inbound` parsers into :class:`MessageEvent`
(``conversation_type == "2"`` → ``is_group``, ``is_in_at_list`` → ``is_mention``,
download codes → :class:`Attachment`).

Outbound: reply through the message's ``sessionWebhook`` (markdown, expiry-aware,
ported from hermes) or, when configured with ``webhook_url`` (+``webhook_secret``
for HMAC-SHA256 signing), through the static robot webhook.

Resilience: reconnect backoff ``[2, 5, 10, 30, 60]`` with a 5-trip circuit breaker on
identical error types — a direct port of the hermes ``_run_stream_loop`` semantics
(300 s silent retry interval while tripped, reset when the error type changes).

Credentials (config key first, then ``atlas.channel.dingtalk.*`` / env):
``client_id`` + ``client_secret`` (Stream Mode); optional ``webhook_url`` /
``webhook_secret`` / ``robot_code``.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import re
import time
import uuid
from typing import Any
from urllib.parse import quote_plus

from atlas.channels.adapters._vendor import dingtalk_inbound
from atlas.channels.adapters._vendor.credentials_bridge import get_channel_secret
from atlas.channels.contract import (
    Attachment,
    ChannelAdapter,
    ChannelAdapterError,
    MessageEvent,
    MessageType,
    SendResult,
)

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 20_000
RECONNECT_BACKOFF = [2, 5, 10, 30, 60]
RECONNECT_CIRCUIT_BREAKER_TRIPS = 5  # identical errors escaping start() before the breaker trips
RECONNECT_CIRCUIT_BREAKER_DELAY = 300  # seconds between attempts while tripped (hermes parity)
_SESSION_WEBHOOKS_MAX = 500
_DEDUP_MAX = 1000


def _dingtalk_mentions(message: Any) -> list[str]:
    """Normalize Stream Mode callback ``atUsers`` into stable user identifiers."""
    values = getattr(message, "at_users", None) or getattr(message, "atUsers", None) or []
    if isinstance(values, dict):
        values = list(values.values())
    if not isinstance(values, (list, tuple)):
        return []
    result: list[str] = []
    for value in values:
        if isinstance(value, str):
            item = value
        elif isinstance(value, dict):
            item = str(value.get("dingtalkId") or value.get("staffId") or value.get("userId") or "")
        else:
            item = str(getattr(value, "dingtalk_id", "") or getattr(value, "staff_id", "") or getattr(value, "user_id", "") or "")
        if item:
            result.append(item.lstrip("@"))
    return list(dict.fromkeys(result))
_DINGTALK_WEBHOOK_RE = re.compile(r"^https://(?:api|oapi)\.dingtalk\.com/")
_NUMBERED_RE = re.compile(r"^\d+\.\s")


def _normalize_markdown(text: str) -> str:
    """Work around DingTalk renderer quirks (ported from hermes): blank line before
    numbered lists, dedent ``` fences."""
    lines = text.split("\n")
    out = []
    for i, line in enumerate(lines):
        prev = lines[i - 1].strip() if i > 0 else ""
        if prev and _NUMBERED_RE.match(line.strip()) and not _NUMBERED_RE.match(prev):
            out.append("")
        out.append(line.lstrip() if line.strip().startswith("```") else line)
    return "\n".join(out)


class DingTalkAdapter(ChannelAdapter):
    """Stream Mode adapter. SDK imported lazily; see :meth:`is_available`."""

    name = "dingtalk"
    max_message_length = MAX_MESSAGE_LENGTH

    def __init__(self, config: dict[str, Any], dispatcher) -> None:
        super().__init__(config, dispatcher)
        self._credentials = config.get("credentials")
        self._client_id = str(config.get("client_id") or self._secret("client_id") or "")
        self._client_secret = str(
            config.get("client_secret") or self._secret("client_secret") or "")
        self._webhook_url = str(config.get("webhook_url") or self._secret("webhook_url") or "")
        self._webhook_secret = str(
            config.get("webhook_secret") or self._secret("webhook_secret") or "")
        self._robot_code = str(config.get("robot_code") or "") or self._client_id
        self._stream_client: Any = None
        self._stream_task: asyncio.Task | None = None
        self._http_client: Any = None
        self._running = False
        # chat_id -> (webhook, expired_time_ms)
        self._session_webhooks: dict[str, tuple[str, int]] = {}
        self._dedup: dict[str, None] = {}  # insertion-ordered bounded set
        # Circuit breaker state (ported hermes semantics).
        self._backoff_idx = 0
        self._consecutive_same_error = 0
        self._last_error_type: type | None = None
        self._breaker_tripped = False

    def _secret(self, field: str) -> str | None:
        store = self.config.get("credentials")
        if store is not None and hasattr(store, "get"):
            try:
                value = store.get("dingtalk", field)
                if value:
                    return value
            except Exception:
                logger.exception("DingTalk credential lookup failed")
        return get_channel_secret("dingtalk", field)

    # -- availability / lifecycle ------------------------------------------------

    @classmethod
    def is_available(cls) -> bool:
        try:
            import dingtalk_stream  # noqa: F401
        except ImportError:
            return False
        return True

    async def start(self) -> None:
        if not self.is_available():
            raise ChannelAdapterError("sdk not installed: dingtalk-stream")
        try:
            import httpx
        except ImportError as exc:
            raise ChannelAdapterError("sdk not installed: httpx") from exc
        if not ((self._client_id and self._client_secret) or self._webhook_url):
            raise ChannelAdapterError("dingtalk: client_id and client_secret are required")
        import dingtalk_stream

        self._http_client = httpx.AsyncClient(timeout=30.0)
        self._running = True
        if self._client_id and self._client_secret:
            self._stream_client = dingtalk_stream.DingTalkStreamClient(
                dingtalk_stream.Credential(self._client_id, self._client_secret))
            self._stream_client.register_callback_handler(
                dingtalk_stream.ChatbotMessage.TOPIC, self._make_handler(dingtalk_stream))
            self._stream_task = asyncio.create_task(self._run_stream())
        # webhook-robot-only mode: outbound via _send_via_robot_webhook.
        logger.info("[dingtalk] started (stream=%s, account=%s)",
                    bool(self._stream_client), self.account_id())

    async def stop(self) -> None:
        self._running = False
        task, self._stream_task = self._stream_task, None
        if task is not None:
            task.cancel()
            try:
                await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=5.0)
            except (TimeoutError, asyncio.CancelledError):
                logger.debug("[dingtalk] stream task did not exit cleanly")
        client, self._http_client = self._http_client, None
        if client is not None:
            await client.aclose()
        self._stream_client = None
        self._session_webhooks.clear()
        self._dedup.clear()

    async def _run_stream(self) -> None:
        """Run the SDK stream client with backoff + circuit breaker (ported hermes
        semantics: identical error types accumulate; past 5 trips the breaker delays
        300 s between attempts until the error type changes)."""
        while self._running:
            try:
                await self._stream_client.start()
                if not self._running:
                    return
                await asyncio.sleep(5)  # SDK start() normally blocks; re-enter politely
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("DingTalk stream failed")
                if not self._running:
                    return
                delay = self._record_stream_error(exc)
                logger.warning(
                    "[dingtalk] stream client error (%s%s); retrying in %.0fs",
                    exc, " — circuit breaker tripped" if self._breaker_tripped else "", delay)
                await asyncio.sleep(delay)

    def _record_stream_error(self, exc: BaseException) -> float:
        """Classify one stream failure and return the reconnect delay (ported hermes
        ``_run_stream_loop`` breaker; testable without the SDK)."""
        error_type = type(exc)
        if error_type is self._last_error_type:
            self._consecutive_same_error += 1
        else:
            self._consecutive_same_error = 1
            self._last_error_type = error_type
            self._backoff_idx = 0
        if self._consecutive_same_error <= RECONNECT_CIRCUIT_BREAKER_TRIPS:
            self._breaker_tripped = False
            delay = RECONNECT_BACKOFF[min(self._backoff_idx, len(RECONNECT_BACKOFF) - 1)]
            self._backoff_idx += 1
            return float(delay)
        self._breaker_tripped = True
        return float(RECONNECT_CIRCUIT_BREAKER_DELAY)

    # -- inbound ------------------------------------------------------------------

    def _make_handler(self, dingtalk_stream: Any) -> Any:
        """Handler instance whose class subclasses the SDK's ``ChatbotHandler`` when the
        SDK is present (isinstance checks), falling back to the plain class otherwise."""
        handler_base = getattr(dingtalk_stream, "ChatbotHandler", None)
        if handler_base is not None and isinstance(handler_base, type):
            handler_cls = type("_IncomingHandlerShim", (_IncomingHandler, handler_base), {})
            return handler_cls(self)
        return _IncomingHandler(self)

    async def _process_callback_data(self, data: Any) -> tuple[int, str]:
        """One SDK callback payload (dict or JSON string) → ChatbotMessage → dispatch.
        Returns the ACK status pair (ported hermes handler shape, SDK-testable)."""
        from dingtalk_stream import ChatbotMessage
        from dingtalk_stream.frames import AckMessage

        try:
            payload = json.loads(data) if isinstance(data, str) else data
            chatbot_msg = ChatbotMessage.from_dict(payload)
            payload = payload if isinstance(payload, dict) else {}
            webhook = payload.get("sessionWebhook") or payload.get("session_webhook") or ""
            if webhook and not getattr(chatbot_msg, "session_webhook", None):
                chatbot_msg.session_webhook = webhook
            if payload.get("isInAtList") and not getattr(chatbot_msg, "is_in_at_list", False):
                chatbot_msg.is_in_at_list = True
            at_users = payload.get("atUsers") or payload.get("at_users")
            if at_users and not getattr(chatbot_msg, "at_users", None):
                chatbot_msg.at_users = at_users
            await self._on_message(chatbot_msg)
        except Exception:
            logger.exception("[dingtalk] error preparing incoming message")
            return AckMessage.STATUS_SYSTEM_EXCEPTION, "error"
        return AckMessage.STATUS_OK, "OK"

    async def _on_message(self, message: Any) -> None:
        msg_id = str(getattr(message, "message_id", "") or "") or uuid.uuid4().hex
        if msg_id in self._dedup:
            return
        self._dedup[msg_id] = None
        if len(self._dedup) > _DEDUP_MAX:
            self._dedup.pop(next(iter(self._dedup)))

        conversation_id = str(getattr(message, "conversation_id", "") or "")
        sender_id = str(getattr(message, "sender_id", "") or "")
        sender_staff_id = str(getattr(message, "sender_staff_id", "") or "")
        sender_nick = str(getattr(message, "sender_nick", "") or "") or sender_id
        is_group = str(getattr(message, "conversation_type", "1")) == "2"
        chat_id = conversation_id or sender_id

        session_webhook = str(getattr(message, "session_webhook", "") or "")
        if session_webhook and chat_id and _DINGTALK_WEBHOOK_RE.match(session_webhook):
            if len(self._session_webhooks) >= _SESSION_WEBHOOKS_MAX:
                self._session_webhooks.pop(next(iter(self._session_webhooks)))
            self._session_webhooks[chat_id] = (
                session_webhook, int(getattr(message, "session_webhook_expired_time", 0) or 0))

        text = dingtalk_inbound.extract_text(message)
        kind, media_urls, media_mimes = dingtalk_inbound.extract_media(message)
        if not text and not media_urls:
            return
        attachments = [
            Attachment(kind=kind if len(media_urls) == 1 else MessageType.FILE,
                       url=url, mime_type=mime)
            for url, mime in zip(media_urls, media_mimes)
        ]
        create_at = getattr(message, "create_at", None)
        try:
            ts = int(create_at) / 1000.0 if create_at else time.time()
        except (TypeError, ValueError):
            ts = time.time()
        event = MessageEvent(
            channel=self.name,
            account=self.account_id(),
            event_id=msg_id,
            chat_id=chat_id,
            sender_id=sender_id or sender_staff_id,
            kind=kind if (attachments or not text) else MessageType.TEXT,
            text=text,
            thread_id="",
            sender_name=sender_nick,
            is_group=is_group,
            is_mention=bool(getattr(message, "is_in_at_list", False)),
            mentions=_dingtalk_mentions(message),
            attachments=attachments,
            ts=ts,
            raw={"message_id": msg_id, "robot_code": str(getattr(message, "robot_code", "") or "")},
        )
        await self._dispatch(event)

    # -- outbound -----------------------------------------------------------------

    async def send(
        self,
        chat_id: str,
        content: str,
        *,
        reply_to: str = "",
        attachments: list[Attachment] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SendResult:
        if self._http_client is None:
            return SendResult(ok=False, error="not connected")
        metadata = metadata or {}
        session_webhook = (str(metadata.get("session_webhook") or "")
                           or self._get_valid_webhook(chat_id))
        if not session_webhook:
            if self._webhook_url:
                return await self._send_via_robot_webhook(content, metadata)
            return SendResult(
                ok=False, error="no valid session_webhook; a reply must follow an inbound message")
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": str(metadata.get("title") or "Atlas"),
                "text": _normalize_markdown(content[: self.max_message_length]),
            },
        }
        try:
            response = await self._http_client.post(session_webhook, json=payload, timeout=15.0)
        except Exception as exc:
            logger.exception("DingTalk message send failed")
            return SendResult(ok=False, error=str(exc), retryable=True)
        if response.status_code >= 300:
            return SendResult(ok=False, error=f"HTTP {response.status_code}: {response.text[:200]}")
        try:
            data = response.json()
        except ValueError:
            data = {}
        if data.get("errcode", 0) != 0:
            return SendResult(ok=False, error=f"dingtalk api error: {data.get('errmsg', data)}")
        return SendResult(ok=True, message_id=uuid.uuid4().hex[:12])

    def _get_valid_webhook(self, chat_id: str) -> str | None:
        """Non-expired session webhook for chat_id with a 5-minute safety margin (ported)."""
        info = self._session_webhooks.get(chat_id)
        if not info:
            return None
        webhook, expired_time_ms = info
        if expired_time_ms and int(time.time() * 1000) + 5 * 60 * 1000 >= expired_time_ms:
            self._session_webhooks.pop(chat_id, None)
            return None
        return webhook

    async def _send_via_robot_webhook(self, content: str, metadata: dict[str, Any]) -> SendResult:
        """Static robot webhook (access_token in URL + optional secret 加签) for proactive
        delivery where no session webhook exists."""
        url = self._webhook_url
        if self._webhook_secret:
            timestamp = str(round(time.time() * 1000))
            digest = hmac.new(
                self._webhook_secret.encode("utf-8"),
                f"{timestamp}\n{self._webhook_secret}".encode(),
                digestmod=hashlib.sha256).digest()
            sign = quote_plus(base64.b64encode(digest))
            url = f"{url}{'&' if '?' in url else '?'}timestamp={timestamp}&sign={sign}"
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": str(metadata.get("title") or "Atlas"),
                "text": _normalize_markdown(content[: self.max_message_length]),
            },
        }
        try:
            response = await self._http_client.post(url, json=payload, timeout=15.0)
            data = response.json() if response.status_code < 300 else {}
        except Exception as exc:
            logger.exception("DingTalk API request failed")
            return SendResult(ok=False, error=str(exc), retryable=True)
        if data.get("errcode", 0) != 0:
            return SendResult(ok=False, error=f"dingtalk api error: {data.get('errmsg', data)}")
        return SendResult(ok=True, message_id=uuid.uuid4().hex[:12])

    # -- metadata -----------------------------------------------------------------

    async def get_chat_info(self, chat_id: str) -> dict[str, Any]:
        return {"name": chat_id, "type": "group" if "group" in chat_id.lower() else "dm"}


class _IncomingHandler:
    """ChatbotHandler-compatible callback (base class resolved against the SDK at
    registration time by the adapter)."""

    def __init__(self, adapter: DingTalkAdapter) -> None:
        self._adapter = adapter

    def pre_start(self) -> None:
        """No-op hook the SDK calls before opening the WebSocket (missing → AttributeError)."""
        return

    async def process(self, callback_message: Any):
        return await self._adapter._process_callback_data(getattr(callback_message, "data", None))
