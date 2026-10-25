"""W2b Slack adapter tests — full flows driven with stubbed slack_sdk modules (no real SDK)."""

from __future__ import annotations

import asyncio
import json
import sys
import types
from typing import Any

import pytest

from atlas.channels.adapters._vendor import slack_block_kit
from atlas.channels.contract import Attachment, ChannelAdapterError, MessageType

# ---------------------------------------------------------------------------
# stub slack_sdk module chain
# ---------------------------------------------------------------------------

def _make_slack_stubs() -> dict[str, Any]:
    class SocketModeResponse:
        def __init__(self, envelope_id: str = "", payload: Any = None) -> None:
            self.envelope_id, self.payload = envelope_id, payload

    class SocketModeClient:
        instances: list[Any] = []

        def __init__(self, app_token=None, web_client=None, trace_enabled=False, **kw):
            self.app_token, self.web_client = app_token, web_client
            self.socket_mode_request_listeners: list[Any] = []
            self.connected = False
            self.acks: list[Any] = []
            SocketModeClient.instances.append(self)

        async def connect(self):
            self.connected = True

        async def close(self):
            self.connected = False

        async def send_socket_mode_response(self, response):
            self.acks.append(response)

    class AsyncWebClient:
        instances: list[Any] = []

        def __init__(self, token=None, **kw):
            self.token = token
            self.calls: list[dict] = []
            AsyncWebClient.instances.append(self)

        async def chat_postMessage(self, **kwargs):  # noqa: N802 (Slack API name)
            self.calls.append(kwargs)
            if kwargs.get("text") == "fail":
                return types.SimpleNamespace(data={"ok": False, "error": "invalid_blocks"})
            return types.SimpleNamespace(
                data={"ok": True, "ts": "1770000000.000100", "channel": kwargs.get("channel")})

        async def conversations_info(self, **kwargs):
            self.calls.append(kwargs)
            return types.SimpleNamespace(
                data={"channel": {"name_normalized": "general", "name": "general", "is_im": False}})

    def _module(name: str, **attrs):
        mod = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(mod, key, value)
        return mod

    modules = {
        "slack_sdk": _module("slack_sdk"),
        "slack_sdk.socket_mode": _module("slack_sdk.socket_mode"),
        "slack_sdk.socket_mode.aiohttp": _module(
            "slack_sdk.socket_mode.aiohttp", SocketModeClient=SocketModeClient),
        "slack_sdk.socket_mode.response": _module(
            "slack_sdk.socket_mode.response", SocketModeResponse=SocketModeResponse),
        "slack_sdk.web": _module("slack_sdk.web"),
        "slack_sdk.web.async_client": _module(
            "slack_sdk.web.async_client", AsyncWebClient=AsyncWebClient),
    }
    return {"modules": modules,
            "SocketModeClient": SocketModeClient, "AsyncWebClient": AsyncWebClient}


@pytest.fixture
def slack_stubs(monkeypatch):
    stubs = _make_slack_stubs()
    for name, module in stubs["modules"].items():
        monkeypatch.setitem(sys.modules, name, module)
    return stubs


class _Collector:
    def __init__(self):
        self.events = []

    async def __call__(self, event):
        self.events.append(event)


_LIVE_ADAPTERS: list[Any] = []


@pytest.fixture(autouse=True)
async def _cleanup_live_adapters():
    """Stop every adapter a test started so no socket/task outlives its loop."""
    yield
    for adapter in list(_LIVE_ADAPTERS):
        try:
            await adapter.stop()
        except Exception:
            pass
    _LIVE_ADAPTERS.clear()


def _adapter(**overrides):
    from atlas.channels.adapters.slack import SlackAdapter

    collector = _Collector()
    config: dict[str, Any] = {
        "bot_token": "xoxb-test", "app_token": "xocha-test",
        "bot_user_id": "UBOT", "account": "main", **overrides,
    }
    adapter = SlackAdapter(config, collector)
    _LIVE_ADAPTERS.append(adapter)
    return adapter, collector


async def _drain(collector: _Collector, want: int = 1) -> None:
    for _ in range(200):
        if len(collector.events) >= want:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"expected {want} dispatch(es), got {len(collector.events)}")


