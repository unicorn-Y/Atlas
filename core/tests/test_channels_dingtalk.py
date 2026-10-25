"""W2b DingTalk adapter tests — Stream Mode + circuit breaker with a stubbed dingtalk-stream SDK."""

from __future__ import annotations

import asyncio
import sys
import types
from typing import Any

import pytest

from atlas.channels.adapters._vendor import dingtalk_inbound
from atlas.channels.contract import ChannelAdapterError, MessageType

# ---------------------------------------------------------------------------
# stub dingtalk_stream module
# ---------------------------------------------------------------------------

def _make_dingtalk_stubs(start_behavior: str = "block") -> dict[str, Any]:
    class Credential:
        def __init__(self, client_id, client_secret):
            self.client_id, self.client_secret = client_id, client_secret

    class ChatbotMessage:
        TOPIC = "/v1.0/im/bot/messages/get"

        @classmethod
        def from_dict(cls, data):
            fields: dict[str, Any] = {
                "message_id": "", "conversation_id": "", "conversation_type": "1",
                "sender_id": "", "sender_nick": "", "sender_staff_id": "",
                "session_webhook": "", "session_webhook_expired_time": 0,
                "is_in_at_list": False, "text": None, "rich_text_content": None,
                "image_content": None, "message_type": "", "extensions": {},
                "create_at": None, "robot_code": "",
            }
            fields.update(data or {})
            return types.SimpleNamespace(**fields)

    class ChatbotHandler:
        pass

    class DingTalkStreamClient:
        instances: list[Any] = []

        def __init__(self, credential=None):
            self.credential = credential
            self.registered: list[tuple[str, Any]] = []
            self.start_calls = 0
            self._stop = asyncio.Event()
            DingTalkStreamClient.instances.append(self)

        def register_callback_handler(self, topic, handler):
            self.registered.append((topic, handler))

        async def start(self):
            self.start_calls += 1
            if start_behavior == "raise":
                raise RuntimeError("stream boom")
            await self._stop.wait()

    frames = types.ModuleType("dingtalk_stream.frames")

    class CallbackMessage:
        def __init__(self, data=None):
            self.data = data

    class AckMessage:
        STATUS_OK = 200
        STATUS_SYSTEM_EXCEPTION = 500

    frames.CallbackMessage = CallbackMessage
    frames.AckMessage = AckMessage
    mod = types.ModuleType("dingtalk_stream")
    mod.Credential = Credential
    mod.ChatbotMessage = ChatbotMessage
    mod.ChatbotHandler = ChatbotHandler
    mod.DingTalkStreamClient = DingTalkStreamClient
    mod.frames = frames

    return {
        "module": mod, "Credential": Credential, "ChatbotMessage": ChatbotMessage,
        "ChatbotHandler": ChatbotHandler, "DingTalkStreamClient": DingTalkStreamClient,
        "AckMessage": AckMessage, "CallbackMessage": CallbackMessage,
    }


@pytest.fixture
def dingtalk_stubs(monkeypatch):
    stubs = _make_dingtalk_stubs()
    monkeypatch.setitem(sys.modules, "dingtalk_stream", stubs["module"])
    monkeypatch.setitem(sys.modules, "dingtalk_stream.frames", stubs["module"].frames)
    return stubs


class _Collector:
    def __init__(self):
        self.events = []

    async def __call__(self, event):
        self.events.append(event)


class _FakeHttp:
    def __init__(self, response: dict | None = None, status_code: int = 200):
        self.posts: list[dict] = []
        self._response = response or {"errcode": 0}
        self._status = status_code

    async def post(self, url, json=None, timeout=None):
        self.posts.append({"url": url, "json": json})
        return types.SimpleNamespace(
            status_code=self._status, text="boom", json=lambda: self._response)


_LIVE_ADAPTERS: list[Any] = []


@pytest.fixture(autouse=True)
async def _cleanup_live_adapters():
    """Stop every adapter a test started so no stream task outlives its loop."""
    yield
    for adapter in list(_LIVE_ADAPTERS):
        try:
            await adapter.stop()
        except Exception:
            pass
    _LIVE_ADAPTERS.clear()


def _adapter(**overrides):
    from atlas.channels.adapters.dingtalk import DingTalkAdapter

    collector = _Collector()
    config: dict[str, Any] = {
        "client_id": "cid", "client_secret": "csec", "account": "main", **overrides,
    }
    adapter = DingTalkAdapter(config, collector)
    _LIVE_ADAPTERS.append(adapter)
    return adapter, collector


