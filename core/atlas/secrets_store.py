"""Local named secrets with keyring storage and an encrypted file fallback."""
from __future__ import annotations

import json
import os
import re
import threading
from typing import Any

from cryptography.fernet import Fernet

from atlas.config import DATA_ROOT

_LOCK = threading.RLock()
_HANDLE = re.compile(r"\{\{secret:([A-Za-z0-9_.-]+)\}\}")
_META = DATA_ROOT / "data" / "secrets.json"
_BLOB = DATA_ROOT / "data" / "secrets.enc"
_KEY = DATA_ROOT / "data" / "secrets.key"
_SERVICE = "Atlas"


def _read_meta() -> dict[str, dict[str, Any]]:
    try: value = json.loads(_META.read_text(encoding="utf-8"))
    except (OSError, ValueError): return {}
    return value if isinstance(value, dict) else {}


def _fernet() -> Fernet:
    _KEY.parent.mkdir(parents=True, exist_ok=True)
    if not _KEY.exists():
        _KEY.write_bytes(Fernet.generate_key())
        try: os.chmod(_KEY, 0o600)
        except OSError: pass
    return Fernet(_KEY.read_bytes())


def _fallback_read() -> dict[str, str]:
    try: return json.loads(_fernet().decrypt(_BLOB.read_bytes()).decode("utf-8"))
    except Exception: return {}


def _fallback_write(values: dict[str, str]) -> None:
    _BLOB.parent.mkdir(parents=True, exist_ok=True)
    temp = _BLOB.with_suffix(".tmp")
    temp.write_bytes(_fernet().encrypt(json.dumps(values, ensure_ascii=False).encode("utf-8")))
    try: os.chmod(temp, 0o600)
    except OSError: pass
    temp.replace(_BLOB)


def _keyring():
    try:
        import keyring
        backend = keyring.get_keyring()
        if backend.priority > 0: return keyring
    except Exception: pass
    return None


def list_secrets() -> list[dict[str, Any]]:
    return [{"name": name, "description": item.get("description", ""), "scope": item.get("scope", "global"), "backend": item.get("backend", "encrypted-file"), "handle": "{{secret:" + name + "}}"} for name, item in sorted(_read_meta().items())]


def set_secret(name: str, value: str, description: str = "", scope: str = "global") -> dict[str, Any]:
    name = str(name).strip().upper()
    if not re.fullmatch(r"[A-Z0-9_.-]{1,80}", name): raise ValueError("密钥名称仅可含字母、数字、点、下划线和连字符。")
    if scope != "global" and not scope.startswith("project:"): raise ValueError("scope must be global or project:<id>")
    if not value: raise ValueError("密钥值不能为空。")
    with _LOCK:
        meta, ring = _read_meta(), _keyring()
        backend = "keyring" if ring else "encrypted-file"
        if ring:
            try:
                ring.set_password(_SERVICE, name, value)
                stale = _fallback_read()
                if name in stale: stale.pop(name, None); _fallback_write(stale)
            except Exception: ring = None; backend = "encrypted-file"
        if not ring:
            secrets = _fallback_read(); secrets[name] = value; _fallback_write(secrets)
        meta[name] = {"description": description, "scope": scope, "backend": backend}
        _META.parent.mkdir(parents=True, exist_ok=True)
        _META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"name": name, "description": description, "scope": scope, "backend": backend, "handle": f"{{{{secret:{name}}}}}"}


def delete_secret(name: str) -> bool:
    with _LOCK:
        meta = _read_meta(); item = meta.pop(name.upper(), None)
        if item is None: return False
        ring = _keyring()
        if item.get("backend") == "keyring" and ring:
            try: ring.delete_password(_SERVICE, name.upper())
            except Exception: pass
        values = _fallback_read(); values.pop(name.upper(), None); _fallback_write(values)
        _META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return True


def resolve_secret(name: str, project_id: str | None = None) -> str | None:
    name = name.upper(); item = _read_meta().get(name)
    if not item or (item.get("scope", "global") != "global" and item.get("scope") != f"project:{project_id}"): return None
    if item.get("backend") == "keyring":
        ring = _keyring()
        if ring:
            try:
                value = ring.get_password(_SERVICE, name)
                if value is not None: return value
            except Exception: pass
    return _fallback_read().get(name)

def reveal_secret(name: str) -> str | None:
    """For the local settings page's explicit temporary reveal action only."""
    item = _read_meta().get(name.upper())
    if not item: return None
    return resolve_secret(name)


def resolve_handles(value: str, project_id: str | None = None) -> str:
    def replace(match: re.Match[str]) -> str:
        secret = resolve_secret(match.group(1), project_id)
        if secret is None: raise ValueError(f"密钥句柄 {match.group(0)} 不存在或不在当前项目范围内。")
        return secret
    return _HANDLE.sub(replace, str(value))


def redact(value: str) -> str:
    result = str(value)
    for item in list_secrets():
        secret = resolve_secret(item["name"])
        if secret and len(secret) >= 3: result = result.replace(secret, item["handle"])
    return result

class StreamingRedactor:
    """Keeps a secret-sized overlap so secrets split across process chunks stay hidden."""
    def __init__(self) -> None: self.pending = ""
    def feed(self, text: str, final: bool = False) -> str:
        self.pending += str(text)
        values = [resolve_secret(item["name"]) for item in list_secrets()]
        if final:
            ready, self.pending = self.pending, ""
            return redact(ready)
        hold = max((len(value) for value in values if value), default=1) - 1
        cut = max(0, len(self.pending) - hold)
        for secret in (value for value in values if value):
            start = self.pending.find(secret)
            while start >= 0:
                end = start + len(secret)
                if start < cut < end:
                    cut = end
                start = self.pending.find(secret, start + 1)
        ready, self.pending = self.pending[:cut], self.pending[cut:]
        return redact(ready)


def resolve_env(env: dict[str, str] | None, project_id: str | None = None) -> dict[str, str]:
    return {key: resolve_handles(value, project_id) for key, value in (env or {}).items()}
