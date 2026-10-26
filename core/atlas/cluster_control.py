"""Local node identity, trusted peer registry, offline task queue and audit trail."""
from __future__ import annotations

import json
import os
import secrets
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atlas.config import DATA_ROOT

_LOCK = threading.RLock()


def _path() -> Path:
    return DATA_ROOT / "data" / "cluster-control.json"


def _empty() -> dict[str, Any]:
    return {"schema_version": 1, "node_id": uuid.uuid4().hex, "node_name": os.environ.get("COMPUTERNAME", "Atlas node"),
            "service_token": secrets.token_urlsafe(36), "peers": [], "trusted_sources": [], "revoked_sources": [],
            "queue": [], "receipts": {}, "audit": []}


def read_state() -> dict[str, Any]:
    with _LOCK:
        path = _path()
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if value.get("schema_version") != 1:
                raise ValueError("unsupported cluster state schema")
            value.setdefault("trusted_sources", [])
            value.setdefault("revoked_sources", [])
            value.setdefault("queue", [])
            value.setdefault("receipts", {})
            value.setdefault("audit", [])
            return value
        except FileNotFoundError:
            value = _empty()
            write_state(value)
            return value
        except (OSError, ValueError, TypeError):
            value = _empty()
            write_state(value)
            return value


def write_state(value: dict[str, Any]) -> None:
    with _LOCK:
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, path)


def audit(action: str, *, peer_id: str = "", subject_id: str = "", result: str = "ok", detail: str = "") -> None:
    state = read_state()
    state["audit"].append({"id": uuid.uuid4().hex, "time": datetime.now(UTC).isoformat(), "action": action,
                           "peer_id": peer_id, "subject_id": subject_id, "result": result, "detail": detail[:240]})
    state["audit"] = state["audit"][-1000:]
    write_state(state)


def peer_by_id(peer_id: str) -> dict[str, Any] | None:
    return next((item for item in read_state()["peers"] if item.get("id") == peer_id), None)


def update_peer(peer_id: str, **values: Any) -> dict[str, Any] | None:
    state = read_state()
    peer = next((item for item in state["peers"] if item.get("id") == peer_id), None)
    if peer:
        peer.update(values)
        write_state(state)
    return peer
