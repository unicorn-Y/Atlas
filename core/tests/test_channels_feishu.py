"""W2b Feishu adapter tests — WS + webhook flows driven with a stubbed lark_oapi (no real SDK)."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import sys
import threading
import types
from typing import Any

import pytest

from atlas.channels.contract import ChannelAdapterError, MessageType

# ---------------------------------------------------------------------------
# stub lark_oapi module
# ---------------------------------------------------------------------------

class _ApiRequest(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def _request_class():
    class _Cls(_ApiRequest):
        @classmethod
        def builder(cls):
            return _Builder(cls)

    return _Cls


class _Builder:
    def __init__(self, ctor):
        self._ctor, self._kw = ctor, {}

    def __getattr__(self, name):
        def _set(*args, **kwargs):
            self._kw[name] = args[0] if args else kwargs
            return self

        return _set

    def build(self):
        return self._ctor(**self._kw)


def _make_lark_stubs(fail_send: bool = False) -> dict[str, Any]:
    class _Response:
        def __init__(self, ok: bool, message_id: str = "", name: str = ""):
            self._ok = ok
            self.code = 0 if ok else 99991672
            self.msg = "ok" if ok else "no permission"
            self.data = types.SimpleNamespace(message_id=message_id, name=name)

        def success(self):
            return self._ok

    class _MessageApi:
        def __init__(self, client):
            self._client = client

        # Real lark-oapi client methods are SYNC (the adapter wraps them with to_thread).

        def create(self, request):
            self._client.create_calls.append(request)
            if fail_send:
                return _Response(False)
            return _Response(True, message_id="om_out_1")

        def reply(self, request):
            self._client.reply_calls.append(request)
            return _Response(True, message_id="om_reply_1")

    class _ChatApi:
        def __init__(self, client):
            self._client = client

        def get(self, request):
            return _Response(True, name="Test Chat")

    class _Client:
        instances: list[Any] = []

        def __init__(self, **kw):
            self.kw = kw
            self.create_calls: list[Any] = []
            self.reply_calls: list[Any] = []
            self.im = types.SimpleNamespace(v1=types.SimpleNamespace(
                message=_MessageApi(self), chat=_ChatApi(self)))
            _Client.instances.append(self)

        @classmethod
        def builder(cls):
            return _Builder(cls)

    class _HandlerBuilder:
        def __init__(self, encrypt_key, verification_token):
            _HandlerBuilder.keys = (encrypt_key, verification_token)
            self.callbacks: dict[str, Any] = {}

        def register_p2_im_message_receive_v1(self, callback):
            self.callbacks["im.message.receive_v1"] = callback
            return self

        def build(self):
            return types.SimpleNamespace(callbacks=self.callbacks)

    class _EventDispatcherHandler:
        @classmethod
        def builder(cls, encrypt_key="", verification_token=""):
            return _HandlerBuilder(encrypt_key, verification_token)

    class _LogLevel:
        INFO = 20
        DEBUG = 10

    class _WsClient:
        instances: list[Any] = []

        def __init__(self, app_id, app_secret, event_handler=None, log_level=None):
            self.app_id, self.app_secret, self.event_handler = app_id, app_secret, event_handler
            self._stop = threading.Event()
            self.start_calls = 0
            self.closed = False
            _WsClient.instances.append(self)

        def start(self):
            self.start_calls += 1
            while not self._stop.is_set():
                self._stop.wait(0.02)

        def close(self):
            self.closed = True
            self._stop.set()

    ws_mod = types.ModuleType("lark_oapi.ws")
    ws_mod.Client = _WsClient
    im_mod = types.ModuleType("lark_oapi.im")
    v1_mod = types.ModuleType("lark_oapi.im.v1")
    v1_mod.CreateMessageRequest = _request_class()
    v1_mod.CreateMessageRequestBody = _request_class()
    v1_mod.ReplyMessageRequest = _request_class()
    v1_mod.ReplyMessageRequestBody = _request_class()
    v1_mod.GetChatRequest = _request_class()
    im_mod.v1 = v1_mod

    lark = types.ModuleType("lark_oapi")
    lark.Client = _Client
    lark.EventDispatcherHandler = _EventDispatcherHandler
    lark.LogLevel = _LogLevel
    lark.ws = ws_mod
    lark.im = im_mod

    return {
        "lark": lark, "_Client": _Client, "_WsClient": _WsClient,
        "_HandlerBuilder": _HandlerBuilder,
    }


@pytest.fixture
def lark_stubs(monkeypatch):
    stubs = _make_lark_stubs()
    monkeypatch.setitem(sys.modules, "lark_oapi", stubs["lark"])
    return stubs


class _Collector:
    def __init__(self):
        self.events = []

    async def __call__(self, event):
        self.events.append(event)


_LIVE_ADAPTERS: list[Any] = []


@pytest.fixture(autouse=True)
async def _cleanup_live_adapters():
    """Stop every adapter a test started — the stub WS thread must not outlive its loop."""
    yield
    for adapter in list(_LIVE_ADAPTERS):
        try:
            await adapter.stop()
        except Exception:
            pass
    _LIVE_ADAPTERS.clear()


def _adapter(**overrides):
    from atlas.channels.adapters.feishu import FeishuAdapter

    collector = _Collector()
    config: dict[str, Any] = {
        "app_id": "cli_test", "app_secret": "s3cret", "account": "main",
        "bot_open_id": "ou_bot", **overrides,
    }
    adapter = FeishuAdapter(config, collector)
    _LIVE_ADAPTERS.append(adapter)
    return adapter, collector


async def _drain(collector: _Collector, want: int = 1) -> None:
    for _ in range(200):
        if len(collector.events) >= want:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"expected {want} dispatch(es), got {len(collector.events)}")


def _text_event(text: str = "hello", chat_type: str = "group",
                root_id: str = "") -> types.SimpleNamespace:
    return types.SimpleNamespace(
        header=types.SimpleNamespace(event_id="evt-1", create_time="1770000000000"),
        event=types.SimpleNamespace(
            sender=types.SimpleNamespace(
                sender_type="user",
                sender_id=types.SimpleNamespace(open_id="ou_1", user_id="u1")),
            message=types.SimpleNamespace(
                message_type="text", content=json.dumps({"text": text}),
                chat_id="oc_chat1", message_id="om_in_1", root_id=root_id,
                chat_type=chat_type, mentions=[])))


# ---------------------------------------------------------------------------
# availability / lifecycle
# ---------------------------------------------------------------------------

async def test_start_raises_without_sdk(monkeypatch):
    monkeypatch.setitem(sys.modules, "lark_oapi", None)
    from atlas.channels.adapters.feishu import FeishuAdapter

    assert FeishuAdapter.is_available() is False
    adapter, _ = _adapter()
    with pytest.raises(ChannelAdapterError, match="sdk not installed: lark-oapi"):
        await adapter.start()


async def test_start_requires_credentials(monkeypatch):
    monkeypatch.setitem(sys.modules, "lark_oapi", _make_lark_stubs()["lark"])
    from atlas.channels.adapters.feishu import FeishuAdapter

    adapter = FeishuAdapter({"app_id": "", "app_secret": ""}, _Collector())
    with pytest.raises(ChannelAdapterError, match="app_id and app_secret"):
        await adapter.start()
    adapter = FeishuAdapter({"app_id": "a", "app_secret": "b", "mode": "webhook"}, _Collector())
    with pytest.raises(ChannelAdapterError, match="verification_token or encrypt_key"):
        await adapter.start()


async def test_start_websocket_mode_registers_handler(lark_stubs):
    adapter, _ = _adapter()
    await adapter.start()
    client = lark_stubs["_Client"].instances[-1]
    assert client.kw["app_id"] == "cli_test" and client.kw["app_secret"] == "s3cret"
    ws = lark_stubs["_WsClient"].instances[-1]
    assert ws.event_handler.callbacks["im.message.receive_v1"] is not None
    assert ws.app_id == "cli_test"
    await asyncio.sleep(0.05)  # let the WS thread enter start()
    await adapter.stop()
    assert ws.closed is True
    assert adapter._client is None


async def test_credentials_env_fallback(monkeypatch):
    monkeypatch.setitem(sys.modules, "lark_oapi", _make_lark_stubs()["lark"])
    monkeypatch.delenv("ATLAS_CHANNEL_FEISHU_APP_ID", raising=False)
    monkeypatch.delenv("ATLAS_CHANNEL_FEISHU_APP_SECRET", raising=False)
    from atlas.channels.adapters.feishu import FeishuAdapter

    adapter = FeishuAdapter({}, _Collector())
    with pytest.raises(ChannelAdapterError):
        await adapter.start()
    monkeypatch.setenv("ATLAS_CHANNEL_FEISHU_APP_ID", "env_app")
    monkeypatch.setenv("ATLAS_CHANNEL_FEISHU_APP_SECRET", "env_secret")
    adapter2 = FeishuAdapter({}, _Collector())
    await adapter2.start()
    assert adapter2._app_id == "env_app"
    await adapter2.stop()


# ---------------------------------------------------------------------------
# inbound normalization (WS handler)
# ---------------------------------------------------------------------------

async def test_inbound_text_with_mention_resolution(lark_stubs):
    adapter, collector = _adapter()
    await adapter.start()
    ws = lark_stubs["_WsClient"].instances[-1]
    handler = ws.event_handler.callbacks["im.message.receive_v1"]
    data = _text_event("@_user_1 ship it")
    data.event.message.mentions = [
        {"key": "@_user_1", "name": "Atlas Bot", "id": {"open_id": "ou_bot"}}]
    handler(data)
    await _drain(collector)

    event = collector.events[0]
    assert (event.channel, event.account, event.event_id) == ("feishu", "main", "evt-1")
    assert (event.chat_id, event.sender_id) == ("oc_chat1", "ou_1")
    assert event.text == "@Atlas Bot ship it"
    assert event.is_group is True and event.is_mention is True
    assert event.ts == pytest.approx(1770000000.0)


async def test_inbound_post_rich_text_flattens(lark_stubs):
    adapter, collector = _adapter()
    await adapter.start()
    handler = lark_stubs["_WsClient"].instances[-1].event_handler.callbacks["im.message.receive_v1"]
    data = _text_event()
    data.event.message.message_type = "post"
    data.event.message.content = json.dumps({
        "title": "Weekly",
        "content": [
            [{"tag": "text", "text": "line1 "}, {"tag": "a", "href": "https://x", "text": "docs"}],
            [{"tag": "at", "user_id": "ou_2"}],
        ]})
    handler(data)
    await _drain(collector)
    event = collector.events[0]
    assert event.kind is MessageType.TEXT
    # one output line per post paragraph; title first
    assert event.text == "Weekly\nline1 docs\n@ou_2"


async def test_inbound_image_file_audio_media(lark_stubs):
    adapter, collector = _adapter()
    await adapter.start()
    handler = lark_stubs["_WsClient"].instances[-1].event_handler.callbacks["im.message.receive_v1"]

    for mtype, content, expected in (
        ("image", {"image_key": "img_1"}, MessageType.IMAGE),
        ("file", {"file_key": "file_1", "file_name": "spec.pdf"}, MessageType.FILE),
        ("audio", {"file_key": "aud_1", "duration": 4200}, MessageType.AUDIO),
        ("media", {"file_key": "vid_1", "image_key": "thumb_1"}, MessageType.VIDEO),
    ):
        data = _text_event()
        data.event.message.message_type = mtype
        data.event.message.content = json.dumps(content)
        data.header.event_id = f"evt-{mtype}"
        handler(data)
    await _drain(collector, want=4)

    by_kind = {event.kind: event for event in collector.events}
    assert by_kind[MessageType.IMAGE].attachments[0].meta["image_key"] == "img_1"
    assert by_kind[MessageType.FILE].attachments[0].filename == "spec.pdf"
    assert by_kind[MessageType.AUDIO].attachments[0].meta["file_key"] == "aud_1"
    assert by_kind[MessageType.VIDEO].attachments[0].meta["image_key"] == "thumb_1"


async def test_inbound_reply_root_id_and_bot_echo_dropped(lark_stubs):
    adapter, collector = _adapter()
    await adapter.start()
    handler = lark_stubs["_WsClient"].instances[-1].event_handler.callbacks["im.message.receive_v1"]
    data = _text_event("a reply", root_id="om_root_9")
    handler(data)
    await _drain(collector)
    assert collector.events[0].reply_to_event_id == "om_root_9"

    echo = _text_event("from a bot")
    echo.event.sender.sender_type = "app"
    handler(echo)
    await asyncio.sleep(0)
    assert len(collector.events) == 1


# ---------------------------------------------------------------------------
# webhook mode
# ---------------------------------------------------------------------------

async def test_webhook_url_verification_and_ingress(monkeypatch):
    stubs = _make_lark_stubs()
    monkeypatch.setitem(sys.modules, "lark_oapi", stubs["lark"])
    adapter, collector = _adapter(mode="webhook", verification_token="vtok")
    await adapter.start()
    assert stubs["_WsClient"].instances == []  # no WS in webhook mode

    assert await adapter.handle_webhook({"type": "url_verification", "challenge": "xyz"}) \
        == {"challenge": "xyz"}

    payload = {
        "header": {"event_id": "evt-wh-1", "create_time": "1770000000000"},
        "event": {
            "sender": {"sender_type": "user", "sender_id": {"open_id": "ou_7"}},
            "message": {"message_type": "text", "content": json.dumps({"text": "via webhook"}),
                        "chat_id": "oc_wh", "message_id": "om_wh", "chat_type": "p2p"},
        },
    }
    assert await adapter.handle_webhook(payload) is None
    await _drain(collector)
    event = collector.events[0]
    assert event.text == "via webhook" and event.is_group is False and event.event_id == "evt-wh-1"
    await adapter.stop()


def _feishu_encrypt(encrypt_key: str, payload: dict) -> str:
    """Feishu event encryption: AES-256-CBC(SHA256(key)), b64(IV16 + PKCS7(32) body)."""
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    key = hashlib.sha256(encrypt_key.encode()).digest()
    raw = json.dumps(payload).encode()
    pad = 32 - (len(raw) % 32) or 32
    data = raw + bytes([pad]) * pad
    iv = os.urandom(16)
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend()).encryptor()
    return base64.b64encode(iv + encryptor.update(data) + encryptor.finalize()).decode()


async def test_webhook_encrypted_event(monkeypatch):
    stubs = _make_lark_stubs()
    monkeypatch.setitem(sys.modules, "lark_oapi", stubs["lark"])
    adapter, collector = _adapter(mode="webhook", encrypt_key="k-test")
    await adapter.start()

    encrypted = _feishu_encrypt("k-test", {
        "header": {"event_id": "evt-enc", "create_time": "1770000000000"},
        "event": {
            "sender": {"sender_type": "user", "sender_id": {"open_id": "ou_8"}},
            "message": {"message_type": "text", "content": json.dumps({"text": "secret payload"}),
                        "chat_id": "oc_enc", "message_id": "om_enc", "chat_type": "group"},
        }})
    assert await adapter.handle_webhook({"encrypt": encrypted}) is None
    await _drain(collector)
    assert collector.events[0].text == "secret payload"
    await adapter.stop()


# ---------------------------------------------------------------------------
# outbound
# ---------------------------------------------------------------------------

async def test_send_text_creates_message(lark_stubs):
    adapter, _ = _adapter()
    await adapter.start()
    result = await adapter.send("oc_chat1", "hello feishu")
    client = lark_stubs["_Client"].instances[-1]
    request = client.create_calls[-1]
    assert request["receive_id_type"] == "chat_id"
    body = request["request_body"]
    assert body["receive_id"] == "oc_chat1"
    assert body["msg_type"] == "text"
    assert json.loads(body["content"]) == {"text": "hello feishu"}
    assert result.ok is True and result.message_id == "om_out_1"


async def test_send_reply_and_interactive(lark_stubs):
    adapter, _ = _adapter()
    await adapter.start()
    await adapter.send("oc_chat1", "a reply", reply_to="om_in_1")
    client = lark_stubs["_Client"].instances[-1]
    assert client.reply_calls[-1]["message_id"] == "om_in_1"

    card = {"config": {"wide_screen_mode": True},
            "elements": [{"tag": "div", "text": {"content": "c"}}]}
    result = await adapter.send("oc_chat1", "interactive:" + json.dumps(card))
    body = client.create_calls[-1]["request_body"]
    assert body["msg_type"] == "interactive"
    assert json.loads(body["content"]) == card
    assert result.ok is True


async def test_send_api_failure(monkeypatch):
    stubs = _make_lark_stubs(fail_send=True)
    monkeypatch.setitem(sys.modules, "lark_oapi", stubs["lark"])
    adapter, _ = _adapter()
    await adapter.start()
    result = await adapter.send("oc_chat1", "hello")
    assert result.ok is False and "99991672" in result.error


async def test_send_not_connected():

    adapter, _ = _adapter()
    result = await adapter.send("oc_chat1", "x")
    assert result.ok is False and result.error == "not connected"
