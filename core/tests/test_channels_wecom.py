"""W2b WeCom adapter tests — vendored AES crypto roundtrip + callback flows + send
queue (no external SDK).

Uses locally-constructed envelopes with random AES keys (cryptography is available in
the core venv); the HTTP layer is a fake client, so no network or WeCom SDK is needed.
"""

from __future__ import annotations

import asyncio
import base64
import os
import sys
import types
from typing import Any
from xml.etree import ElementTree as ET

import pytest

from atlas.channels.adapters._vendor.wecom_crypto import (
    DecryptError,
    SignatureError,
    WXBizMsgCrypt,
    _sha1_signature,
)
from atlas.channels.adapters._vendor.wecom_send_queue import ChatSendQueueMixin
from atlas.channels.contract import ChannelAdapterError, MessageType

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _random_aes_key() -> str:
    """A valid 43-char encoding_aes_key (base64 of 32 random bytes, no padding char)."""
    return base64.b64encode(os.urandom(32)).decode()[:43]


def _make_app() -> dict[str, str]:
    return {
        "name": "default", "corp_id": "corp123", "corp_secret": "corpsecret",
        "agent_id": "1000002", "token": "tok123", "encoding_aes_key": _random_aes_key(),
    }


def _plaintext_xml(user: str = "UserA", content: str = "hello atlas", msg_id: str = "1001") -> str:
    return (
        "<xml><ToUserName><![CDATA[corp123]]></ToUserName>"
        f"<FromUserName><![CDATA[{user}]]></FromUserName>"
        "<CreateTime>1770000000</CreateTime><MsgType><![CDATA[text]]></MsgType>"
        f"<Content><![CDATA[{content}]]></Content><MsgId>{msg_id}</MsgId></xml>"
    )


def _envelope(app: dict[str, str], plaintext: str,
              nonce: str = "n1", timestamp: str = "1770000000") -> tuple[str, str]:
    """(envelope xml, msg_signature) for a plaintext callback body."""
    crypt = WXBizMsgCrypt(app["token"], app["encoding_aes_key"], app["corp_id"])
    envelope = crypt.encrypt(plaintext, nonce=nonce, timestamp=timestamp)
    signature = ET.fromstring(envelope).findtext("MsgSignature") or ""
    return envelope, signature


class _Collector:
    def __init__(self):
        self.events = []

    async def __call__(self, event):
        self.events.append(event)


class _FakeWeComHttp:
    def __init__(self, send_responses: list[dict] | None = None):
        self.gets: list[dict] = []
        self.posts: list[tuple[str, dict]] = []
        self._send_responses = list(send_responses or [{"errcode": 0, "msgid": "MSG1"}])

    async def get(self, url, params=None):
        self.gets.append(dict(params or {}))
        return types.SimpleNamespace(json=lambda: {
            "errcode": 0, "access_token": "TOKEN", "expires_in": 7200})

    async def post(self, url, json=None):
        self.posts.append((url, json))
        index = min(len(self.posts) - 1, len(self._send_responses) - 1)
        return types.SimpleNamespace(json=lambda: self._send_responses[index])


_LIVE_ADAPTERS: list[Any] = []


@pytest.fixture(autouse=True)
async def _cleanup_live_adapters():
    """Stop every adapter a test started so no queue worker outlives its loop."""
    yield
    for adapter in list(_LIVE_ADAPTERS):
        try:
            await adapter.stop()
        except Exception:
            pass
    _LIVE_ADAPTERS.clear()


def _adapter(apps: list[dict[str, str]] | None = None, **overrides: Any):
    from atlas.channels.adapters.wecom import WeComAdapter

    collector = _Collector()
    config: dict[str, Any] = {"apps": apps if apps is not None else [_make_app()],
                              "account": "main", **overrides}
    adapter = WeComAdapter(config, collector)
    _LIVE_ADAPTERS.append(adapter)
    return adapter, collector


def _callback_query(signature: str, nonce: str = "n1", timestamp: str = "1770000000",
                    echostr: str = "") -> dict[str, str]:
    return {"msg_signature": signature, "timestamp": timestamp, "nonce": nonce, "echostr": echostr}


# ---------------------------------------------------------------------------
# availability / lifecycle
# ---------------------------------------------------------------------------

async def test_start_raises_without_crypto(monkeypatch):
    from atlas.channels.adapters.wecom import WeComAdapter

    monkeypatch.setitem(sys.modules, "cryptography", None)  # lazy import raises ImportError
    assert WeComAdapter.is_available() is False
    adapter, _ = _adapter()
    with pytest.raises(ChannelAdapterError, match="sdk not installed: cryptography"):
        await adapter.start()


async def test_start_raises_without_httpx(monkeypatch):

    monkeypatch.setitem(sys.modules, "httpx", None)
    adapter, _ = _adapter()
    with pytest.raises(ChannelAdapterError, match="sdk not installed: httpx"):
        await adapter.start()


