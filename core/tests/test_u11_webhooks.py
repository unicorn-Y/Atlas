from __future__ import annotations

import hashlib
import hmac
import json
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from atlas.automation.webhooks import WebhookCredentials
from atlas.api import automation_router as router_module
from atlas.api.automation_router import automation_router
from atlas.automation.engine import _message_with_webhook_payload


def test_webhook_route_verifies_signature_enqueues_payload_and_rejects_replay(tmp_path, monkeypatch) -> None:
    credentials = WebhookCredentials(tmp_path / "secrets.json", tmp_path / "nonces.sqlite3")
    secret = credentials.rotate("external-event")

    class Store:
        def get(self, automation_id):
            return {"id": automation_id, "trigger": {"kind": "webhook"}}

    class Engine:
        started = True
        store = Store()

        async def trigger_event(self, automation_id, *, source, payload):
            return {"fired": True, "automation_id": automation_id, "source": source, "payload": payload}

    monkeypatch.setattr(router_module, "get_webhook_credentials", lambda: credentials)
    monkeypatch.setattr(router_module, "_engine", lambda: Engine())
    app = FastAPI()
    app.include_router(automation_router)
    body = json.dumps({"build": 81, "status": "passed"}, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    signature = "sha256=" + hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    headers = {"X-Atlas-Timestamp": timestamp, "X-Atlas-Signature": signature,
               "Content-Type": "application/json"}
    with TestClient(app) as client:
        assert client.post("/api/automations/external-event/webhook", content=body, headers=headers).json() == {
            "fired": True, "automation_id": "external-event", "source": "webhook",
            "payload": {"build": 81, "status": "passed"},
        }
        assert client.post("/api/automations/external-event/webhook", content=body, headers=headers).status_code == 401
        bad = {**headers, "X-Atlas-Signature": "sha256=" + "0" * 64}
        assert client.post("/api/automations/external-event/webhook", content=body, headers=bad).status_code == 401
        assert client.post("/api/automations/external-event/webhook", content=b"x" * (256 * 1024 + 1), headers=headers).status_code == 413


def test_webhook_payload_reaches_agent_prompt() -> None:
    rendered = _message_with_webhook_payload("检查这次 CI", "webhook", {"build": 81})
    assert "检查这次 CI" in rendered and '"build": 81' in rendered
    assert _message_with_webhook_payload("定时运行", "cron", {"build": 81}) == "定时运行"


