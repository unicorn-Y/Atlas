"""Webhook channel adapter (r5 §6.2: reuse the Atlas HTTP server, no side server).

Inbound direction lives on the FastAPI route ``POST /api/channels/{channel}/inbound``
(mounted by :mod:`atlas.api.channel_router`): this module owns the protocol
pieces — HMAC-SHA256 verification with a ±5 min timestamp window against
replay, plus payload → :class:`MessageEvent` normalization. Outbound ``send``
POSTs a JSON envelope to the configured URL (optionally signed with the same
secret).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from collections.abc import Mapping
from typing import Any

import httpx

from atlas.channels.contract import (
    Attachment,
    ChannelAdapter,
    MessageEvent,
    MessageType,
    SendResult,
    causality_fields,
)

SIGNATURE_HEADER = "x-atlas-signature"
TIMESTAMP_TOLERANCE_SECONDS = 300.0  # ±5 min anti-replay window


def _header_value(headers: Mapping[str, str], name: str) -> str:
    lowered = name.lower()
    for key, value in headers.items():
        if str(key).lower() == lowered:
            return str(value)
    return ""


def sign_payload(secret: str, timestamp: int, body: bytes | str) -> str:
    """Signature header value ``t=<ts>,v1=<hex hmac_sha256(ts + '.' + body)>``."""
    if isinstance(body, str):
        body = body.encode("utf-8")
    digest = hmac.new(
        secret.encode("utf-8"), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return f"t={timestamp},v1={digest}"


def verify_hmac(
    secret: str,
    headers: Mapping[str, str],
    body: bytes | str,
    *,
    now: float | None = None,
    tolerance: float = TIMESTAMP_TOLERANCE_SECONDS,
) -> bool:
    """Validate one signed webhook request (good signature, fresh timestamp)."""
    if not secret:
        return False
    if isinstance(body, str):
        body = body.encode("utf-8")
    header = _header_value(headers, SIGNATURE_HEADER)
    if not header:
        return False
    parts: dict[str, str] = {}
    for chunk in header.split(","):
        if "=" in chunk:
            key, _, value = chunk.partition("=")
            parts[key.strip()] = value.strip()
    timestamp_text, signature = parts.get("t", ""), parts.get("v1", "")
    if not timestamp_text or not signature:
        return False
    try:
        timestamp = int(timestamp_text)
    except ValueError:
        return False
    current = time.time() if now is None else now
    if abs(current - timestamp) > tolerance:
        return False
    expected = sign_payload(secret, timestamp, body).rsplit("v1=", 1)[-1]
    return hmac.compare_digest(expected, signature.lower())


_KIND_NAMES = {member.value for member in MessageType}


def parse_inbound(
    payload: Mapping[str, Any],
    *,
    channel: str = "webhook",
    account: str = "",
) -> MessageEvent:
    """Normalize a JSON webhook payload into a :class:`MessageEvent`.

    Required: ``event_id`` and ``chat_id`` (raises ``ValueError`` otherwise).
    Attachments may be given inline (``url``/``filename``/``mime_type``).
    """
    data = dict(payload or {})
    event_id = str(data.get("event_id") or data.get("eventId") or "").strip()
    chat_id = str(data.get("chat_id") or data.get("chatId") or "").strip()
    if not event_id:
        raise ValueError("webhook 载荷缺少 event_id。")
    if not chat_id:
        raise ValueError("webhook 载荷缺少 chat_id。")
    kind_name = str(data.get("kind") or data.get("message_type") or "text").lower()
    if kind_name not in _KIND_NAMES:
        kind_name = MessageType.UNKNOWN.value
    attachments: list[Attachment] = []
    for raw in data.get("attachments") or []:
        if not isinstance(raw, Mapping):
            continue
        item = dict(raw)
        raw_kind = str(item.get("kind") or kind_name or "file").lower()
        if raw_kind not in _KIND_NAMES:
            raw_kind = MessageType.FILE.value
        attachments.append(
            Attachment(
                kind=MessageType(raw_kind),
                url=str(item.get("url", "")),
                local_path=str(item.get("local_path", "")),
                filename=str(item.get("filename", "")),
                mime_type=str(item.get("mime_type", "")),
                size=int(item["size"]) if isinstance(item.get("size"), int) else None,
            )
        )
    return MessageEvent(
        channel=str(data.get("channel") or channel),
        account=str(data.get("account") or account),
        event_id=event_id,
        chat_id=chat_id,
        sender_id=str(data.get("sender_id") or data.get("sender") or ""),
        kind=MessageType(kind_name),
        text=str(data.get("text") or data.get("prompt") or ""),
        thread_id=str(data.get("thread_id") or ""),
        sender_name=str(data.get("sender_name") or ""),
        sender_is_bot=bool(data.get("sender_is_bot", data.get("is_bot", False))),
        is_group=bool(data.get("is_group", False)),
        is_mention=bool(data.get("is_mention", True)),
        reply_to_event_id=str(data.get("reply_to_event_id") or ""),
        **causality_fields(dict(data), str(data.get("channel") or channel), str(data.get("event_id") or "")),
        attachments=attachments,
        ts=float(data.get("ts") or time.time()),
        raw=dict(data),
    )


class WebhookAdapter(ChannelAdapter):
    """Outbound-only adapter: ``send`` POSTs a signed JSON envelope to ``url``.

    Inbound arrives through the shared HTTP route and the gateway, not through
    this instance (``start``/``stop`` are therefore near no-ops).
    """

    name = "webhook"

    def __init__(self, config: dict[str, Any], dispatcher) -> None:
        super().__init__(config, dispatcher)
        self.account = str(config.get("account") or "")
        self.url = str(config.get("url") or "")
        self.secret = str(config.get("secret") or "")
        self.extra_headers = dict(config.get("headers") or {})
        self._client_factory = config.get("client_factory") or httpx.AsyncClient
        self._client: httpx.AsyncClient | None = None

    def account_id(self) -> str:
        return self.account

    async def start(self) -> None:
        self._client = self._client_factory(timeout=20.0)

    async def stop(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            await client.aclose()

    async def send(
        self,
        chat_id: str,
        content: str,
        *,
        reply_to: str = "",
        attachments: list[Attachment] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SendResult:
        if not self.url:
            return SendResult(ok=False, error="webhook 出站 URL 未配置。", retryable=False)
        envelope = {
            "channel": self.config.get("channel_label") or self.name,
            "account": self.account,
            "chat_id": str(chat_id),
            "text": str(content),
            "reply_to": str(reply_to),
            "metadata": dict(metadata or {}),
            "_atlas": dict((metadata or {}).get("_atlas") or {}),
            "attachments": [
                {
                    "kind": item.kind.value,
                    "url": item.url,
                    "local_path": item.local_path,
                    "filename": item.filename,
                    "mime_type": item.mime_type,
                }
                for item in (attachments or [])
            ],
        }
        client = self._client or self._client_factory(timeout=20.0)
        try:
            body = json.dumps(envelope, ensure_ascii=False).encode("utf-8")
            headers = dict(self.extra_headers)
            headers["content-type"] = "application/json"
            if self.secret:
                headers[SIGNATURE_HEADER] = sign_payload(
                    self.secret, int(time.time()), body
                )
            response = await client.post(self.url, content=body, headers=headers)
        except asyncio.CancelledError:
            raise
        except httpx.RequestError as exc:
            return SendResult(ok=False, error=f"webhook 请求失败：{exc}", retryable=True)
        if 200 <= response.status_code < 300:
            message_id = str(response.headers.get("x-atlas-message-id", ""))
            return SendResult(ok=True, message_id=message_id)
        retryable = response.status_code in (408, 425, 429) or response.status_code >= 500
        return SendResult(
            ok=False,
            error=f"webhook 返回 HTTP {response.status_code}",
            retryable=retryable,
        )


__all__ = [
    "SIGNATURE_HEADER",
    "TIMESTAMP_TOLERANCE_SECONDS",
    "WebhookAdapter",
    "parse_inbound",
    "sign_payload",
    "verify_hmac",
]