async def test_start_requires_app_config():
    from atlas.channels.adapters.wecom import WeComAdapter

    adapter = WeComAdapter({}, _Collector())
    with pytest.raises(ChannelAdapterError, match="app configuration"):
        await adapter.start()


async def test_single_app_config_with_env_credentials(monkeypatch):
    monkeypatch.setenv("ATLAS_CHANNEL_WECOM_CORP_ID", "corp-env")
    monkeypatch.setenv("ATLAS_CHANNEL_WECOM_ENCODING_AES_KEY", _random_aes_key())
    monkeypatch.setenv("ATLAS_CHANNEL_WECOM_TOKEN", "tok-env")
    from atlas.channels.adapters.wecom import WeComAdapter

    adapter = WeComAdapter({"corp_secret": "s", "agent_id": "1"}, _Collector())
    assert len(adapter._apps) == 1
    assert adapter._apps[0]["corp_id"] == "corp-env"
    assert adapter._apps[0]["token"] == "tok-env"


# ---------------------------------------------------------------------------
# vendored WXBizMsgCrypt roundtrip (AES-CBC, hermes-compatible wire format)
# ---------------------------------------------------------------------------

def test_wxbizmsgcrypt_encrypt_decrypt_roundtrip():
    key = _random_aes_key()
    crypt = WXBizMsgCrypt("tok123", key, "corp123")
    plaintext = _plaintext_xml()
    envelope = crypt.encrypt(plaintext, nonce="abc", timestamp="1770000000")
    root = ET.fromstring(envelope)
    encrypt = root.findtext("Encrypt") or ""
    signature = root.findtext("MsgSignature") or ""
    assert root.findtext("Nonce") == "abc"

    assert crypt.decrypt(signature, "1770000000", "abc", encrypt).decode("utf-8") == plaintext
    assert crypt.verify_url(signature, "1770000000", "abc", encrypt) == plaintext

    with pytest.raises(SignatureError):
        crypt.decrypt("badsig", "1770000000", "abc", encrypt)
    other_corp = WXBizMsgCrypt("tok123", key, "corp999")
    with pytest.raises(DecryptError):
        other_corp.decrypt(signature, "1770000000", "abc", encrypt)
    with pytest.raises(ValueError):
        WXBizMsgCrypt("tok123", "too-short", "corp123")


# ---------------------------------------------------------------------------
# inbound: URL verification + callback decrypt/dispatch
# ---------------------------------------------------------------------------

async def test_handle_verify_echoes_decrypted_echostr():
    app = _make_app()
    adapter, _ = _adapter([app])
    crypt = WXBizMsgCrypt(app["token"], app["encoding_aes_key"], app["corp_id"])
    echostr = crypt._encrypt_bytes(b"verify-me-123")
    query = _callback_query(_sha1_signature(app["token"], "1770000000", "n1", echostr),
                            echostr=echostr)
    assert await adapter.handle_verify(query) == (200, "verify-me-123")
    assert await adapter.handle_verify(_callback_query("badsig")) == (
        403, "signature verification failed")


async def test_handle_callback_dispatches_decrypted_event():
    app = _make_app()
    adapter, collector = _adapter([app])
    body, signature = _envelope(app, _plaintext_xml(content="hello atlas", msg_id="1001"))
    status, ack = await adapter.handle_callback(_callback_query(signature), body)
    assert (status, ack) == (200, "success")

    event = collector.events[0]
    assert (event.channel, event.account, event.event_id) == ("wecom", "main", "1001")
    assert (event.chat_id, event.sender_id) == ("corp123:UserA", "UserA")
    assert event.text == "hello atlas"
    assert event.kind is MessageType.TEXT and event.is_group is False

    # WeCom retries on ack timeout → duplicate MsgId suppressed but still acked
    status2, ack2 = await adapter.handle_callback(_callback_query(signature), body)
    assert (status2, ack2) == (200, "success")
    assert len(collector.events) == 1


async def test_handle_callback_normalizes_group_at_text():
    app = _make_app()
    adapter, collector = _adapter([app])
    body, signature = _envelope(app, _plaintext_xml(user="wr_group_1", content="@代码助手 review", msg_id="1002"))
    assert await adapter.handle_callback(_callback_query(signature), body) == (200, "success")
    event = collector.events[0]
    assert event.is_group is True and event.is_mention is True
    assert event.mentions == ["代码助手"]


async def test_handle_callback_rejects_bad_signature():
    app = _make_app()
    adapter, _ = _adapter([app])
    body, _ = _envelope(app, _plaintext_xml())
    assert await adapter.handle_callback(_callback_query("badsig"), body) == (
        400, "invalid callback payload")
    assert await adapter.handle_callback(
        _callback_query("badsig"), "<xml><Encrypt>x</Encrypt></xml>") == (
        400, "invalid callback payload")


