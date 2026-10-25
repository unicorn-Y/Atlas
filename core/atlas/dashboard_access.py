"""Local browser dashboard lifecycle and short-lived, read-only access token."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any

from atlas.config import DATA_ROOT


def control_path() -> Path:
    return DATA_ROOT / "data" / "runtime" / "dashboard.json"


def read_control(*, include_expired: bool = False) -> dict[str, Any]:
    try:
        value = json.loads(control_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(value, dict) or (
        not include_expired and int(value.get("expires_at", 0) or 0) <= int(time.time())
    ):
        return {}
    return value


def create_access(*, port: int, pid: int, owns_server: bool, shutdown_token: str = "") -> tuple[str, dict[str, Any]]:
    token = secrets.token_urlsafe(32)
    info = {
        "token_hash": hashlib.sha256(token.encode("utf-8")).hexdigest(),
        "session_id": secrets.token_hex(12), "port": int(port), "pid": int(pid),
        "owns_server": bool(owns_server), "shutdown_token": shutdown_token,
        "expires_at": int(time.time()) + 8 * 60 * 60,
    }
    path = control_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(info, indent=2), encoding="utf-8")
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    temporary.replace(path)
    return token, info


def token_valid(token: str | None) -> bool:
    info = read_control()
    if not token or len(token) > 256 or not info.get("token_hash"):
        return False
    return secrets.compare_digest(
        hashlib.sha256(token.encode("utf-8")).hexdigest(), str(info["token_hash"]),
    )


def revoke_access() -> None:
    control_path().unlink(missing_ok=True)
