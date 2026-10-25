from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from click.testing import CliRunner

from atlas.api.app_services import AppServices
from atlas.api.channel_router import router, set_channel_manager
from atlas.channels import ChannelManager
from atlas.channels.contract import ChannelAdapter, SendResult
from atlas.origin_guard import OriginGuard


class FakeAdapter(ChannelAdapter):
    async def start(self):
        return None

    async def stop(self):
        return None

    async def send(self, chat_id, content, **kwargs):
        return SendResult(ok=True, message_id="fake-message")


def make_client(tmp_path):
    manager = ChannelManager(db_path=tmp_path / "channels.sqlite")
    manager.register_channel("telegram", FakeAdapter)
    manager.configure("telegram", {"enabled": True}, persist=False)
    app = FastAPI()
    app.add_middleware(OriginGuard)
    app.include_router(router)
    app.state.services = AppServices()
    set_channel_manager(manager)
    return TestClient(app, client=("127.0.0.1", 50000)), manager


def test_manual_send_is_idempotent_and_reports_queue_delivery(tmp_path):
    client, manager = make_client(tmp_path)
    payload = {"channel": "telegram", "target": "@someone", "text": "Hello"}
    first = client.post("/api/channels/send", json=payload)
    second = client.post("/api/channels/send", json=payload)
    assert first.status_code == 200
    assert first.json()["idempotency_key"] == second.json()["idempotency_key"]
    key = first.json()["idempotency_key"]
    queued = client.get(f"/api/channels/delivery/{key}")
    assert queued.json()["status"] == "pending"
    assert queued.json()["attempts"] == 0
    record = manager.delivery.claim_due()[0]
    manager.delivery.mark_delivered(record.id, "fake-message")
    delivered = client.get(f"/api/channels/delivery/{key}")
    assert delivered.json()["status"] == "delivered"
    assert delivered.json()["message"] == "已送达"
    failed_request = client.post("/api/channels/send", json={**payload, "text": "retry me"})
    retry_record = manager.delivery.claim_due()[0]
    manager.delivery.fail(retry_record.id, "temporary adapter error", retryable=True, now=100)
    retry = client.get(f"/api/channels/delivery/{failed_request.json()['idempotency_key']}")
    assert retry.json()["status"] == "pending"
    assert retry.json()["attempts"] == 1
    assert retry.json()["message"] == "投递失败，已安排重试"
    manager.ingress.close()
    manager.delivery.close()
    set_channel_manager(None)


def test_manual_send_validates_enabled_channel_and_target(tmp_path):
    client, manager = make_client(tmp_path)
    assert client.post("/api/channels/send", json={
        "channel": "missing", "target": "x", "text": "hello",
    }).status_code == 422
    assert client.post("/api/channels/send", json={
        "channel": "telegram", "target": "bad\ntarget", "text": "hello",
    }).status_code == 422
    manager.configure("telegram", {"enabled": False}, persist=False)
    assert client.post("/api/channels/send", json={
        "channel": "telegram", "target": "@someone", "text": "hello",
    }).status_code == 422
    manager.ingress.close()
    manager.delivery.close()
    set_channel_manager(None)


def test_channel_send_cli_queues_and_reports_delivery(monkeypatch):
    from atlas.cli import main
    import atlas.config

    monkeypatch.setattr(atlas.config, "get_config", lambda: type("Config", (), {"server_port": 18765})())

    class Response:
        is_success = True
        def __init__(self, body): self.body = body
        def json(self): return self.body

    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def post(self, url, json):
            assert url == "http://127.0.0.1:18765/api/channels/send"
            assert json == {"channel": "telegram", "target": "12345", "text": "hello"}
            return Response({"idempotency_key": "a" * 64, "status": "pending"})
        def get(self, url):
            assert url.endswith("/" + "a" * 64)
            return Response({"status": "delivered", "attempts": 1, "message": "已送达"})

    monkeypatch.setattr("httpx.Client", Client)
    result = CliRunner().invoke(main, ["channel", "send", "--channel", "telegram", "--target", "12345", "--text", "hello", "--wait-seconds", "1"])
    assert result.exit_code == 0, result.output
    assert "status=delivered attempts=1" in result.output