# ---------------------------------------------------------------------------
# availability / lifecycle
# ---------------------------------------------------------------------------

async def test_start_raises_without_sdk(monkeypatch):
    monkeypatch.setitem(sys.modules, "slack_sdk", None)  # import raises ImportError
    from atlas.channels.adapters.slack import SlackAdapter

    assert SlackAdapter.is_available() is False
    adapter, _ = _adapter()
    with pytest.raises(ChannelAdapterError, match="sdk not installed: slack-sdk"):
        await adapter.start()


async def test_start_requires_tokens(monkeypatch):
    monkeypatch.setitem(sys.modules, "slack_sdk", _make_slack_stubs()["modules"]["slack_sdk"])
    from atlas.channels.adapters.slack import SlackAdapter

    adapter = SlackAdapter({"bot_token": "", "app_token": ""}, _Collector())
    with pytest.raises(ChannelAdapterError, match="bot_token and app_token"):
        await adapter.start()


async def test_start_connects_socket_mode(slack_stubs):
    adapter, _ = _adapter()
    await adapter.start()
    client = slack_stubs["SocketModeClient"].instances[-1]
    assert client.connected
    assert client.app_token == "xocha-test"
    assert client.web_client.token == "xoxb-test"
    assert len(client.socket_mode_request_listeners) == 1
    await adapter.stop()
    assert client.connected is False
    await adapter.stop()  # idempotent


# ---------------------------------------------------------------------------
# inbound normalization
# ---------------------------------------------------------------------------

async def test_inbound_message_text_thread_and_files(slack_stubs):
    adapter, collector = _adapter()
    await adapter.start()
    client = slack_stubs["SocketModeClient"].instances[-1]
    listener = client.socket_mode_request_listeners[0]

    req = types.SimpleNamespace(
        type="events_api", envelope_id="env-1",
        payload={"event": {
            "type": "message", "channel": "C123", "user": "U1",
            "text": "run the report", "ts": "1770000000.000200",
            "client_msg_id": "cmid-1", "thread_ts": "1770000000.000100",
            "user_profile": {"display_name": "alice"},
            "files": [{
                "id": "F1", "name": "chart.png", "mimetype": "image/png", "size": 1234,
                "url_private": "https://files.slack.com/files-pri/F1/chart.png",
            }],
        }})
    await listener(client, req)
    await _drain(collector)

    # acked the envelope
    assert len(client.acks) == 1 and client.acks[0].envelope_id == "env-1"

    event = collector.events[0]
    assert (event.channel, event.account, event.event_id) == ("slack", "main", "cmid-1")
    assert (event.chat_id, event.sender_id, event.sender_name) == ("C123", "U1", "alice")
    assert event.text == "run the report"
    assert event.thread_id == "1770000000.000100"
    assert event.reply_to_event_id == "1770000000.000100"
    assert event.is_group is True and event.is_mention is False
    assert len(event.attachments) == 1
    att = event.attachments[0]
    assert att.kind is MessageType.IMAGE and att.filename == "chart.png" and att.size == 1234


async def test_inbound_app_mention_strips_bot_tag(slack_stubs):
    adapter, collector = _adapter()
    await adapter.start()
    client = slack_stubs["SocketModeClient"].instances[-1]
    await client.socket_mode_request_listeners[0](client, types.SimpleNamespace(
        type="events_api", envelope_id="env-2",
        payload={"event": {
            "type": "app_mention", "channel": "C9", "user": "U2",
            "text": "<@UBOT> deploy now", "ts": "1770000000.000300",
            "client_msg_id": "cmid-2",
        }}))
    await _drain(collector)
    event = collector.events[0]
    assert event.is_mention is True and event.text == "deploy now"
    assert event.is_group is True
    assert event.mentions == ["UBOT"]