async def test_handle_callback_ignores_lifecycle_events():
    app = _make_app()
    adapter, collector = _adapter([app])
    lifecycle = _plaintext_xml(content="", msg_id="0").replace(
        "<MsgType><![CDATA[text]]></MsgType>",
        "<MsgType><![CDATA[event]]></MsgType><Event><![CDATA[enter_agent]]></Event>")
    body, signature = _envelope(app, lifecycle)
    status, ack = await adapter.handle_callback(_callback_query(signature), body)
    assert (status, ack) == (200, "success")
    assert collector.events == []


# ---------------------------------------------------------------------------
# outbound: message/send with token cache + retry, FIFO queue, chunking
# ---------------------------------------------------------------------------

async def test_send_uses_token_and_message_send_payload():
    adapter, _ = _adapter()
    await adapter.start()
    fake = _FakeWeComHttp()
    adapter._http_client = fake
    result = await adapter.send("corp123:UserA", "hello wecom")
    assert result.ok is True and result.message_id == "MSG1"
    url, payload = fake.posts[0]
    assert url.startswith("https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token=TOKEN")
    assert payload["touser"] == "UserA"
    assert payload["agentid"] == 1000002
    assert payload["msgtype"] == "text" and payload["text"] == {"content": "hello wecom"}
    assert fake.gets == [{"corpid": "corp123", "corpsecret": "corpsecret"}]
    # second send reuses the cached token (still a single gettoken call)
    await adapter.send("corp123:UserA", "again")
    assert len(fake.gets) == 1 and len(fake.posts) == 2


async def test_send_refreshes_token_on_rejection():
    adapter, _ = _adapter()
    await adapter.start()
    fake = _FakeWeComHttp(send_responses=[{"errcode": 40001, "errmsg": "invalid credential"},
                                          {"errcode": 0, "msgid": "MSG2"}])
    adapter._http_client = fake
    result = await adapter.send("corp123:UserA", "retry me")
    assert result.ok is True and result.message_id == "MSG2"
    assert len(fake.gets) == 2  # evicted token forced a refresh
    assert len(fake.posts) == 2


async def test_send_chunks_to_2048_byte_cap():
    adapter, _ = _adapter()
    await adapter.start()
    fake = _FakeWeComHttp()
    adapter._http_client = fake
    result = await adapter.send("corp123:UserA", "好" * 2000)  # 6000 utf-8 bytes
    assert result.ok is True
    assert len(fake.posts) == 3
    joined = "".join(payload["text"]["content"] for _, payload in fake.posts)
    assert joined == "好" * 2000  # no character lost or split
    for _, payload in fake.posts:
        assert len(payload["text"]["content"].encode("utf-8")) <= 2048


async def test_send_propagates_api_error():
    adapter, _ = _adapter()
    await adapter.start()
    fake = _FakeWeComHttp(send_responses=[{"errcode": 81013, "errmsg": "user not found"}])
    adapter._http_client = fake
    result = await adapter.send("corp123:UserA", "x")
    assert result.ok is False and "user not found" in result.error


async def test_send_without_start_is_not_connected():
    adapter, _ = _adapter()
    result = await adapter.send("corp123:UserA", "x")
    assert result.ok is False and result.error == "not connected"


# ---------------------------------------------------------------------------
# vendored send queue: token bucket + per-chat FIFO
# ---------------------------------------------------------------------------

class _BucketHolder(ChatSendQueueMixin):
    name = "wecom"

    def __init__(self):
        self._chat_queues: dict[str, asyncio.Queue] = {}
        self._chat_workers: dict[str, asyncio.Task] = {}
        self._control_queues: dict[str, asyncio.Queue] = {}
        self._control_workers: dict[str, asyncio.Task] = {}
        self._chat_token_usage: dict[str, dict[str, float]] = {}


def test_token_bucket_normal_and_reserved_lanes():
    holder = _BucketHolder()
    for _ in range(holder._BUCKET_NORMAL_TOKENS):
        assert holder._bucket_try_consume("c1") == 0.0
    # normal lane exhausted → wait quoted until the next minute window
    assert holder._bucket_try_consume("c1") > 0.0
    # control messages drain the reserved pool next (6 tokens)
    for _ in range(holder._BUCKET_RESERVED_TOKENS):
        assert holder._bucket_try_consume("c1", is_control=True) == 0.0
    assert holder._bucket_try_consume("c1", is_control=True) > 0.0
    # per-chat isolation
    assert holder._bucket_try_consume("c2") == 0.0


async def test_fifo_queue_preserves_order_under_load():
    holder = _BucketHolder()
    order: list[int] = []

    def factory(i: int):
        async def _coro_factory():
            order.append(i)
            return f"r{i}"
        return _coro_factory

    results = await asyncio.gather(
        *[holder._enqueue_chat_send("chat", factory(i)) for i in range(20)])
    assert results == [f"r{i}" for i in range(20)]
    assert order == list(range(20))
    for workers in (holder._chat_workers, holder._control_workers):
        for task in workers.values():
            task.cancel()