def _payload(**fields) -> dict[str, Any]:
    base: dict[str, Any] = {
        "message_id": "msg_1", "conversation_id": "cid0001cid0001", "conversation_type": "2",
        "sender_id": "sender1", "sender_nick": "Zhang", "sender_staff_id": "staff1",
        "session_webhook": "https://oapi.dingtalk.com/robot/send?session=abc",
        "session_webhook_expired_time": 9999999999999,
        "isInAtList": False, "text": {"content": "hi bot"}, "message_type": "text",
        "atUsers": ["agent_dingtalk_id"],
    }
    base.update(fields)
    return base


# ---------------------------------------------------------------------------
# availability / lifecycle
# ---------------------------------------------------------------------------

async def test_start_raises_without_sdk(monkeypatch):
    monkeypatch.setitem(sys.modules, "dingtalk_stream", None)
    from atlas.channels.adapters.dingtalk import DingTalkAdapter

    assert DingTalkAdapter.is_available() is False
    adapter, _ = _adapter()
    with pytest.raises(ChannelAdapterError, match="sdk not installed: dingtalk-stream"):
        await adapter.start()


async def test_start_raises_without_httpx(monkeypatch, dingtalk_stubs):
    monkeypatch.setitem(sys.modules, "httpx", None)

    adapter, _ = _adapter()
    with pytest.raises(ChannelAdapterError, match="sdk not installed: httpx"):
        await adapter.start()


async def test_start_requires_credentials(monkeypatch, dingtalk_stubs):
    from atlas.channels.adapters.dingtalk import DingTalkAdapter

    adapter = DingTalkAdapter(
        {"client_id": "", "client_secret": "", "webhook_url": ""}, _Collector())
    with pytest.raises(ChannelAdapterError, match="client_id and client_secret"):
        await adapter.start()


async def test_start_registers_stream_handler(dingtalk_stubs):
    adapter, _ = _adapter()
    await adapter.start()
    client = dingtalk_stubs["DingTalkStreamClient"].instances[-1]
    assert client.credential.client_id == "cid"
    topic, handler = client.registered[-1]
    assert topic == dingtalk_stubs["ChatbotMessage"].TOPIC
    assert isinstance(handler, dingtalk_stubs["ChatbotHandler"])  # SDK-compatible handler
    await asyncio.sleep(0.02)
    await adapter.stop()
    assert adapter._http_client is None
    await adapter.stop()  # idempotent


# ---------------------------------------------------------------------------
# inbound normalization
# ---------------------------------------------------------------------------

async def test_inbound_text_group_mention_and_session_webhook(dingtalk_stubs):
    adapter, collector = _adapter()
    await adapter.start()
    status, body = await adapter._process_callback_data(_payload(isInAtList=True))
    assert (status, body) == (200, "OK")

    event = collector.events[0]
    assert (event.channel, event.account, event.event_id) == ("dingtalk", "main", "msg_1")
    assert (event.chat_id, event.sender_id, event.sender_name) == (
        "cid0001cid0001", "sender1", "Zhang")
    assert event.text == "hi bot"
    assert event.is_group is True and event.is_mention is True
    assert event.mentions == ["agent_dingtalk_id"]
    assert event.kind is MessageType.TEXT
    # session webhook cached for later replies (hermes parity)
    assert adapter._session_webhooks[event.chat_id][0].startswith("https://oapi.dingtalk.com/")

    # duplicate message_id suppressed, still ACKed
    status2, _ = await adapter._process_callback_data(_payload(isInAtList=True))
    assert status2 == 200 and len(collector.events) == 1


async def test_inbound_dm_without_mention(dingtalk_stubs):
    adapter, collector = _adapter()
    await adapter.start()
    await adapter._process_callback_data(_payload(conversation_type="1", conversation_id=""))
    event = collector.events[0]
    assert event.is_group is False and event.is_mention is False
    assert event.chat_id == "sender1"  # falls back to sender id


async def test_inbound_image_and_rich_text_media(dingtalk_stubs):
    adapter, collector = _adapter()
    await adapter.start()
    await adapter._process_callback_data(_payload(
        message_id="msg_img", text=None, message_type="image",
        image_content=types.SimpleNamespace(download_code="dl_img_1")))
    await adapter._process_callback_data(_payload(
        message_id="msg_rich", text=None, message_type="richText",
        rich_text_content=types.SimpleNamespace(rich_text_list=[
            {"type": "text", "text": "see "},
            {"type": "picture", "downloadCode": "dl_pic_1"},
        ])))
    await asyncio.sleep(0)
    assert len(collector.events) == 2
    first = collector.events[0]
    assert first.text == ""
    assert first.kind is MessageType.IMAGE
    assert first.attachments[0].url == "dl_img_1"
    rich = collector.events[1]
    assert rich.text == "see"
    assert rich.attachments[0].url == "dl_pic_1" and rich.kind is MessageType.IMAGE


async def test_inbound_bad_payload_acks_system_exception(dingtalk_stubs):
    adapter, collector = _adapter()
    await adapter.start()
    status, body = await adapter._process_callback_data("{not json")
    assert (status, body) == (500, "error")
    assert collector.events == []


