"""Local credentials and replay protection for automation webhooks."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class WebhookSessionRequest:
    """Authenticated, parsed request passed from a provider to automation dispatch."""

    automation_id: str
    payload: dict[str, Any]


class WebhookAuthenticationError(ValueError):
    """Provider could not authenticate the inbound request."""


class WebhookPayloadError(ValueError):
    """An authenticated webhook did not contain a JSON object."""


class WebhookProvider(Protocol):
    def authenticate(
        self, automation_id: str, timestamp: str, signature: str, body: bytes,
    ) -> WebhookSessionRequest: ...


class WebhookCredentials:
    """Persist per-automation HMAC secrets and one-use timestamp/signature pairs."""

    def __init__(self, path: str | Path | None = None, nonce_db: str | Path | None = None):
        if path is None or nonce_db is None:
            from atlas.config import DATA_ROOT

            path = path or DATA_ROOT / "data" / "automation-webhook-secrets.json"
            nonce_db = nonce_db or DATA_ROOT / "data" / "automation-webhook-nonces.sqlite3"
        self.path = Path(path)
        self.nonce_db = Path(nonce_db)
        self._lock = threading.Lock()

    def _read(self) -> dict[str, str]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def rotate(self, automation_id: str) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            values = self._read()
            values[automation_id] = token
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(values), encoding="utf-8")
            temporary.replace(self.path)
        return token

    def delete(self, automation_id: str) -> None:
        with self._lock:
            values = self._read()
            if automation_id not in values:
                return
            values.pop(automation_id, None)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(values), encoding="utf-8")
            temporary.replace(self.path)

    def verify(self, automation_id: str, timestamp: str, signature: str, body: bytes) -> bool:
        if not timestamp.isascii() or not timestamp.isdecimal():
            return False
        try:
            stamp = int(timestamp)
        except (TypeError, ValueError):
            return False
        if abs(time.time() - stamp) > 300 or not signature.startswith("sha256="):
            return False
        secret = self._read().get(automation_id)
        if not secret:
            return False
        expected = "sha256=" + hmac.new(
            secret.encode("utf-8"), timestamp.encode("ascii") + b"." + body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return False
        self.nonce_db.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.nonce_db, timeout=5) as db:
            db.execute("CREATE TABLE IF NOT EXISTS webhook_nonces (automation_id TEXT NOT NULL, signature TEXT NOT NULL, seen_at INTEGER NOT NULL, PRIMARY KEY (automation_id, signature))")
            db.execute("DELETE FROM webhook_nonces WHERE seen_at < ?", (int(time.time()) - 600,))
            try:
                db.execute("INSERT INTO webhook_nonces VALUES (?, ?, ?)", (automation_id, signature, int(time.time())))
            except sqlite3.IntegrityError:
                return False
        return True


class HmacWebhookProvider:
    """Adapter for Atlas's timestamped SHA-256 webhook signature contract."""

    def __init__(self, credentials: WebhookCredentials):
        self.credentials = credentials

    def authenticate(
        self, automation_id: str, timestamp: str, signature: str, body: bytes,
    ) -> WebhookSessionRequest:
        if not self.credentials.verify(automation_id, timestamp, signature, body):
            raise WebhookAuthenticationError("invalid or replayed webhook signature")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WebhookPayloadError("webhook body must be a JSON object") from exc
        if not isinstance(payload, dict):
            raise WebhookPayloadError("webhook body must be a JSON object")
        return WebhookSessionRequest(automation_id=automation_id, payload=payload)


_credentials: WebhookCredentials | None = None


def get_webhook_credentials() -> WebhookCredentials:
    global _credentials
    if _credentials is None:
        _credentials = WebhookCredentials()
    return _credentials


def get_webhook_provider(credentials: WebhookCredentials | None = None) -> WebhookProvider:
    return HmacWebhookProvider(credentials or get_webhook_credentials())


__all__ = [
    "HmacWebhookProvider", "WebhookAuthenticationError", "WebhookCredentials",
    "WebhookPayloadError", "WebhookProvider", "WebhookSessionRequest",
    "get_webhook_credentials", "get_webhook_provider",
]
