"""Short-lived, revocable bearer credentials for the Atlas mobile remote page."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import socket
import threading
import time
from typing import Any

from atlas.config import DATA_ROOT

_PATH = DATA_ROOT / "data" / "runtime" / "remote-access.json"
_LOCK = threading.RLock()


def _read() -> dict[str, Any]:
    try:
        value = json.loads(_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {"sessions": {}}
    except (OSError, json.JSONDecodeError):
        return {"sessions": {}}


def _write(value: dict[str, Any]) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = _PATH.with_suffix(".json.tmp")
    temp.write_text(json.dumps(value, indent=2), encoding="utf-8")
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    temp.replace(_PATH)


def create_remote_session(ttl_seconds: int = 8 * 60 * 60) -> dict[str, Any]:
    if not 60 <= ttl_seconds <= 24 * 60 * 60:
        raise ValueError("Remote access lifetime must be between 1 minute and 24 hours")
    token = secrets.token_urlsafe(32)
    session_id = secrets.token_hex(12)
    expires_at = int(time.time()) + ttl_seconds
    with _LOCK:
        data = _read()
        sessions = data.setdefault("sessions", {})
        sessions[session_id] = {"token_hash": hashlib.sha256(token.encode()).hexdigest(), "expires_at": expires_at}
        data["sessions"] = {key: row for key, row in sessions.items() if int(row.get("expires_at", 0)) > int(time.time())}
        _write(data)
    return {"session_id": session_id, "token": token, "expires_at": expires_at}


def remote_token_valid(token: str | None) -> bool:
    if not token or len(token) > 256:
        return False
    digest = hashlib.sha256(token.encode()).hexdigest()
    now = int(time.time())
    with _LOCK:
        data = _read()
        sessions = data.get("sessions", {})
        valid = any(int(row.get("expires_at", 0)) > now and secrets.compare_digest(str(row.get("token_hash", "")), digest)
                    for row in sessions.values() if isinstance(row, dict))
        if len(sessions) > 0 and any(int(row.get("expires_at", 0)) <= now for row in sessions.values() if isinstance(row, dict)):
            data["sessions"] = {key: row for key, row in sessions.items() if int(row.get("expires_at", 0)) > now}
            _write(data)
        return valid


def revoke_remote_session(session_id: str | None = None) -> int:
    with _LOCK:
        data = _read()
        sessions = data.get("sessions", {})
        if session_id:
            removed = int(session_id in sessions)
            sessions.pop(session_id, None)
        else:
            removed = len(sessions)
            sessions.clear()
        data["sessions"] = sessions
        _write(data)
    return removed


def remote_access_status() -> dict[str, Any]:
    now = int(time.time())
    with _LOCK:
        sessions = _read().get("sessions", {})
    active = [row for row in sessions.values() if isinstance(row, dict) and int(row.get("expires_at", 0)) > now]
    return {"active_sessions": len(active), "latest_expiry": max((int(row["expires_at"]) for row in active), default=None)}


def local_network_address() -> str:
    """Find the interface address used for routed traffic without sending packets."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))
            address = probe.getsockname()[0]
            if not address.startswith("127."):
                return address
    except OSError:
        pass
    return "127.0.0.1"
