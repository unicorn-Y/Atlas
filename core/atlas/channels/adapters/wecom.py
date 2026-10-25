"""WeCom (企业微信) channel adapter — self-built-app HTTP callback mode.

The transport mirrors the hermes ``wecom_callback`` adapter, split for Atlas: the
gateway HTTP route (or the adapter's own optional aiohttp listener, ``config["port"]``)
hands requests to :meth:`handle_verify` (GET URL verification — the ``echostr`` is
decrypted and echoed) and :meth:`handle_callback` (POST encrypted XML — decrypted via
the ported :mod:`..._vendor.wecom_crypto` / ``WXBizMsgCrypt``, acked immediately, and
dispatched as :class:`MessageEvent`).

Outbound is proactive ``message/send`` (``touser`` + ``agentid``) through the ported
:mod:`..._vendor.wecom_send_queue` per-chat FIFO with the 30 msgs/min token bucket;
content is chunked to the API's 2048-byte ``text.content`` cap. Access tokens cache per
app and refresh on ``40001``/``42001`` rejections.

chat_id convention (hermes parity): ``<corp_id>:<user_id>``; a bare user id resolves
against users seen inbound.

Dependencies: ``cryptography`` (lazy, via the vendored crypto) and ``httpx``; ``aiohttp``
only when the built-in listener is enabled. Credentials (config first, then
``atlas.channel.wecom.*`` / env): ``corp_id`` / ``corp_secret`` / ``agent_id`` /
``token`` / ``encoding_aes_key``; multi-app via ``config["apps"]``.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any
from xml.etree import ElementTree as ET

from atlas.channels.adapters._vendor import wecom_crypto
from atlas.channels.adapters._vendor.credentials_bridge import get_channel_secret
from atlas.channels.adapters._vendor.wecom_crypto import WeComCryptoError, WXBizMsgCrypt
from atlas.channels.adapters._vendor.wecom_send_queue import ChatSendQueueMixin
from atlas.channels.contract import (
    ChannelAdapter,
    ChannelAdapterError,
    MessageEvent,
    MessageType,
    SendResult,
)

logger = logging.getLogger(__name__)

DEFAULT_PATH = "/wecom/callback"
_MAX_BODY = 65_536  # pre-auth body cap: callbacks are small encrypted XML envelopes
ACCESS_TOKEN_TTL_SECONDS = 7200
MESSAGE_DEDUP_TTL_SECONDS = 300
_SEND_URL = "https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token="
_TOKEN_URL = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
_TOKEN_RETRY_CODES = {40001, 42001}


def _utf8_len(text: str) -> int:
    return len(text.encode("utf-8"))


def _split_utf8_chunks(text: str, max_bytes: int) -> list[str]:
    """Split on the 2048-BYTE cap without cutting a multibyte character (message/send
    keeps only the first 2048 bytes of ``text.content`` and drops the rest silently)."""
    chunks: list[str] = []
    current: list[str] = []
    used = 0
    for char in text:
        size = _utf8_len(char)
        if current and used + size > max_bytes:
            chunks.append("".join(current))
            current, used = [], 0
        current.append(char)
        used += size
    if current:
        chunks.append("".join(current))
    return chunks or [""]


def _parse_xml(xml_text: str) -> ET.Element:
    """Untrusted pre-auth bodies prefer defusedxml (billion-laughs / XXE), stdlib fallback
    keeps the adapter importable without the extra."""
    try:
        import defusedxml.ElementTree

        return defusedxml.ElementTree.fromstring(xml_text)
    except ImportError:
        return ET.fromstring(xml_text)


class WeComAdapter(ChatSendQueueMixin, ChannelAdapter):
    """Callback-mode adapter. See :meth:`is_available`; crypto is vendored + lazy."""

    name = "wecom"
    # message/send keeps only the first 2048 BYTES of text.content and drops the rest silently.
    max_message_length = 2048

    def __init__(self, config: dict[str, Any], dispatcher) -> None:
        ChannelAdapter.__init__(self, config, dispatcher)
        self._credentials = config.get("credentials")
        self._apps: list[dict[str, Any]] = self._normalize_apps(config)
        self._path = str(config.get("path") or DEFAULT_PATH)
        # ChatSendQueueMixin state (ported): two lanes per chat + token usage.
        self._chat_queues: dict[str, asyncio.Queue] = {}
        self._chat_workers: dict[str, asyncio.Task] = {}
        self._control_queues: dict[str, asyncio.Queue] = {}
        self._control_workers: dict[str, asyncio.Task] = {}
        self._chat_token_usage: dict[str, dict[str, float]] = {}
        self._http_client: Any = None
        self._runner: Any = None
        self._running = False
        self._user_app_map: dict[str, str] = {}
        self._access_tokens: dict[str, dict[str, Any]] = {}
        self._dedup: dict[str, float] = {}

    # -- configuration ------------------------------------------------------------

    def _secret(self, field: str) -> str | None:
        store = self.config.get("credentials")
        if store is not None and hasattr(store, "get"):
            try:
                value = store.get("wecom", field)
                if value:
                    return value
            except Exception:
                logger.exception("WeCom credential lookup failed")
        return get_channel_secret("wecom", field)

    def _normalize_apps(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        """Single-app config dict or ``config["apps"]`` list (hermes parity); single-app
        fields fall back to ``atlas.channel.wecom.*`` credentials / env when absent."""
        apps = config.get("apps")
        if isinstance(apps, list) and apps:
            return [dict(app) for app in apps if isinstance(app, dict)]

        def _field(key: str) -> str:
            return str(config.get(key) or self._secret(key) or "")

        corp_id, encoding_aes_key = _field("corp_id"), _field("encoding_aes_key")
        if corp_id or encoding_aes_key:
            return [{
                "name": config.get("name") or "default",
                "corp_id": corp_id,
                "corp_secret": _field("corp_secret"),
                "agent_id": _field("agent_id"),
                "token": _field("token"),
                "encoding_aes_key": encoding_aes_key,
            }]
        return []

    # -- availability / lifecycle ------------------------------------------------

    @classmethod
    def is_available(cls) -> bool:
        return wecom_crypto.cryptography_available()

    async def start(self) -> None:
        if not wecom_crypto.cryptography_available():
            raise ChannelAdapterError("sdk not installed: cryptography")
        try:
            import httpx
        except ImportError as exc:
            raise ChannelAdapterError("sdk not installed: httpx") from exc
        if not self._apps:
            raise ChannelAdapterError("wecom: corp callback app configuration is required")
        self._http_client = httpx.AsyncClient(timeout=20.0)
        self._running = True
        if self.config.get("port"):
            await self._start_listener()
        # Access tokens refresh lazily on the first send (offline-friendly; hermes
        # refreshes at connect, Atlas defers so a misconfigured corp secret cannot
        # block adapter startup).
        logger.info("[wecom] started (%d app(s), account=%s)", len(self._apps), self.account_id())

    async def stop(self) -> None:
        self._running = False
        for workers in (self._chat_workers, self._control_workers):
            for task in list(workers.values()):
                task.cancel()
        for queues in (self._chat_queues, self._control_queues,
                       self._chat_workers, self._control_workers):
            queues.clear()
        self._chat_token_usage.clear()
        runner, self._runner = self._runner, None
        if runner is not None:
            try:
                await runner.cleanup()
            except Exception:
                logger.debug("[wecom] listener cleanup failed", exc_info=True)
        client, self._http_client = self._http_client, None
        if client is not None:
            await client.aclose()

    async def _start_listener(self) -> None:
        """Optional standalone aiohttp listener (the integration wave can instead wire
        the gateway route straight to handle_verify/handle_callback)."""
        try:
            from aiohttp import web
        except ImportError as exc:
            raise ChannelAdapterError("sdk not installed: aiohttp") from exc

        async def _verify(request: web.Request) -> web.Response:
            status, text = await self.handle_verify(dict(request.query))
            return web.Response(status=status, text=text, content_type="text/plain")

        async def _callback(request: web.Request) -> web.Response:
            body = await request.read()
            query = dict(request.query)
            status, text = await self.handle_callback(query, body.decode("utf-8", errors="replace"))
            return web.Response(status=status, text=text, content_type="text/plain")

        app = web.Application(client_max_size=_MAX_BODY)
        app.router.add_get(self._path, _verify)
        app.router.add_post(self._path, _callback)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        from aiohttp import TCPSite

        await TCPSite(self._runner, str(self.config.get("host") or "0.0.0.0"),
                      int(self.config["port"])).start()
        logger.info("[wecom] HTTP listener on %s:%s%s",
                    self.config.get("host") or "0.0.0.0", self.config.get("port"), self._path)

    # -- inbound ------------------------------------------------------------------

    async def handle_verify(self, query: dict[str, str]) -> tuple[int, str]:
        """GET URL verification handshake: decrypt ``echostr`` and echo the plaintext."""
        msg_signature = str(query.get("msg_signature") or "")
        timestamp = str(query.get("timestamp") or "")
        nonce = str(query.get("nonce") or "")
        echostr = str(query.get("echostr") or "")
        for app in self._apps:
            try:
                crypt = self._crypt_for_app(app)
                plain = crypt.verify_url(msg_signature, timestamp, nonce, echostr)
                return 200, plain
            except Exception:
                logger.debug("[wecom] url verification failed for app %r",
                             app.get("name", "default"), exc_info=True)
                continue
        return 403, "signature verification failed"

    async def handle_callback(self, query: dict[str, str], body: str) -> tuple[int, str]:
        """POST encrypted callback: decrypt, normalize, dispatch, and ack at once (the
        reply arrives later via proactive ``message/send``)."""
        msg_signature = str(query.get("msg_signature") or "")
        timestamp = str(query.get("timestamp") or "")
        nonce = str(query.get("nonce") or "")
        if _utf8_len(body) > _MAX_BODY:
            logger.warning("[wecom] payload too large (%d bytes) — rejected", _utf8_len(body))
            return 413, "payload too large"
        for app in self._apps:
            try:
                encrypt = _parse_xml(body).findtext("Encrypt", default="")
                xml_text = self._crypt_for_app(app).decrypt(
                    msg_signature, timestamp, nonce, encrypt).decode("utf-8")
            except WeComCryptoError:
                continue
            except Exception:
                logger.exception("[wecom] error decrypting callback")
                break
            try:
                event = self._build_event(app, xml_text)
                if event is not None:
                    # WeCom retries callbacks on timeout → duplicate inbound messages.
                    now = time.monotonic()
                    self._dedup = {
                        key: stamp for key, stamp in self._dedup.items()
                        if now - stamp < MESSAGE_DEDUP_TTL_SECONDS}
                    if event.event_id in self._dedup:
                        return 200, "success"
                    self._dedup[event.event_id] = now
                    self._user_app_map[event.chat_id] = str(app.get("name") or "default")
                    await self._dispatch(event)
                return 200, "success"  # ack immediately — reply is proactive
            except Exception:
                logger.exception("[wecom] error handling message")
                break
        return 400, "invalid callback payload"

    def _build_event(self, app: dict[str, Any], xml_text: str) -> MessageEvent | None:
        root = _parse_xml(xml_text)
        find = lambda tag: (root.findtext(tag) or "")  # noqa: E731
        msg_type = find("MsgType").lower()
        # Lifecycle events (enter_agent/subscribe) and non-text types are silently acked.
        if msg_type not in {"text", "event"} or (
            msg_type == "event" and find("Event").lower() in {"enter_agent", "subscribe"}
        ):
            return None
        user_id = find("FromUserName")
        corp_id = find("ToUserName") or str(app.get("corp_id") or "")
        content = find("Content").strip() or ("/start" if msg_type == "event" else "")
        if not content:
            return None
        msg_id = find("MsgId") or f"{user_id}:{find('CreateTime') or '0'}"
        is_group = user_id.startswith("wr")
        text_mentions = list(dict.fromkeys(re.findall(r"@([^\s,，:：@]{1,80})", content)))
        return MessageEvent(
            channel=self.name,
            account=self.account_id(),
            event_id=str(msg_id),
            chat_id=self._user_app_key(corp_id, user_id),
            sender_id=user_id,
            kind=MessageType.TEXT,
            text=content,
            sender_name=user_id,
            is_group=is_group,
            is_mention=bool(text_mentions),
            mentions=text_mentions,
            ts=float(find("CreateTime") or 0) or time.time(),
            raw={"xml": xml_text, "app": str(app.get("name") or "default")},
        )

    # -- outbound -----------------------------------------------------------------

    async def send(
        self,
        chat_id: str,
        content: str,
        *,
        reply_to: str = "",
        attachments: list[Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SendResult:
        """One text message per 2048-byte chunk through the per-chat FIFO + token bucket;
        stops at the first failure."""
        if self._http_client is None:
            return SendResult(ok=False, error="not connected")
        app = self._resolve_app_for_chat(chat_id)
        try:
            last_message_id = ""
            for chunk in _split_utf8_chunks(content, self.max_message_length):
                result = await self._enqueue_chat_send(
                    chat_id, lambda chunk=chunk: self._send_text(app, chat_id, chunk))
                if isinstance(result, SendResult):
                    if not result.ok:
                        return result
                    last_message_id = result.message_id or last_message_id
                else:
                    return SendResult(ok=False, error=str(result))
        except Exception as exc:  # queue worker cancelled during shutdown, etc.
            logger.exception("WeCom queued message failed")
            return SendResult(ok=False, error=str(exc), retryable=True)
        return SendResult(ok=True, message_id=last_message_id)

    async def _send_text(self, app: dict[str, Any], chat_id: str, content: str) -> SendResult:
        try:
            payload = {
                "touser": chat_id.split(":", 1)[-1],
                "msgtype": "text",
                "agentid": int(str(app.get("agent_id") or 0)),
                "text": {"content": content},
                "safe": 0,
            }
            for attempt in range(2):
                token = await self._get_access_token(app)
                response = await self._http_client.post(f"{_SEND_URL}{token}", json=payload)
                data = response.json()
                errcode = data.get("errcode")
                if errcode in _TOKEN_RETRY_CODES and attempt == 0:
                    # token rejected — evict so the retry fetches a fresh one
                    logger.warning("[wecom] token rejected for app %r (errcode=%s), refreshing",
                                   app.get("name", "default"), errcode)
                    self._access_tokens.pop(str(app["name"]), None)
                    continue
                if errcode == 0:
                    return SendResult(ok=True, message_id=str(data.get("msgid") or ""))
                return SendResult(ok=False, error=str(data),
                                  retryable=errcode in {-1, 45009})
            return SendResult(ok=False, error="send failed after token refresh")
        except Exception as exc:
            logger.exception("WeCom message send failed")
            return SendResult(ok=False, error=str(exc), retryable=True)

    # -- helpers ------------------------------------------------------------------

    @staticmethod
    def _user_app_key(corp_id: str, user_id: str) -> str:
        return f"{corp_id}:{user_id}" if corp_id else user_id

    def _resolve_app_for_chat(self, chat_id: str) -> dict[str, Any]:
        app_name = self._user_app_map.get(chat_id)
        if not app_name and ":" not in chat_id:  # legacy bare user_id — unique match only
            matching = [key for key in self._user_app_map if key.endswith(f":{chat_id}")]
            app_name = self._user_app_map.get(matching[0]) if len(matching) == 1 else app_name
        for app in self._apps:
            if app.get("name") == app_name:
                return app
        return self._apps[0]

    def _crypt_for_app(self, app: dict[str, Any]) -> WXBizMsgCrypt:
        return WXBizMsgCrypt(
            token=str(app.get("token") or ""),
            encoding_aes_key=str(app.get("encoding_aes_key") or ""),
            receive_id=str(app.get("corp_id") or ""),
        )

    async def _get_access_token(self, app: dict[str, Any]) -> str:
        cached = self._access_tokens.get(str(app["name"]))
        if cached and cached.get("expires_at", 0) > time.time() + 60:
            return str(cached["token"])
        return await self._refresh_access_token(app)

    async def _refresh_access_token(self, app: dict[str, Any]) -> str:
        response = await self._http_client.get(
            _TOKEN_URL, params={"corpid": app.get("corp_id"), "corpsecret": app.get("corp_secret")})
        data = response.json()
        if data.get("errcode") != 0:
            raise RuntimeError(f"WeCom token refresh failed: {data}")
        token = data["access_token"]
        expires_in = int(data.get("expires_in", ACCESS_TOKEN_TTL_SECONDS))
        self._access_tokens[str(app["name"])] = {
            "token": token, "expires_at": time.time() + expires_in}
        return token

    async def get_chat_info(self, chat_id: str) -> dict[str, Any]:
        return {"name": chat_id, "type": "dm"}
