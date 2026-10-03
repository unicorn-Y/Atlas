"""Adapter tests: Telegram (httpx MockTransport), Webhook (HMAC), Email (fake IMAP/SMTP)."""

from __future__ import annotations

import asyncio
import email.utils
import imaplib
import json
import time
from email.message import EmailMessage

import httpx
import pytest

from atlas.channels import AdapterAuthError
from atlas.channels.adapters.email import EmailAdapter, parse_mail
from atlas.channels.adapters.telegram import TelegramAdapter, file_download_url
from atlas.channels.adapters.webhook import (
    SIGNATURE_HEADER,
    WebhookAdapter,
    parse_inbound,
    sign_payload,
    verify_hmac,
)
from atlas.channels.contract import Attachment, MessageEvent, MessageType, SendResult
from atlas.channels.credentials import ChannelCredentialStore


class MemoryCredentials(ChannelCredentialStore):
    def __init__(self, values=None):
        super().__init__(base=_DictStore(values or {}))


class _DictStore:
    def __init__(self, values):
        self.values = dict(values)

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)


def make_telegram_transport(requests: list, updates: list):
    async def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        url = str(request.url)
        if "/getUpdates" in url:
            # Bot API returns a list of updates; one queued update per poll.
            batch = [updates.pop(0)] if updates else []
            return httpx.Response(200, json={"ok": True, "result": batch})
        if "/getMe" in url:
            me = {"id": 42, "username": "atlas_bot"}
            return httpx.Response(200, json={"ok": True, "result": me})
        if "/sendMessage" in url:
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 777}})
        if "/editMessageText" in url:
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
        if "/getFile" in url:
            found = {"file_path": "documents/report.pdf"}
            return httpx.Response(200, json={"ok": True, "result": found})
        return httpx.Response(200, json={"ok": True, "result": {}})

    return httpx.MockTransport(respond)


def telegram_adapter(tmp_path, requests, updates, events, credentials=None):
    def client_factory(**kwargs):
        return httpx.AsyncClient(transport=make_telegram_transport(requests, updates), **kwargs)

    async def dispatcher(event: MessageEvent) -> None:
        events.append(event)

    return TelegramAdapter(
        {
            "bot_token": "secret-token",
            "state_path": tmp_path / "telegram_state.db",
            "client_factory": client_factory,
            "poll_timeout": 0,
            "credentials": credentials or MemoryCredentials(),
        },
        dispatcher,
    )


