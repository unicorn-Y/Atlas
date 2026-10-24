"""Versioned project configuration and project-scoped OS credentials."""

from __future__ import annotations

import json
import os
import re
import threading
from typing import Any

from atlas.config import DATA_ROOT

_LOCK = threading.RLock()
_PATH = DATA_ROOT / "data" / "project-settings.json"
_PROJECT_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_GATEWAY_KEY = "atlas.project.{project_id}.gateway.api_key"


def _valid_project_id(project_id: str) -> str:
    value = str(project_id or "").strip()
    if not _PROJECT_ID.fullmatch(value):
        raise ValueError("项目 ID 格式无效")
    return value


def _load_all() -> dict[str, Any]:
    try:
        value = json.loads(_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 1, "projects": {}, "sessions": {}}
    if not isinstance(value, dict) or not isinstance(value.get("projects"), dict):
        return {"schema_version": 1, "projects": {}, "sessions": {}}
    value.setdefault("sessions", {})
    return value


def load_project_config(project_id: str | None) -> dict[str, Any]:
    if not project_id:
        return {}
    project_id = _valid_project_id(project_id)
    with _LOCK:
        entry = _load_all()["projects"].get(project_id, {})
    config = entry.get("config", {}) if isinstance(entry, dict) else {}
    return config if isinstance(config, dict) else {}


def save_project_config(project_id: str, config: dict[str, Any]) -> dict[str, Any]:
    project_id = _valid_project_id(project_id)
    if not isinstance(config, dict):
        raise ValueError("项目配置必须是对象")
    if any(not isinstance(key, str) or not key.strip() or "api_key" in key.casefold() for key in config):
        raise ValueError("配置键无效；凭据必须单独存入系统凭据库")
    json.dumps(config, ensure_ascii=False)
    with _LOCK:
        data = _load_all()
        projects = data.setdefault("projects", {})
        entry = projects.setdefault(project_id, {})
        entry["config"] = config
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        temp = _PATH.with_suffix(".json.tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(temp, 0o600)
        except OSError:
            pass
        temp.replace(_PATH)
    return config


def load_session_config(session_id: str | None) -> dict[str, Any]:
    if not session_id:
        return {}
    session_id = _valid_project_id(session_id)
    with _LOCK:
        entry = _load_all()["sessions"].get(session_id, {})
    config = entry.get("config", {}) if isinstance(entry, dict) else {}
    return config if isinstance(config, dict) else {}


def save_session_config(session_id: str, config: dict[str, Any]) -> dict[str, Any]:
    session_id = _valid_project_id(session_id)
    if not isinstance(config, dict) or any(
        not isinstance(key, str) or not key.strip() or "api_key" in key.casefold()
        for key in config
    ):
        raise ValueError("会话配置无效；凭据必须单独存入系统凭据库")
    json.dumps(config, ensure_ascii=False)
    with _LOCK:
        data = _load_all()
        entry = data.setdefault("sessions", {}).setdefault(session_id, {})
        entry["config"] = config
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        temp = _PATH.with_suffix(".json.tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(temp, 0o600)
        except OSError:
            pass
        temp.replace(_PATH)
    return config


def _credential_store():
    from atlas.telegram import KeyringCredentialStore

    return KeyringCredentialStore()


def project_gateway_key_account(project_id: str) -> str:
    return _GATEWAY_KEY.format(project_id=_valid_project_id(project_id))


def session_gateway_key_account(session_id: str) -> str:
    return f"atlas.session.{_valid_project_id(session_id)}.gateway.api_key"


def get_project_gateway_key(project_id: str | None) -> str | None:
    if not project_id:
        return None
    try:
        return _credential_store().get(project_gateway_key_account(project_id))
    except Exception:
        return None


def set_project_gateway_key(project_id: str, secret: str | None) -> bool:
    account = project_gateway_key_account(project_id)
    store = _credential_store()
    if secret and secret.strip():
        store.set(account, secret.strip())
        return True
    store.delete(account)
    return False


def get_session_gateway_key(session_id: str | None) -> str | None:
    if not session_id:
        return None
    try:
        return _credential_store().get(session_gateway_key_account(session_id))
    except Exception:
        return None


def set_session_gateway_key(session_id: str, secret: str | None) -> bool:
    account = session_gateway_key_account(session_id)
    store = _credential_store()
    if secret and secret.strip():
        store.set(account, secret.strip())
        return True
    store.delete(account)
    return False
