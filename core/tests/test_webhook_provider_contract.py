from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest

from atlas.automation.webhooks import (
    HmacWebhookProvider,
    WebhookAuthenticationError,
    WebhookCredentials,
    WebhookPayloadError,
)

pytestmark = pytest.mark.unit


def test_hmac_provider_returns_typed_session_request(tmp_path) -> None:
    credentials = WebhookCredentials(tmp_path / "secrets.json", tmp_path / "nonces.sqlite3")
    secret = credentials.rotate("ci")
    body = json.dumps({"build": 81}).encode()
    timestamp = str(int(time.time()))
    signature = "sha256=" + hmac.new(
        secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256
    ).hexdigest()

    request = HmacWebhookProvider(credentials).authenticate("ci", timestamp, signature, body)

    assert request.automation_id == "ci"
    assert request.payload == {"build": 81}


def test_hmac_provider_rejects_bad_signature_and_non_object_payload(tmp_path) -> None:
    credentials = WebhookCredentials(tmp_path / "secrets.json", tmp_path / "nonces.sqlite3")
    credentials.rotate("ci")
    provider = HmacWebhookProvider(credentials)
    timestamp = str(int(time.time()))

    with pytest.raises(WebhookAuthenticationError):
        provider.authenticate("ci", timestamp, "sha256=" + "0" * 64, b"{}")

    body = b"[]"
    secret = credentials._read()["ci"]
    signature = "sha256=" + hmac.new(
        secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256
    ).hexdigest()
    with pytest.raises(WebhookPayloadError):
        provider.authenticate("ci", timestamp, signature, body)