async def wait_for(condition, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        await asyncio.sleep(0.01)
    return condition()


# --- Telegram -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_telegram_long_poll_full_flow_and_offset_persistence(tmp_path):
    requests: list = []
    updates: list = [{
        "update_id": 1,
        "message": {
            "message_id": 11,
            "date": 1700000000,
            "from": {"id": 42, "first_name": "Ada", "last_name": "L"},
            "chat": {"id": 100, "type": "private"},
            "text": "你好 Atlas",
        },
    }]
    events: list = []
    adapter = telegram_adapter(tmp_path, requests, updates, events)
    await adapter.start()
    assert await wait_for(lambda: len(events) == 1)
    await adapter.stop()

    event = events[0]
    assert event.channel == "telegram"
    assert event.event_id == "11"
    assert event.chat_id == "100"
    assert event.sender_id == "42"
    assert event.sender_name == "Ada L"
    assert event.text == "你好 Atlas"
    assert event.kind is MessageType.TEXT
    assert not event.is_group
    assert adapter.bot_username == "atlas_bot"

    # offset persisted to sqlite before stop
    import sqlite3

    with sqlite3.connect(tmp_path / "telegram_state.db") as db:
        row = db.execute(
            "SELECT value FROM adapter_state WHERE key='telegram//offset'"
        ).fetchone()
    assert row == ("2",)


@pytest.mark.asyncio
async def test_telegram_restart_replays_nothing_uses_persisted_offset(tmp_path):
    requests: list = []
    updates: list = []
    events: list = []
    adapter = telegram_adapter(tmp_path, requests, updates, events)
    # simulate persisted offset from a previous run
    adapter._offset = 7
    adapter._persist_offset()
    await adapter.start()
    await asyncio.sleep(0.15)
    await adapter.stop()
    poll_calls = [r for r in requests if "/getUpdates" in str(r.url)]
    assert poll_calls, "expected at least one getUpdates call"
    body = json.loads(poll_calls[0].content.decode("utf-8"))
    assert body["offset"] == 7
    assert events == []


@pytest.mark.asyncio
async def test_telegram_missing_token_raises_auth_error(tmp_path):
    adapter = telegram_adapter(tmp_path, [], [], [], credentials=MemoryCredentials())
    adapter.config["bot_token"] = ""
    with pytest.raises(AdapterAuthError):
        await adapter.start()


@pytest.mark.asyncio
async def test_telegram_auth_failure_from_api_pauses(tmp_path):
    requests: list = []

    async def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            401, json={"ok": False, "error_code": 401, "description": "Unauthorized"}
        )

    def client_factory(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    async def dispatcher(event):
        return None

    adapter = TelegramAdapter(
        {"bot_token": "bad", "client_factory": client_factory, "state_path": tmp_path / "s.db",
         "credentials": MemoryCredentials()},
        dispatcher,
    )
    with pytest.raises(AdapterAuthError):
        await adapter.start()


@pytest.mark.asyncio
async def test_telegram_send_edit_and_media_url_normalization(tmp_path):
    requests: list = []
    updates: list = []
    events: list = []
    adapter = telegram_adapter(tmp_path, requests, updates, events)
    await adapter.start()

    result = await adapter.send("100", "hi" * 5000, reply_to="55")
    assert isinstance(result, SendResult) and result.ok and result.message_id == "777"
    send_call = next(r for r in requests if "/sendMessage" in str(r.url))
    payload = json.loads(send_call.content.decode("utf-8"))
    assert payload["chat_id"] == "100"
    assert len(payload["text"]) == 4096
    assert payload["reply_to_message_id"] == 55

    edit = await adapter.edit_message("100", "777", "edited")
    assert edit.ok
    edit_call = next(r for r in requests if "/editMessageText" in str(r.url))
    edit_payload = json.loads(edit_call.content.decode("utf-8"))
    assert edit_payload["message_id"] == 777 and edit_payload["text"] == "edited"

    # metadata-driven edit routing through send()
    via_meta = await adapter.send("100", "v2", metadata={"edit_message_id": "777"})
    assert via_meta.ok
    await adapter.stop()


def test_file_download_url_normalization():
    assert (
        file_download_url("https://api.telegram.org/", "tok", "/documents/report.pdf")
        == "https://api.telegram.org/file/bottok/documents/report.pdf"
    )
    assert file_download_url("", "tok", "photos/a.jpg") == "https://api.telegram.org/file/bottok/photos/a.jpg"


@pytest.mark.asyncio
async def test_telegram_media_message_builds_attachment(tmp_path):
    requests: list = []
    updates: list = [{
        "update_id": 5,
        "message": {
            "message_id": 22,
            "date": 1700000000,
            "from": {"id": 42, "first_name": "Ada"},
            "chat": {"id": -500, "type": "supergroup", "title": "Ops"},
            "document": {"file_id": "doc-1", "file_name": "report.pdf",
                         "mime_type": "application/pdf", "file_size": 1234},
        },
    }]
    events: list = []
    adapter = telegram_adapter(tmp_path, requests, updates, events)
    await adapter.start()
    assert await wait_for(lambda: len(events) == 1)
    await adapter.stop()

    event = events[0]
    assert event.is_group is True
    assert event.kind is MessageType.FILE
    assert event.attachments[0].filename == "report.pdf"
    assert event.attachments[0].url.endswith("/file/botsecret-token/documents/report.pdf")
    assert event.attachments[0].size == 1234


# --- Webhook -------------------------------------------------------------------


def test_verify_hmac_accepts_good_signature():
    secret = "s3cret"
    body = b'{"event_id": "1"}'
    headers = {SIGNATURE_HEADER: sign_payload(secret, int(time.time()), body)}
    assert verify_hmac(secret, headers, body) is True


def test_verify_hmac_rejects_bad_signature():
    body = b'{"event_id": "1"}'
    headers = {SIGNATURE_HEADER: sign_payload("other-secret", int(time.time()), body)}
    assert verify_hmac("s3cret", headers, body) is False


def test_verify_hmac_rejects_expired_timestamp():
    body = b"payload"
    stale = int(time.time()) - 60 * 10  # 10 minutes ago, outside ±5 min window
    headers = {SIGNATURE_HEADER: sign_payload("s3cret", stale, body)}
    assert verify_hmac("s3cret", headers, body) is False
    assert verify_hmac("s3cret", headers, body, now=float(stale)) is True


def test_verify_hmac_rejects_missing_or_malformed_headers():
    assert verify_hmac("s3cret", {}, b"x") is False
    assert verify_hmac("s3cret", {SIGNATURE_HEADER: "not-a-signature"}, b"x") is False
    assert verify_hmac("s3cret", {SIGNATURE_HEADER: "t=abc,v1=zz"}, b"x") is False
    assert verify_hmac("", {SIGNATURE_HEADER: sign_payload("", 1, b"x")}, b"x") is False


def test_parse_inbound_normalizes_and_validates():
    event = parse_inbound(
        {
            "event_id": "wh-1",
            "chat_id": "cart-9",
            "sender_id": "user-1",
            "kind": "file",
            "text": "见附件",
            "attachments": [{"url": "https://x/y.bin", "filename": "y.bin",
                             "mime_type": "app/bin"}],
        },
        channel="webhook",
        account="team",
    )
    assert event.channel == "webhook" and event.account == "team"
    assert event.event_id == "wh-1" and event.chat_id == "cart-9"
    assert event.kind is MessageType.FILE
    assert event.attachments[0].filename == "y.bin"
    with pytest.raises(ValueError):
        parse_inbound({"chat_id": "x"})
    with pytest.raises(ValueError):
        parse_inbound({"event_id": "x"})
    unknown = parse_inbound({"event_id": "e", "chat_id": "c", "kind": "hologram"})
    assert unknown.kind is MessageType.UNKNOWN


@pytest.mark.asyncio
async def test_webhook_adapter_send_posts_signed_envelope():
    received: list = []

    async def respond(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(200, headers={"x-atlas-message-id": "wh-9"})

    def client_factory(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    async def dispatcher(event):
        return None

    adapter = WebhookAdapter(
        {"url": "https://example.test/hook", "secret": "s3cret", "client_factory": client_factory},
        dispatcher,
    )
    await adapter.start()
    result = await adapter.send(
        "cart-9", "hello", attachments=[Attachment(kind=MessageType.FILE, url="u")]
    )
    await adapter.stop()
    assert result.ok and result.message_id == "wh-9"
    request = received[0]
    body = request.content
    envelope = json.loads(body.decode("utf-8"))
    assert envelope["chat_id"] == "cart-9" and envelope["text"] == "hello"
    assert verify_hmac("s3cret", dict(request.headers), body) is True


@pytest.mark.asyncio
async def test_webhook_adapter_without_url_reports_not_retryable():
    async def dispatcher(event):
        return None

    adapter = WebhookAdapter({}, dispatcher)
    result = await adapter.send("c", "hi")
    assert result.ok is False and result.retryable is False


# --- Email -----------------------------------------------------------------------


class FakeIMAP:
    server: dict = {}

    def __init__(self):
        self.uid_calls: list = []

    def login(self, user, password):
        if password != "app-password":
            raise imaplib.IMAP4.error("LOGIN failed")

    def select(self, folder):
        self.folder = folder

    def uid(self, command, *args):
        self.uid_calls.append((command, args))
        if command == "search":
            last_seen = self.last_seen
            uids = sorted(int(u) for u in self.server)
            visible = [u for u in uids if u > last_seen]
            if not visible and uids:
                visible = [uids[-1]]  # RFC: "UID n:*" re-reports the newest mail
            return "OK", [b" ".join(str(u).encode() for u in visible)]
        if command == "fetch":
            uid = int(args[0])
            raw = self.server.get(str(uid))
            if raw is None:
                return "OK", [None]
            return "OK", [(f"1 (UID {uid} {{10}}".encode(), raw), b")"]
        raise AssertionError(command)

    last_seen = 0

    def logout(self):
        pass


def build_raw_mail(*, body: str | None = "每周报告正文", attach: bool = False) -> bytes:
    message = EmailMessage()
    message["From"] = "Boss <boss@example.com>"
    message["To"] = "atlas@example.com"
    message["Subject"] = "每周报告"
    message["Date"] = email.utils.formatdate(1700000000, localtime=False)
    if body is not None:
        message.set_content(body)
    if attach:
        message.add_attachment(
            b"BIN", maintype="application", subtype="octet-stream", filename="data.bin"
        )
    return message.as_bytes()


@pytest.mark.asyncio
async def test_email_poll_text_and_file_kinds(tmp_path):
    FakeIMAP.server = {
        "5": build_raw_mail(body="正文内容"),
        "6": build_raw_mail(body=None, attach=True),
    }
    created: list = []

    def imap_factory():
        client = FakeIMAP()
        created.append(client)
        return client

    events: list = []

    async def dispatcher(event):
        events.append(event)

    adapter = EmailAdapter(
        {
            "host": "imap.example.com", "user": "atlas@example.com", "password": "app-password",
            "poll_interval": 0.01, "state_path": tmp_path / "email_state.db",
            "imap_factory": imap_factory,
        },
        dispatcher,
    )
    await adapter.start()
    assert await wait_for(lambda: len(events) == 2)
    await adapter.stop()

    text_event, file_event = events
    assert text_event.kind is MessageType.TEXT
    assert "每周报告" in text_event.text and "正文内容" in text_event.text
    assert text_event.chat_id == "boss@example.com"
    assert text_event.sender_name == "Boss"
    assert text_event.attachments == []
    assert file_event.kind is MessageType.FILE
    assert file_event.attachments[0].filename == "data.bin"
    # both mails were fetched exactly once (single fetch call per uid)
    fetch_calls = [call for call in created[1].uid_calls if call[0] == "fetch"]
    assert sorted(int(call[1][0]) for call in fetch_calls) == [5, 6]


@pytest.mark.asyncio
async def test_email_uid_persistence_prevents_redispatch(tmp_path):
    FakeIMAP.server = {"3": build_raw_mail(body="第一封")}
    events: list = []

    async def dispatcher(event):
        events.append(event)

    common = {
        "host": "imap.example.com", "user": "atlas@example.com", "password": "app-password",
        "poll_interval": 0.01, "state_path": tmp_path / "email_state.db",
        "imap_factory": FakeIMAP,
    }
    first = EmailAdapter(dict(common), dispatcher)
    await first.start()
    assert await wait_for(lambda: len(events) == 1)
    await first.stop()
    assert first._last_uid == 3

    second = EmailAdapter(dict(common), dispatcher)
    assert second._load_uid() == 3
    await second.start()
    await asyncio.sleep(0.05)
    await second.stop()
    assert len(events) == 1  # no redispatch after restart


@pytest.mark.asyncio
async def test_email_bad_password_raises_auth_error(tmp_path):
    async def dispatcher(event):
        return None

    adapter = EmailAdapter(
        {
            "host": "imap.example.com", "user": "atlas@example.com", "password": "wrong",
            "state_path": tmp_path / "s.db", "imap_factory": FakeIMAP,
        },
        dispatcher,
    )
    with pytest.raises(AdapterAuthError):
        await adapter.start()


@pytest.mark.asyncio
async def test_email_send_uses_smtp_and_returns_message_id(tmp_path):
    sent: list = []

    class FakeSMTP:
        def login(self, user, password):
            assert password == "app-password"

        def send_message(self, message):
            sent.append(message)

        def quit(self):
            pass

    async def dispatcher(event):
        return None

    adapter = EmailAdapter(
        {
            "host": "imap.example.com", "user": "atlas@example.com", "password": "app-password",
            "state_path": tmp_path / "s.db", "imap_factory": FakeIMAP,
            "smtp_factory": FakeSMTP,
        },
        dispatcher,
    )
    result = await adapter.send("dest@example.com", "回复内容", metadata={"subject": "Atlas 回复"})
    assert result.ok
    assert len(sent) == 1
    assert sent[0]["To"] == "dest@example.com"
    assert sent[0]["Subject"] == "Atlas 回复"
    body = sent[0].get_content()
    assert "回复内容" in body


def test_parse_mail_filters_and_headers():
    raw = build_raw_mail(body="hello")
    event = parse_mail(raw, uid="9", account="team")
    assert event.event_id == "9"
    assert event.raw["subject"] == "每周报告"
    assert event.ts > 0
