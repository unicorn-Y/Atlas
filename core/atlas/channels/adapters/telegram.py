"""Telegram channel adapter — raw Bot API over httpx, zero third-party SDK.

Behaviour is absorbed from the frozen ``core/atlas/telegram.py`` (long polling
with ``getUpdates`` offset, ``sendMessage``/``editMessage`` text delivery, Bot
API file download URLs, secret-safe error messages). Differences:

- the adapter never keeps secrets in logs/exceptions;
- the ``getUpdates`` offset is persisted in SQLite so restarts do not replay;
- transport errors propagate to the gateway, which owns reconnect backoff;
  credential failures raise :class:`AdapterAuthError` and pause the channel.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

import httpx

from atlas.channels import AdapterAuthError
from atlas.channels.contract import (
    Attachment,
    ChannelAdapter,
    ChannelAdapterError,
    MessageEvent,
    MessageType,
    SendResult,
)
from atlas.channels.credentials import channel_credentials

logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)

DEFAULT_API_BASE = "https://api.telegram.org"
MAX_TEXT_LENGTH = 4096
RETRYABLE_ERROR_CODES = {429, 500, 502, 503, 504}
AUTH_ERROR_CODES = {401, 403, 404}

_MEDIA_KIND = {
    "photo": MessageType.IMAGE,
    "document": MessageType.FILE,
    "voice": MessageType.AUDIO,
    "audio": MessageType.AUDIO,
    "video": MessageType.VIDEO,
    "video_note": MessageType.VIDEO,
    "sticker": MessageType.STICKER,
}


def file_download_url(api_base: str, token: str, file_path: str) -> str:
    """Normalized Bot API file download URL (same shape the Bot API returns)."""
    base = (api_base or DEFAULT_API_BASE).rstrip("/")
    return f"{base}/file/bot{token}/{str(file_path).lstrip('/')}"


def default_state_path() -> Path:
    data_dir = Path(os.environ.get("ATLAS_DATA_DIR") or "data")
    return data_dir / "channels" / "telegram_state.db"


class TelegramAdapter(ChannelAdapter):
    name = "telegram"

    def __init__(self, config: dict[str, Any], dispatcher) -> None:
        super().__init__(config, dispatcher)
        self.account = str(config.get("account") or "")
        self.api_base = str(config.get("api_base") or DEFAULT_API_BASE).rstrip("/")
        self.poll_timeout = float(config.get("poll_timeout", 25))
        self._client_factory = config.get("client_factory") or httpx.AsyncClient
        self._credentials = config.get("credentials") or channel_credentials
        self.state_path = Path(config.get("state_path") or default_state_path())
        self._client: httpx.AsyncClient | None = None
        self._task: asyncio.Task[None] | None = None
        self._offset = 0
        self._state_db: sqlite3.Connection | None = None
        self.bot_username = ""
        self.bot_id = 0
        self.stopping = False
        self._offset = self._load_offset()

    # -- lifecycle -------------------------------------------------------------

    @property
    def worker_task(self) -> asyncio.Task[None] | None:
        return self._task

    def account_id(self) -> str:
        return self.account

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        if not self._token():
            raise AdapterAuthError("请先保存 Telegram 机器人密钥。")
        self.stopping = False
        self._client = self._client_factory(timeout=self.poll_timeout + 10.0)
        try:
            me = await self._request("getMe") or {}
            self.bot_username = str(me.get("username", ""))
            self.bot_id = int(me.get("id", 0) or 0)
        except asyncio.CancelledError:
            await self._close_client()
            raise
        except Exception:
            await self._close_client()
            raise
        self._task = asyncio.create_task(
            self._run_loop(), name=f"atlas-channel-telegram-{self.account}"
        )

    async def stop(self) -> None:
        self.stopping = True
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self._close_client()

    async def _close_client(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            await client.aclose()

    async def _run_loop(self) -> None:
        try:
            while not self.stopping:
                updates = await self._poll_once()
                if not updates:
                    # Long poll elapsed server-side; a tiny idle sleep keeps a
                    # misbehaving zero-timeout server from spinning the loop.
                    await asyncio.sleep(0.05)
                    continue
                for update in updates:
                    await self._handle_update(update)
                    self._offset = max(self._offset, int(update.get("update_id", 0)) + 1)
                    self._persist_offset()
        except asyncio.CancelledError:
            raise
        finally:
            await self._close_client()

    # -- Bot API ------------------------------------------------------------------

    def _token(self) -> str | None:
        token = str(self.config.get("bot_token") or "").strip()
        if token:
            return token
        token = self._credentials.get("telegram", "bot_token")
        if token:
            return token
        legacy = getattr(self._credentials, "get_legacy_telegram_token", None)
        if legacy is not None:
            return legacy() or None
        return None

    async def _request(
        self, method: str, payload: dict[str, Any] | None = None, *, timeout: float | None = None
    ) -> Any:
        token = self._token()
        if not token:
            raise AdapterAuthError("Telegram 机器人密钥未配置。")
        client = self._client
        if client is None:
            raise ChannelAdapterError("Telegram 客户端未启动。")
        try:
            response = await client.post(
                f"{self.api_base}/bot{token}/{method}", json=payload or {},
                timeout=timeout if timeout is not None else self.poll_timeout + 10.0,
            )
        except asyncio.CancelledError:
            raise
        except httpx.RequestError:
            # Client exceptions may embed the secret-bearing request URL.
            raise ChannelAdapterError("Telegram 请求失败。") from None
        if response.status_code in AUTH_ERROR_CODES:
            raise AdapterAuthError(f"Telegram 鉴权失败（HTTP {response.status_code}）。")
        if response.status_code >= 400:
            raise ChannelAdapterError(f"Telegram 请求失败（HTTP {response.status_code}）。")
        try:
            data = response.json()
        except ValueError:
            raise ChannelAdapterError("Telegram 响应格式无效。") from None
        if not isinstance(data, dict) or not data.get("ok"):
            code = (data or {}).get("error_code")
            description = str((data or {}).get("description", "请求失败"))
            if code in AUTH_ERROR_CODES:
                raise AdapterAuthError(f"Telegram 鉴权失败：{description}")
            raise ChannelAdapterError(f"Telegram API 错误 {code}: {description}")
        return data.get("result")

    async def _poll_once(self) -> list[dict[str, Any]]:
        result = await self._request(
            "getUpdates",
            {
                "offset": self._offset,
                "timeout": int(self.poll_timeout),
                "allowed_updates": ["message"],
            },
        )
        return list(result) if isinstance(result, list) else []

    # -- inbound ----------------------------------------------------------------

    async def _handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message")
        if not isinstance(message, dict):
            return  # callback queries stay with the legacy approval service for now
        event = await self._build_event(message)
        if event is None:
            return
        await self._dispatch(event)

    async def _build_event(self, message: dict[str, Any]) -> MessageEvent | None:
        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        text = str(message.get("text") or message.get("caption") or "")
        media_field = next((field for field in _MEDIA_KIND if message.get(field)), None)
        if not text and media_field is None:
            return None
        chat_type = str(chat.get("type", "private"))
        is_group = chat_type in ("group", "supergroup", "channel")
        attachments: list[Attachment] = []
        kind = MessageType.TEXT
        if media_field is not None:
            kind = _MEDIA_KIND[media_field]
            attachment = await self._build_attachment(media_field, message[media_field])
            if attachment is not None:
                attachments.append(attachment)
        reply = message.get("reply_to_message") or {}
        reply_from = reply.get("from") or {}
        reply_to_bot = bool(self.bot_id) and int(reply_from.get("id", 0) or 0) == self.bot_id
        return MessageEvent(
            channel=self.name,
            account=self.account,
            event_id=str(message.get("message_id", "")),
            chat_id=str(chat.get("id", "")),
            sender_id=str(sender.get("id", "")),
            kind=kind,
            text=text,
            thread_id=str(message.get("message_thread_id") or ""),
            sender_name=" ".join(
                part
                for part in (str(sender.get("first_name", "")), str(sender.get("last_name", "")))
                if part
            ).strip(),
            is_group=is_group,
            is_mention=reply_to_bot or self._contains_bot_mention(message, text),
            reply_to_event_id=str(reply.get("message_id") or ""),
            attachments=attachments,
            ts=float(message.get("date", 0) or 0.0),
            raw=message,
        )

    def _contains_bot_mention(self, message: dict[str, Any], text: str) -> bool:
        if not self.bot_username:
            return False
        needle = f"@{self.bot_username}"
        for entities in (message.get("entities"), message.get("caption_entities")):
            for entity in entities or []:
                if entity.get("type") == "mention" and needle in text:
                    return True
        return needle in text

    async def _build_attachment(self, field: str, media: Any) -> Attachment | None:
        if field == "photo" and isinstance(media, list):
            media = max(media, key=lambda item: int(item.get("width", 0) or 0)) if media else None
        if not isinstance(media, dict) or not media.get("file_id"):
            return None
        kind = _MEDIA_KIND[field]
        file_path = ""
        try:
            result = await self._request("getFile", {"file_id": media["file_id"]}) or {}
            file_path = str(result.get("file_path", ""))
        except ChannelAdapterError:
            file_path = ""
        token = self._token() or ""
        url = file_download_url(self.api_base, token, file_path) if file_path else ""
        return Attachment(
            kind=kind,
            url=url,
            filename=str(media.get("file_name", "")),
            mime_type=str(media.get("mime_type", "")),
            size=int(media.get("file_size", 0) or 0) or None,
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
        metadata = metadata or {}
        edit_id = str(metadata.get("edit_message_id") or "")
        if edit_id:
            return await self.edit_message(chat_id, edit_id, content)
        payload: dict[str, Any] = {"chat_id": chat_id, "text": str(content)[:MAX_TEXT_LENGTH]}
        if reply_to and str(reply_to).isdigit():
            payload["reply_to_message_id"] = int(reply_to)
        try:
            result = await self._request("sendMessage", payload)
        except AdapterAuthError as exc:
            return SendResult(ok=False, error=str(exc), retryable=False)
        except ChannelAdapterError as exc:
            return SendResult(ok=False, error=str(exc), retryable=True)
        return SendResult(ok=True, message_id=str((result or {}).get("message_id", "")))

    async def edit_message(self, chat_id: str, message_id: str, content: str) -> SendResult:
        payload = {
            "chat_id": chat_id,
            "message_id": int(message_id) if str(message_id).isdigit() else message_id,
            "text": str(content)[:MAX_TEXT_LENGTH],
        }
        try:
            await self._request("editMessageText", payload)
        except AdapterAuthError as exc:
            return SendResult(ok=False, error=str(exc), retryable=False)
        except ChannelAdapterError as exc:
            return SendResult(ok=False, error=str(exc), retryable=True)
        return SendResult(ok=True, message_id=str(message_id))

    # -- offset state (SQLite) ------------------------------------------------------

    def _state_connection(self) -> sqlite3.Connection:
        if self._state_db is None:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_db = sqlite3.connect(self.state_path)
            self._state_db.execute(
                "CREATE TABLE IF NOT EXISTS adapter_state"
                " (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
        return self._state_db

    def _offset_key(self) -> str:
        return f"telegram/{self.account}/offset"

    def _load_offset(self) -> int:
        try:
            row = self._state_connection().execute(
                "SELECT value FROM adapter_state WHERE key=?", (self._offset_key(),)
            ).fetchone()
            return int(row[0]) if row else 0
        except sqlite3.Error:
            return 0

    def _persist_offset(self) -> None:
        try:
            with self._state_connection():
                self._state_db.execute(
                    "INSERT OR REPLACE INTO adapter_state(key, value) VALUES (?,?)",
                    (self._offset_key(), str(self._offset)),
                )
        except sqlite3.Error:
            logger.warning("Telegram offset 持久化失败", exc_info=True)


__all__ = ["TelegramAdapter", "file_download_url", "default_state_path"]