def test_vendored_inbound_text_shapes():
    msg = types.SimpleNamespace(text={"content": "plain"}, rich_text_content=None,
                                message_type="", extensions={})
    assert dingtalk_inbound.extract_text(msg) == "plain"
    msg = types.SimpleNamespace(
        text=None,
        rich_text_content=types.SimpleNamespace(rich_text_list=[
            {"type": "text", "text": "a"}, {"type": "text", "text": "b"}]),
        message_type="", extensions={})
    assert dingtalk_inbound.extract_text(msg) == "a b"
    file_msg = types.SimpleNamespace(
        text=None, rich_text_content=None, message_type="file",
        extensions={"content": {"fileName": "report.pdf", "downloadCode": "dl_9"}})
    kind, urls, mimes = dingtalk_inbound.extract_media(file_msg)
    assert kind is MessageType.FILE and urls == ["dl_9"] and mimes == ["application/pdf"]
    assert dingtalk_inbound.extract_text(file_msg) == "[文件] report.pdf"


# ---------------------------------------------------------------------------
# outbound
# ---------------------------------------------------------------------------

async def test_send_via_session_webhook(dingtalk_stubs):
    adapter, _ = _adapter()
    await adapter.start()
    fake = _FakeHttp()
    adapter._http_client = fake
    adapter._session_webhooks["cid0001cid0001"] = (
        "https://oapi.dingtalk.com/robot/send?session=abc", 0)
    result = await adapter.send("cid0001cid0001", "done!")
    post = fake.posts[-1]
    assert post["url"].startswith("https://oapi.dingtalk.com/")
    assert post["json"]["msgtype"] == "markdown"
    assert "done!" in post["json"]["markdown"]["text"]
    assert result.ok is True and result.message_id


async def test_send_session_webhook_expired_falls_back_to_robot(dingtalk_stubs):
    adapter, _ = _adapter(webhook_url="https://oapi.dingtalk.com/robot/send?access_token=tok",
                          webhook_secret="s3cret")
    await adapter.start()
    fake = _FakeHttp()
    adapter._http_client = fake
    # expired in 1970
    adapter._session_webhooks["gone"] = (
        "https://oapi.dingtalk.com/robot/send?session=x", 1)
    result = await adapter.send("gone", "proactive")
    post = fake.posts[-1]
    assert "timestamp=" in post["url"] and "sign=" in post["url"]  # HMAC-signed robot webhook
    assert result.ok is True


async def test_send_error_paths(dingtalk_stubs):
    adapter, _ = _adapter()
    await adapter.start()
    adapter._http_client = _FakeHttp(response={"errcode": 310000, "errmsg": "sign not match"})
    adapter._session_webhooks["c"] = ("https://oapi.dingtalk.com/robot/send?session=y", 0)
    result = await adapter.send("c", "x")
    assert result.ok is False and "sign not match" in result.error

    adapter._http_client = _FakeHttp(status_code=500)
    result = await adapter.send("c", "x")
    assert result.ok is False and "HTTP 500" in result.error

    adapter._http_client = _FakeHttp()
    result = await adapter.send("unknown-chat", "x")
    assert result.ok is False and "session_webhook" in result.error


# ---------------------------------------------------------------------------
# circuit breaker (ported hermes semantics)
# ---------------------------------------------------------------------------

def test_circuit_breaker_counts_identical_errors(dingtalk_stubs):
    adapter, _ = _adapter()
    delays = [adapter._record_stream_error(RuntimeError("boom")) for _ in range(5)]
    assert delays == [2.0, 5.0, 10.0, 30.0, 60.0]
    assert adapter._breaker_tripped is False
    # 6th identical error trips the breaker → fixed 300s silent interval
    assert adapter._record_stream_error(RuntimeError("boom")) == 300.0
    assert adapter._breaker_tripped is True
    # a different error type resets both the counter and the trip
    assert adapter._record_stream_error(ValueError("different")) == 2.0
    assert adapter._breaker_tripped is False
    assert adapter._consecutive_same_error == 1


async def test_stream_error_path_feeds_breaker(monkeypatch, dingtalk_stubs):
    stubs = _make_dingtalk_stubs(start_behavior="raise")
    monkeypatch.setitem(sys.modules, "dingtalk_stream", stubs["module"])
    monkeypatch.setitem(sys.modules, "dingtalk_stream.frames", stubs["module"].frames)
    adapter, _ = _adapter()
    await adapter.start()
    await asyncio.sleep(0.05)  # first failure recorded, task now backing off (2s)
    client = stubs["DingTalkStreamClient"].instances[-1]
    assert client.start_calls >= 1
    assert adapter._consecutive_same_error == 1
    assert adapter._breaker_tripped is False
    await adapter.stop()
