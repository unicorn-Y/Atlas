"""Feishu / Lark channel adapter — lark-oapi (lazy-loaded), WebSocket default.

Receive modes (``config["mode"]``):
* ``websocket`` (default): ``lark.ws.Client`` long connection with an
  ``EventDispatcherHandler`` registered for ``im.message.receive_v1`` — mirrors the
  hermes WS distribution path.
* ``webhook``: the gateway HTTP route hands payloads to :meth:`handle_webhook`
  (URL-verification challenge echo + optional ``encrypt`` decryption via
  ``encrypt_key``; requires ``verification_token`` or ``encrypt_key``, as in hermes).

Inbound ``im.message.receive_v1`` normalizes into :class:`MessageEvent`: text and
``post``/rich-text bodies flatten to plain text, images/files/audio/media become
:class:`Attachment` entries (media stays key-referenced; resource download is a
gateway-side concern), mention keys (``@_user_1``) resolve against the event's
mention list, ``root_id`` maps to ``reply_to_event_id`` and group chats set
``is_group``.

Outbound uses ``im/v1/messages`` (receive_id_type ``chat_id``) or the reply API when
``reply_to`` carries a message id. Content prefixes switch the msg_type:
``interactive:`` / ``post:`` / ``image:`` expect a JSON body after the prefix;
anything else sends as ``text``.

Credentials (config key first, then ``atlas.channel.feishu.*`` / env): ``app_id``,
``app_secret``; webhook mode adds ``verification_token`` / ``encrypt_key``.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import uuid
from typing import Any

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

_MAX_MESSAGE_LENGTH = 15_000
_OUTBOUND_PREFIXES = {"interactive": "interactive:", "post": "post:", "image": "image:"}
# Feishu error codes the delivery queue may retry (transient server-side conditions).
_RETRYABLE_CODES = {99991400, 99991401, 99991402}


def _get(obj: Any, *path: str) -> Any:
    """Defensive attribute/item traversal (SDK objects and webhook dicts both work)."""
    current = obj
    for key in path:
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(key)
        else:
            current = getattr(current, key, None)
    return current


def _flatten_post(content: dict[str, Any]) -> str:
    """Feishu ``post``/``rich_text`` JSON → plain text (hermes parity: paragraphs join
    text/a/at runs with newlines; ``@_user_i`` placeholders resolve later)."""
    lines: list[str] = []
    for block in content.get("content") or []:
        if not isinstance(block, list):
            continue
        parts: list[str] = []
        for el in block:
            if not isinstance(el, dict):
                continue
            tag = el.get("tag")
            if tag == "text":
                parts.append(str(el.get("text") or ""))
            elif tag == "a":
                parts.append(str(el.get("text") or el.get("href") or ""))
            elif tag == "at":
                parts.append(f"@{el.get('user_name') or el.get('user_id') or ''}".strip())
        lines.append("".join(parts))
    text = "\n".join(line for line in lines)
    title = str(content.get("title") or "")
    if title and text:
        return f"{title}\n{text}"
    return text or title


class FeishuAdapter(ChannelAdapter):
    """lark-oapi adapter. SDK imported lazily; see :meth:`is_available`."""

    name = "feishu"
    max_message_length = _MAX_MESSAGE_LENGTH

    def __init__(self, config: dict[str, Any], dispatcher) -> None:
        super().__init__(config, dispatcher)
        self._credentials = config.get("credentials")
        self._mode = str(config.get("mode") or "websocket").strip().lower()
        self._app_id = str(config.get("app_id") or self._secret("app_id") or "")
        self._app_secret = str(config.get("app_secret") or self._secret("app_secret") or "")
        self._verification_token = str(
            config.get("verification_token") or self._secret("verification_token") or "")
        self._encrypt_key = str(config.get("encrypt_key") or self._secret("encrypt_key") or "")
        self._bot_open_id = str(config.get("bot_open_id") or self._secret("bot_open_id") or "")
        self._client: Any = None
        self._lark: Any = None
        self._ws_client: Any = None
        self._ws_task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._running = False

    def _secret(self, field: str) -> str | None:
        store = self.config.get("credentials")
        if store is not None and hasattr(store, "get"):
            try:
                value = store.get("feishu", field)
                if value:
                    return value
            except Exception:
                logger.exception("Feishu credential lookup failed")
        return get_channel_secret("feishu", field)

    # -- availability / lifecycle ------------------------------------------------

    @classmethod
    def is_available(cls) -> bool:
        try:
            import lark_oapi  # noqa: F401
        except ImportError:
            return False
        return True

    async def start(self) -> None:
        if not self.is_available():
            raise ChannelAdapterError("sdk not installed: lark-oapi")
        if not self._app_id or not self._app_secret:
            raise ChannelAdapterError("feishu: app_id and app_secret are required")
        if self._mode not in ("websocket", "webhook"):
            raise ChannelAdapterError(
                f"feishu: unsupported mode {self._mode!r} (websocket|webhook)")
        if self._mode == "webhook" and not (self._verification_token or self._encrypt_key):
            raise ChannelAdapterError(
                "feishu: webhook mode requires verification_token or encrypt_key")
        import lark_oapi as lark

        self._lark = lark
        self._loop = asyncio.get_running_loop()
        self._client = (lark.Client.builder()
                        .app_id(self._app_id).app_secret(self._app_secret).build())
        self._running = True
        if self._mode == "websocket":
            handler = self._build_event_handler(lark)
            self._ws_client = lark.ws.Client(
                self._app_id, self._app_secret, event_handler=handler,
                log_level=getattr(lark, "LogLevel", None) and lark.LogLevel.INFO)
            self._ws_task = asyncio.create_task(self._run_websocket())
        # webhook mode: ingress flows through handle_webhook() from the gateway route.
        logger.info("[feishu] started in %s mode (account=%s)", self._mode, self.account_id())

    async def stop(self) -> None:
        self._running = False
        ws, self._ws_client = self._ws_client, None
        # Best-effort close for SDKs exposing one; real lark ws threads are torn down by
        # the integration wave's supervisor (hermes parity: send a CLOSE frame first).
        if ws is not None and callable(getattr(ws, "close", None)):
            try:
                await asyncio.to_thread(ws.close)
            except Exception:
                logger.debug("[feishu] ws close failed", exc_info=True)
        task, self._ws_task = self._ws_task, None
        if task is not None:
            task.cancel()
            try:
                await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=5.0)
            except (TimeoutError, asyncio.CancelledError):
                logger.debug("[feishu] ws task did not exit cleanly")
        self._client = None

    async def _run_websocket(self) -> None:
        """Drive the SDK's blocking ``start()`` off-loop; restart with a short backoff
        (the SDK auto-reconnects internally; this guards a dead ``start()`` return)."""
        while self._running and self._ws_client is not None:
            try:
                await asyncio.to_thread(self._ws_client.start)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("[feishu] websocket client error: %s", exc, exc_info=True)
            if not self._running:
                return
            await asyncio.sleep(5)

    def _build_event_handler(self, lark: Any) -> Any:
        builder = lark.EventDispatcherHandler.builder(self._encrypt_key, self._verification_token)
        builder.register_p2_im_message_receive_v1(self._on_message_event)
        return builder.build()

    # -- inbound ------------------------------------------------------------------

    def _on_message_event(self, data: Any) -> None:
        """WS-thread callback: normalize then marshal onto the adapter loop."""
        event = self._normalize_event(data)
        if event is None or self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._safe_dispatch(event), self._loop)

    async def _safe_dispatch(self, event: MessageEvent) -> None:
        try:
            await self._dispatch(event)
        except Exception:
            logger.exception("[feishu] dispatcher failed for event %s", event.event_id)

    async def handle_webhook(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Webhook-mode ingress for the gateway route (``/api/channels/feishu/inbound``).

        Answers Feishu's ``url_verification`` handshake (``{"challenge": ...}``; the
        encrypted variant is decrypted with ``encrypt_key``), otherwise normalizes the
        event and dispatches it. Returns the JSON response body (or ``None``)."""
        if not isinstance(payload, dict):
            return None
        if payload.get("type") == "url_verification":
            challenge = str(payload.get("challenge") or "")
            encrypt = payload.get("encrypt")
            if encrypt and self._encrypt_key:
                try:
                    decrypted = json.loads(self._decrypt_event(str(encrypt)))
                    challenge = str(decrypted.get("challenge") or challenge)
                except Exception:
                    logger.warning("[feishu] url_verification decrypt failed", exc_info=True)
                    return {"challenge": ""}
            return {"challenge": challenge}
        if payload.get("encrypt") and self._encrypt_key:
            try:
                payload = json.loads(self._decrypt_event(str(payload["encrypt"])))
            except Exception:
                logger.warning("[feishu] event decrypt failed", exc_info=True)
                return None
        event = self._normalize_event(payload)
        if event is not None:
            await self._safe_dispatch(event)
        return None

    def _decrypt_event(self, encrypt: str) -> str:
        """Feishu event decryption: AES-256-CBC, key = SHA-256(encrypt_key), base64 body,
        16-byte random IV prefix, PKCS7 padding (documented Feishu event scheme)."""
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        key = hashlib.sha256(self._encrypt_key.encode("utf-8")).digest()
        raw = base64.b64decode(encrypt)
        cipher = Cipher(algorithms.AES(key), modes.CBC(raw[:16]), backend=default_backend())
        decryptor = cipher.decryptor()
        padded = decryptor.update(raw[16:]) + decryptor.finalize()
        pad = padded[-1]
        if pad < 1 or pad > 32 or padded[-pad:] != bytes([pad]) * pad:
            raise ChannelAdapterError("feishu: invalid event padding")
        return padded[:-pad].decode("utf-8")

    def _normalize_event(self, data: Any) -> MessageEvent | None:
        message = _get(data, "event", "message")
        if message is None:
            return None
        header = _get(data, "header") or {}
        sender = _get(data, "event", "sender") or {}
        if str(_get(sender, "sender_type") or "user") != "user":
            return None  # bot/self echoes never reach the gateway

        try:
            content = json.loads(str(_get(message, "content") or "{}"))
            if not isinstance(content, dict):
                content = {"text": str(_get(message, "content") or "")}
        except (TypeError, ValueError):
            content = {"text": str(_get(message, "content") or "")}
        mtype = str(_get(message, "message_type") or "text")

        mentions = [m for m in (_get(message, "mentions") or []) if isinstance(m, dict)]
        mention_map: dict[str, str] = {}
        for mention in mentions:
            key = str(mention.get("key") or "")
            if key:
                mention_map[key] = str(
                    mention.get("name") or mention.get("id", {}).get("user_id") or key)

        text = ""
        kind = MessageType.TEXT
        attachments: list[Attachment] = []
        if mtype in ("text", "post", "rich_text"):
            text = str(content.get("text") or "") if mtype == "text" else _flatten_post(content)
        elif mtype == "image":
            kind = MessageType.IMAGE
            attachments.append(Attachment(
                kind=kind, meta={"image_key": str(content.get("image_key") or "")}))
        elif mtype == "file":
            kind = MessageType.FILE
            attachments.append(Attachment(
                kind=kind,
                filename=str(content.get("file_name") or ""),
                meta={"file_key": str(content.get("file_key") or "")}))
        elif mtype == "audio":
            kind = MessageType.AUDIO
            attachments.append(Attachment(
                kind=kind, meta={"file_key": str(content.get("file_key") or ""),
                                 "duration_ms": content.get("duration")}))
        elif mtype == "media":
            kind = MessageType.VIDEO
            attachments.append(Attachment(
                kind=kind, filename=str(content.get("file_name") or ""),
                meta={"file_key": str(content.get("file_key") or ""),
                      "image_key": str(content.get("image_key") or "")}))
        elif mtype == "sticker":
            kind = MessageType.STICKER
            attachments.append(Attachment(
                kind=kind, meta={"file_key": str(content.get("file_key") or "")}))
        else:
            text = str(content.get("text") or json.dumps(content, ensure_ascii=False))

        for key, name in mention_map.items():
            if key in text:
                text = text.replace(key, f"@{name}")
        # Mention gating info only — the gateway's gating module owns policy.
        if self._bot_open_id:
            is_mention = any(
                self._bot_open_id in json.dumps(m.get("id") or {}, ensure_ascii=False)
                for m in mentions)
        else:
            is_mention = bool(mentions)

        root_id = str(_get(message, "root_id") or "")
        event_id = str(_get(header, "event_id") or _get(message, "message_id") or "")
        create_time = str(_get(header, "create_time") or "0")
        try:
            ts = float(create_time) / 1000.0 if create_time else 0.0
        except ValueError:
            ts = 0.0
        chat_type = str(_get(message, "chat_type") or "p2p")
        sender_id = str(_get(sender, "sender_id", "open_id")
                        or _get(sender, "sender_id", "user_id") or "")
        return MessageEvent(
            channel=self.name,
            account=self.account_id(),
            event_id=event_id or str(_get(message, "message_id") or ""),
            chat_id=str(_get(message, "chat_id") or ""),
            sender_id=sender_id,
            kind=kind if (attachments or not text) else MessageType.TEXT,
            text=text,
            thread_id="",
            sender_name="",
            is_group=chat_type == "group",
            is_mention=is_mention,
            reply_to_event_id=root_id,
            attachments=attachments,
            ts=ts,
            raw={"message": message if isinstance(message, dict) else str(message)},
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
        if self._client is None or self._lark is None:
            return SendResult(ok=False, error="not connected")
        msg_type, body_obj = self._build_outbound(content)
        content_json = json.dumps(body_obj, ensure_ascii=False)
        lark = self._lark
        try:
            if reply_to:
                body = lark.im.v1.ReplyMessageRequestBody.builder() \
                    .content(content_json).msg_type(msg_type).build()
                request = lark.im.v1.ReplyMessageRequest.builder() \
                    .message_id(reply_to).request_body(body).build()
                response = await asyncio.to_thread(self._client.im.v1.message.reply, request)
            else:
                body = lark.im.v1.CreateMessageRequestBody.builder() \
                    .receive_id(chat_id).msg_type(msg_type).content(content_json) \
                    .uuid(uuid.uuid4().hex).build()
                request = lark.im.v1.CreateMessageRequest.builder() \
                    .receive_id_type("chat_id").request_body(body).build()
                response = await asyncio.to_thread(self._client.im.v1.message.create, request)
        except Exception as exc:
            logger.exception("Feishu message send failed")
            return SendResult(ok=False, error=str(exc), retryable=True)
        if not self._response_succeeded(response):
            code = int(getattr(response, "code", 0) or 0)
            return SendResult(
                ok=False, error=f"feishu api error {code}: {getattr(response, 'msg', '')}",
                retryable=code in _RETRYABLE_CODES)
        message_id = str(_get(getattr(response, "data", None), "message_id") or "")
        return SendResult(ok=True, message_id=message_id)

    def _build_outbound(self, content: str) -> tuple[str, dict[str, Any]]:
        """``interactive:/post:/image:`` prefixes carry a JSON body; plain content sends
        as text. A malformed enhanced body falls back to text (never lose a message)."""
        for msg_type, prefix in _OUTBOUND_PREFIXES.items():
            if content.startswith(prefix):
                try:
                    parsed = json.loads(content[len(prefix):])
                    if isinstance(parsed, dict):
                        if msg_type == "image":
                            return msg_type, {"image_key": str(parsed.get("image_key") or "")}
                        return msg_type, parsed
                except (TypeError, ValueError):
                    break
        return "text", {"text": content[: self.max_message_length]}

    @staticmethod
    def _response_succeeded(response: Any) -> bool:
        success = getattr(response, "success", None)
        if callable(success):
            try:
                return bool(success())
            except Exception:
                logger.exception("Feishu response status check failed")
                return False
        return bool(response)

    # -- metadata -----------------------------------------------------------------

    async def get_chat_info(self, chat_id: str) -> dict[str, Any]:
        if self._client is None or self._lark is None:
            return {}
        try:
            request = self._lark.im.v1.GetChatRequest.builder().chat_id(chat_id).build()
            response = await asyncio.to_thread(self._client.im.v1.chat.get, request)
            if not self._response_succeeded(response):
                return {}
            data = getattr(response, "data", None)
            return {"name": str(_get(data, "name") or chat_id), "type": "group"}
        except Exception:
            logger.debug("[feishu] get_chat_info failed for %s", chat_id, exc_info=True)
            return {}
