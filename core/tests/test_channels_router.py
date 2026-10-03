"""REST surface tests for /api/channels (lane-owned router on a bare FastAPI app)."""

from __future__ import annotations

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atlas.api.channel_router import router, set_channel_manager
from atlas.channels import ChannelManager
from atlas.channels.adapters.webhook import sign_payload
from atlas.channels.credentials import ChannelCredentialStore


class _DictStore:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)


@pytest.fixture()
def client(tmp_path):
    from atlas.channels.adapters.telegram import TelegramAdapter

    credentials = ChannelCredentialStore(base=_DictStore())
    manager = ChannelManager(
        db_path=tmp_path / "channels.db",
        config_path=tmp_path / "channels.json",
        credentials=credentials,
    )
    manager.register_channel("telegram", TelegramAdapter)
    manager.register_channel("webhook", TelegramAdapter)  # factory never constructed here
    manager.configure("webhook", {"enabled": True, "secret": "s3cret", "account": ""}, persist=True)
    set_channel_manager(manager)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as test_client:
        yield test_client, manager
    set_channel_manager(None)


def test_status_lists_registered_channels(client):
    test_client, manager = client
    response = test_client.get("/api/channels")
    assert response.status_code == 200
    body = response.json()
    names = {channel["name"] for channel in body["channels"]}
    assert {"telegram", "webhook"} <= names
    telegram = next(c for c in body["channels"] if c["name"] == "telegram")
    assert telegram["enabled"] is False  # not configured yet
    assert telegram["counts"]["inbound_pending"] == 0


def test_put_accounts_persists_non_secret_config(client, tmp_path):
    test_client, manager = client
    response = test_client.put(
        "/api/channels/accounts",
        json={"configs": {"telegram": {"enabled": True, "allowed_user_ids": [42]}}},
    )
    assert response.status_code == 200
    assert manager.configs["telegram"]["enabled"] is True
    persisted = (tmp_path / "channels.json").read_text(encoding="utf-8")
    assert "telegram" in persisted and "42" in persisted
    # unknown channel is a 404
    missing = test_client.put(
        "/api/channels/accounts", json={"configs": {"nope": {"enabled": True}}}
    )
    assert missing.status_code == 404


def test_put_accounts_strips_secret_fields(client):
    test_client, manager = client
    response = test_client.put(
        "/api/channels/accounts",
        json={"configs": {"telegram": {"enabled": True, "bot_token": "should-not-persist"}}},
    )
    assert response.status_code == 200
    assert "bot_token" not in manager.configs["telegram"]
    assert "should-not-persist" not in response.text


def test_credential_endpoint_uses_credential_store(client):
    test_client, manager = client
    response = test_client.post(
        "/api/channels/credential",
        json={"channel": "telegram", "field": "bot_token", "value": "tok-123"},
    )
    assert response.status_code == 200 and response.json()["set"] is True
    assert manager.credentials.get("telegram", "bot_token") == "tok-123"
    cleared = test_client.post(
        "/api/channels/credential", json={"channel": "telegram", "field": "bot_token", "value": ""}
    )
    assert cleared.json()["set"] is False
    assert manager.credentials.get("telegram", "bot_token") is None


def test_without_manager_reports_503(monkeypatch):
    set_channel_manager(None)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.get("/api/channels")
    assert response.status_code == 503


def test_inbound_webhook_requires_signature(client):
    test_client, manager = client
    body = b'{"event_id": "w1", "chat_id": "cart-9"}'
    # secret configured on the channel: unsigned and wrongly-signed are both 401
    unsigned = test_client.post("/api/channels/webhook/inbound", content=body)
    assert unsigned.status_code == 401
    wrong = test_client.post(
        "/api/channels/webhook/inbound",
        content=body,
        headers={"x-atlas-signature": "t=1,v1=00"},
    )
    assert wrong.status_code == 401


def test_inbound_webhook_good_signature_queues_event(client):
    test_client, manager = client
    body = b'{"event_id": "w2", "chat_id": "cart-9", "text": "hi"}'
    headers = {"x-atlas-signature": sign_payload("s3cret", int(time.time()), body)}
    response = test_client.post("/api/channels/webhook/inbound", content=body, headers=headers)
    assert response.status_code == 200
    assert response.json() == {"ok": True, "event_id": "w2", "channel": "webhook"}
    assert manager.ingress.pending_count(channel="webhook") == 1


def test_inbound_webhook_invalid_payload_is_422(client):
    test_client, manager = client
    body = b'{"chat_id": "cart-9"}'  # missing event_id
    headers = {"x-atlas-signature": sign_payload("s3cret", int(time.time()), body)}
    response = test_client.post("/api/channels/webhook/inbound", content=body, headers=headers)
    assert response.status_code == 422


def test_post_test_enqueues_through_delivery_queue(client):
    test_client, manager = client
    response = test_client.post(
        "/api/channels/test", json={"channel": "webhook", "chat_id": "cart-1", "text": "ping"}
    )
    assert response.status_code == 200
    key = response.json()["idempotency_key"]
    row = manager.delivery.get(key)
    assert row is not None and row.status == "pending"
    assert row.metadata.get("test") is True
    unknown = test_client.post("/api/channels/test", json={"channel": "nope", "chat_id": "x"})
    assert unknown.status_code == 404


def test_inbound_for_unknown_channel_is_403(client):
    test_client, manager = client
    response = test_client.post("/api/channels/ghost/inbound", content=b"{}")
    assert response.status_code == 403
