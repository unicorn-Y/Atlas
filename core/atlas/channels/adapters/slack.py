"""Slack channel adapter — Socket Mode via ``slack-sdk`` (lazy-loaded).

Inbound ``message``/``app_mention`` events normalize into :class:`MessageEvent`
(``app_mention`` → ``is_mention``, ``thread_ts`` → ``thread_id``, files →
:class:`Attachment`); outbound goes through ``chat.postMessage``. Content with a
``blocks:`` prefix is treated as the Block Kit enhanced path: the remainder is
parsed as JSON (a list of blocks, or ``{"blocks": [...], "text": fallback}``),
sanitized through the ported :mod:`..._vendor.slack_block_kit` boundary, and sent
with the mandatory ``text`` fallback; anything else (or unparseable JSON) falls
back to plain text so a message is never lost.

Credentials (config key first, then ``atlas.channel.slack.*`` / env):
``bot_token`` (``xoxb-…``) and ``app_token`` (``xocha-…`` Socket Mode). Optional
``bot_user_id`` improves mention detection and self-message filtering.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from atlas.channels.adapters._vendor import slack_block_kit
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

_BLOCKS_PREFIX = "blocks:"
# Slack hard cap on ``text`` for chat.postMessage (~40k chars).
_MAX_MESSAGE_LENGTH = 39_000
# Bot-authored / non-user-facing subtypes that must never reach the dispatcher.
_SKIP_SUBTYPES = {
    "message_changed", "message_deleted", "message_replied", "bot_message",
    "channel_join", "channel_leave", "channel_topic", "channel_purpose", "channel_name",
    "group_join", "group_leave", "thread_broadcast", "reminder_add",
}
_MENTION_RE = re.compile(r"<@([A-Z0-9]+)(\|[^>]+)?>")
_RETRYABLE_SLACK_ERRORS = {
    "ratelimited", "rate_limited", "internal_error", "service_unavailable",
    "request_timeout", "temporarily_unavailable",
}
_INVALID_THREAD_ANCHOR_ERRORS = {"thread_not_found", "invalid_thread_ts"}


def slack_send_error_retryable(error: str, status_code: int | None = None) -> bool:
    """Classify a Slack send failure for the channel delivery retry queue.

    Network/server/rate-limit failures are transient; authentication, invalid
    arguments, missing scopes, and other permanent API errors should be surfaced
    without replaying the same message.
    """
    if status_code == 429 or (status_code is not None and status_code >= 500):
        return True
    return str(error or "").strip().lower() in _RETRYABLE_SLACK_ERRORS


def slack_thread_anchor_invalid(error: str) -> bool:
    """Return true only for structured Slack errors that reject a reply anchor."""
    return str(error or "").strip().lower() in _INVALID_THREAD_ANCHOR_ERRORS


def _channel_kind(channel_id: str) -> tuple[bool, str]:
    """(is_group, slack kind) from the Slack channel-id prefix convention."""
    prefix = (channel_id or "")[:1]
    if prefix in ("C", "G"):
        return True, "channel" if prefix == "C" else "group"
    return False, "dm"


class SlackAdapter(ChannelAdapter):
    """Socket Mode adapter. SDKs are imported lazily; see :meth:`is_available`."""

    name = "slack"
    max_message_length = _MAX_MESSAGE_LENGTH

    def __init__(self, config: dict[str, Any], dispatcher) -> None:
        super().__init__(config, dispatcher)
        self._credentials = config.get("credentials")
        self._bot_token = str(config.get("bot_token") or self._secret("bot_token") or "")
        self._app_token = str(config.get("app_token") or self._secret("app_token") or "")
        self._bot_user_id = str(config.get("bot_user_id") or self._secret("bot_user_id") or "")
        self._client: Any = None  # SocketModeClient
        self._web: Any = None  # AsyncWebClient
        self._running = False

    def _secret(self, field: str) -> str | None:
        override = self.config.get("credentials")
        store = override if override is not None else None
        if store is not None and hasattr(store, "get"):
            try:
                value = store.get("slack", field)
                if value:
                    return value
            except Exception:
                logger.exception("Slack credential lookup failed")
        return get_channel_secret("slack", field)

    # -- availability / lifecycle ------------------------------------------------

    @classmethod
    def is_available(cls) -> bool:
        try:
            import slack_sdk  # noqa: F401
        except ImportError:
            return False
        return slack_sdk is not None

    async def start(self) -> None:
        if not self.is_available():
            raise ChannelAdapterError("sdk not installed: slack-sdk")
        if not self._bot_token or not self._app_token:
            raise ChannelAdapterError("slack: bot_token and app_token are required")
        from slack_sdk.socket_mode.aiohttp import SocketModeClient
        from slack_sdk.web.async_client import AsyncWebClient

        self._web = AsyncWebClient(token=self._bot_token)
        self._client = SocketModeClient(
            app_token=self._app_token, web_client=self._web, trace_enabled=False)
        self._client.socket_mode_request_listeners.append(self._on_socket_mode_request)
        await self._client.connect()
        self._running = True
        logger.info("[slack] connected via Socket Mode (account=%s)", self.account_id())

    async def stop(self) -> None:
        self._running = False
        client, self._client = self._client, None
        self._web = None
        if client is not None:
            try:
                await client.close()
            except Exception:
                logger.debug("[slack] socket mode close failed", exc_info=True)

    # -- inbound ------------------------------------------------------------------

    async def _on_socket_mode_request(self, client: Any, req: Any) -> None:
        """Socket Mode listener: ack every events_api envelope immediately, then
        dispatch the normalized event as a background task (never stall the socket)."""
        if getattr(req, "type", "") != "events_api":
            return
        try:
            from slack_sdk.socket_mode.response import SocketModeResponse
            await client.send_socket_mode_response(
                SocketModeResponse(envelope_id=getattr(req, "envelope_id", "")))
        except Exception:
            logger.warning("[slack] failed to ack envelope", exc_info=True)
        payload = getattr(req, "payload", None) or {}
        event = payload.get("event") if isinstance(payload, dict) else None
        normalized = self._normalize_event(event if isinstance(event, dict) else {})
        if normalized is not None:
            import asyncio
            asyncio.create_task(self._safe_dispatch(normalized))

    async def _safe_dispatch(self, event: MessageEvent) -> None:
        try:
            await self._dispatch(event)
        except Exception:
            logger.exception("[slack] dispatcher failed for event %s", event.event_id)

    def _normalize_event(self, event: dict[str, Any]) -> MessageEvent | None:
        """Slack event dict → MessageEvent (None for events the gateway must not see)."""
        etype = event.get("type")
        if etype not in ("message", "app_mention"):
            return None
        subtype = event.get("subtype") or ""
        if subtype in _SKIP_SUBTYPES:
            return None
        user = event.get("user") or ""
        if not user or event.get("bot_id"):
            return None
        if self._bot_user_id and user == self._bot_user_id:
            return None

        channel = str(event.get("channel") or "")
        ts = str(event.get("ts") or "")
        text = str(event.get("text") or "")
        is_mention = False
        if etype == "app_mention":
            is_mention = True
            text = _MENTION_RE.sub("", text).strip()
        elif self._bot_user_id and f"<@{self._bot_user_id}>" in text:
            is_mention = True

        thread_ts = str(event.get("thread_ts") or "")
        is_group, _ = _channel_kind(channel)

        attachments: list[Attachment] = []
        for item in event.get("files") or []:
            if not isinstance(item, dict):
                continue
            mime = str(item.get("mimetype") or "")
            attachments.append(Attachment(
                kind=MessageType.IMAGE if mime.startswith("image/") else MessageType.FILE,
                url=str(item.get("url_private") or item.get("permalink") or ""),
                filename=str(item.get("name") or ""),
                mime_type=mime,
                size=item.get("size") if isinstance(item.get("size"), int) else None,
                meta={"file_id": str(item.get("id") or "")},
            ))

        profile = event.get("user_profile") if isinstance(event.get("user_profile"), dict) else {}
        try:
            ts_value = float(ts) if ts else 0.0
        except ValueError:
            ts_value = 0.0
        return MessageEvent(
            channel=self.name,
            account=self.account_id(),
            event_id=str(event.get("client_msg_id") or f"{channel}:{ts}" or ""),
            chat_id=channel,
            sender_id=user,
            kind=MessageType.TEXT if (text or not attachments) else attachments[0].kind,
            text=text,
            thread_id=thread_ts,
            sender_name=str(profile.get("display_name") or profile.get("real_name") or ""),
            is_group=is_group,
            is_mention=is_mention,
            reply_to_event_id=thread_ts if thread_ts and thread_ts != ts else "",
            attachments=attachments,
            ts=ts_value,
            raw=dict(event),
        )

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
        if self._web is None:
            return SendResult(ok=False, error="not connected", retryable=True)
        text, blocks = content, None
        if content.startswith(_BLOCKS_PREFIX):
            text, blocks = self._parse_blocks(content[len(_BLOCKS_PREFIX):])
        else:
            text = content[: self.max_message_length]
        blocks = self._attachment_blocks(attachments, blocks)
        payload: dict[str, Any] = {
            "channel": chat_id,
            # Slack requires a non-empty text fallback alongside blocks
            # (notifications / screen readers).
            "text": text or " ",
        }
        if blocks:
            payload["blocks"] = blocks
        if reply_to:
            payload["thread_ts"] = reply_to
        try:
            response = await self._web.chat_postMessage(**payload)
        except Exception as exc:
            logger.exception("Slack message send failed")
            return SendResult(ok=False, error=str(exc), retryable=True)
        data = getattr(response, "data", None)
        if not isinstance(data, dict):
            return SendResult(ok=False, error="Slack returned an invalid send response")
        if not data.get("ok", False) and reply_to and slack_thread_anchor_invalid(
            str(data.get("error") or ""),
        ):
            # The thread may have been deleted between inbound dispatch and the
            # final answer. Slack confirmed this attempt was rejected, so one
            # unthreaded retry safely delivers the content to the channel.
            payload.pop("thread_ts", None)
            try:
                response = await self._web.chat_postMessage(**payload)
            except Exception as exc:
                logger.exception("Slack unthreaded fallback send failed")
                return SendResult(ok=False, error=str(exc), retryable=True)
            data = getattr(response, "data", None)
            if not isinstance(data, dict):
                return SendResult(ok=False, error="Slack returned an invalid fallback response")
        if not data.get("ok", False):
            error = str(data.get("error") or "slack api error")
            status_code = getattr(response, "status_code", None)
            try:
                status_code = int(status_code) if status_code is not None else None
            except (TypeError, ValueError):
                status_code = None
            return SendResult(
                ok=False, error=error,
                retryable=slack_send_error_retryable(error, status_code),
            )
        return SendResult(ok=True, message_id=str(data.get("ts") or ""))

    def _parse_blocks(self, raw: str) -> tuple[str, list[dict[str, Any]] | None]:
        """``blocks:`` remainder → (text fallback, sanitized blocks). Invalid JSON or an
        empty sanitized payload falls back to plain text — never lose a message."""
        fallback = f"{_BLOCKS_PREFIX}{raw}"
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return fallback, None
        text, blocks = fallback, None
        if isinstance(parsed, dict):
            blocks = parsed.get("blocks")
            text = str(parsed.get("text") or fallback)
        elif isinstance(parsed, list):
            blocks = parsed
        if not isinstance(blocks, list):
            return fallback, None
        return text, slack_block_kit.sanitize_blocks(blocks)

    def _attachment_blocks(
        self, attachments: list[Attachment] | None, blocks: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]] | None:
        """Append remote image attachments as ``image`` blocks (local files are skipped:
        uploads need ``files.getUploadURLExternal``, a later enhancement)."""
        out = list(blocks) if blocks else None
        for att in attachments or []:
            if att.kind is MessageType.IMAGE and att.url and att.url.startswith(("http://", "https://")):
                block = {"type": "image", "image_url": att.url, "alt_text": att.filename or "image"}
                if out is None:
                    out = [block]
                elif len(out) < slack_block_kit.MAX_BLOCKS:
                    out.append(block)
        return out

    # -- metadata -----------------------------------------------------------------

    async def get_chat_info(self, chat_id: str) -> dict[str, Any]:
        if self._web is None:
            return {}
        try:
            response = await self._web.conversations_info(channel=chat_id)
            data = getattr(response, "data", None) or {}
            channel = data.get("channel") or {}
        except Exception:
            logger.debug("[slack] conversations_info failed for %s", chat_id, exc_info=True)
            return {}
        _, kind = _channel_kind(chat_id)
        return {
            "name": str(channel.get("name_normalized") or channel.get("name") or chat_id),
            "type": "dm" if channel.get("is_im") else kind,
        }