async def test_inbound_bot_and_non_message_events_dropped_but_acked(slack_stubs):
    adapter, collector = _adapter()
    await adapter.start()
    client = slack_stubs["SocketModeClient"].instances[-1]
    listener = client.socket_mode_request_listeners[0]
    for payload in (
        {"event": {"type": "message", "channel": "C1", "bot_id": "B1", "text": "bot", "ts": "1"}},
        {"event": {"type": "reaction_added", "user": "U1"}},
        {"event": {"type": "message", "subtype": "message_changed", "channel": "C1",
                   "user": "U1", "text": "edited", "ts": "2"}},
        {"event": {"type": "message", "channel": "C1", "user": "UBOT", "text": "self", "ts": "3"}},
    ):
        await listener(client, types.SimpleNamespace(
            type="events_api", envelope_id="ack", payload=payload))
    assert len(client.acks) == 4
    assert collector.events == []


# ---------------------------------------------------------------------------
# outbound
# ---------------------------------------------------------------------------

async def test_send_plain_text_with_thread(slack_stubs):
    adapter, _ = _adapter()
    await adapter.start()
    result = await adapter.send("C123", "hi there", reply_to="1770.1")
    web = slack_stubs["AsyncWebClient"].instances[-1]
    assert web.calls[-1] == {"channel": "C123", "text": "hi there", "thread_ts": "1770.1"}
    assert result.ok is True and result.message_id == "1770000000.000100"


async def test_send_blocks_prefix_uses_block_kit(slack_stubs):
    adapter, _ = _adapter()
    await adapter.start()
    payload = {
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": "Report"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": "x" * 5000}},
        ],
        "text": "fallback text",
    }
    result = await adapter.send("C123", "blocks:" + json.dumps(payload))
    call = slack_stubs["AsyncWebClient"].instances[-1].calls[-1]
    assert result.ok is True
    assert "blocks" in call
    assert call["blocks"][0]["type"] == "header"
    # vendored sanitize_blocks clamped the oversized section text
    assert len(call["blocks"][1]["text"]["text"]) <= slack_block_kit.MAX_SECTION_TEXT
    assert call["text"] == "fallback text"


async def test_send_blocks_invalid_json_falls_back_to_text(slack_stubs):
    adapter, _ = _adapter()
    await adapter.start()
    result = await adapter.send("C123", "blocks:{not json")
    call = slack_stubs["AsyncWebClient"].instances[-1].calls[-1]
    assert result.ok is True
    assert "blocks" not in call
    assert call["text"] == "blocks:{not json"


async def test_send_image_attachment_becomes_image_block(slack_stubs):
    adapter, _ = _adapter()
    await adapter.start()
    att = Attachment(kind=MessageType.IMAGE, url="https://example.com/pic.png", filename="pic.png")
    await adapter.send("C123", "here you go", attachments=[att])
    call = slack_stubs["AsyncWebClient"].instances[-1].calls[-1]
    assert {"type": "image", "image_url": "https://example.com/pic.png",
            "alt_text": "pic.png"} in call["blocks"]


async def test_send_api_error_result(slack_stubs):
    adapter, _ = _adapter()
    await adapter.start()
    result = await adapter.send("C123", "fail")
    assert result.ok is False and result.error == "invalid_blocks"


async def test_send_without_start_is_not_connected():
    adapter, _ = _adapter()
    result = await adapter.send("C123", "x")
    assert result.ok is False and result.error == "not connected"


async def test_get_chat_info(slack_stubs):
    adapter, _ = _adapter()
    await adapter.start()
    info = await adapter.get_chat_info("C123")
    assert info == {"name": "general", "type": "channel"}


# ---------------------------------------------------------------------------
# vendored block_kit (pure stdlib port)
# ---------------------------------------------------------------------------

def test_block_kit_render_and_sanitize():
    blocks = slack_block_kit.render_blocks("# Title\n\n- a\n- b\n\n```code```")
    assert blocks is not None
    assert blocks[0]["type"] == "header"
    assert any(block["type"] == "rich_text" for block in blocks)

    oversized = [{"type": "section", "text": {"type": "mrkdwn", "text": "y" * 4000}},
                 {"type": "divider"},
                 {"type": "header", "text": {"type": "plain_text", "text": ""}}]
    clean = slack_block_kit.sanitize_blocks(oversized)
    assert clean is not None and len(clean) == 2  # empty header dropped
    assert len(clean[0]["text"]["text"]) <= slack_block_kit.MAX_SECTION_TEXT
    assert slack_block_kit.sanitize_blocks([]) is None
