"""Read selected Chromium saved logins into Atlas's local encrypted vault.

This is deliberately metadata-only until a row is explicitly selected for import.
Passwords are decrypted in the API process and passed straight to VaultStore; they
are never returned by the candidate endpoint or written to logs.
"""

from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


@dataclass(frozen=True)
class PasswordProfile:
    id: str
    browser: str
    label: str
    directory: Path


def _local_app_data() -> Path:
    value = os.environ.get("LOCALAPPDATA")
    if not value:
        raise RuntimeError("Windows 浏览器密码库导入仅支持当前用户的 Windows Profile")
    return Path(value)


def list_profiles(browser: str) -> list[PasswordProfile]:
    normalized = browser.strip().lower()
    if normalized not in {"chrome", "edge"}:
        raise ValueError("仅支持 Chrome 和 Microsoft Edge")
    root = _local_app_data() / ("Google/Chrome/User Data" if normalized == "chrome" else "Microsoft/Edge/User Data")
    if not root.is_dir():
        return []
    profiles = []
    for directory in sorted(root.iterdir()):
        if not directory.is_dir() or not (directory / "Login Data").is_file():
            continue
        label = "Default" if directory.name == "Default" else directory.name
        source_id = hashlib.sha256(f"{normalized}:{directory.name}".encode()).hexdigest()[:20]
        profiles.append(PasswordProfile(source_id, normalized, f"{normalized.title()} · {label}", directory))
    return profiles


def list_candidates(browser: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for profile in list_profiles(browser):
        for row in _read_rows(profile):
            url = str(row["origin_url"] or "")
            parts = urlsplit(url)
            if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
                continue
            identity = hashlib.sha256(f"{profile.id}:{row['rowid']}".encode()).hexdigest()[:24]
            candidates.append({
                "id": identity, "source_id": profile.id, "source": profile.label,
                "origin": f"{parts.scheme}://{parts.netloc}",
                "username": str(row["username_value"] or ""),
                "label": parts.hostname,
            })
    return candidates


def import_selected(browser: str, selected_ids: list[str], store: Any, *, existing_origins: dict[str, str], overwrite_confirmed: bool = False) -> dict[str, Any]:
    wanted = set(selected_ids)
    imported = []
    skipped = []
    for profile in list_profiles(browser):
        for row in _read_rows(profile):
            candidate_id = hashlib.sha256(f"{profile.id}:{row['rowid']}".encode()).hexdigest()[:24]
            if candidate_id not in wanted:
                continue
            url = str(row["origin_url"] or "")
            parts = urlsplit(url)
            if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
                skipped.append(candidate_id)
                continue
            origin = f"{parts.scheme}://{parts.netloc}"
            key = f"{origin}\0{str(row['username_value'] or '')}"
            if not str(row["username_value"] or "").strip():
                skipped.append(candidate_id)
                continue
            password = _decrypt_password(profile.directory, bytes(row["password_value"] or b""))
            if not password:
                skipped.append(candidate_id)
                continue
            if key in existing_origins:
                if not overwrite_confirmed:
                    skipped.append(candidate_id)
                    continue
                if store.rotate_login_password(existing_origins[key], password):
                    imported.append(candidate_id)
                else:
                    skipped.append(candidate_id)
                continue
            created = store.add_item("login", str(parts.hostname), {
                "identifier_type": "username", "identifier": str(row["username_value"] or ""),
                "password": password,
            }, origin, login_method={"fields": {"identifier": "username", "password": "current-password"},
                                    "confirm_before_fill": True, "source": profile.label})
            existing_origins[key] = created.id
            imported.append(candidate_id)
    return {"imported": imported, "skipped": skipped}


def _read_rows(profile: PasswordProfile) -> list[sqlite3.Row]:
    source = profile.directory / "Login Data"
    with tempfile.TemporaryDirectory(prefix="atlas-login-import-") as temp_dir:
        copy = Path(temp_dir) / "Login Data"
        shutil.copy2(source, copy)
        db = sqlite3.connect(f"file:{copy.as_posix()}?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        try:
            return list(db.execute("SELECT rowid, origin_url, username_value, password_value FROM logins WHERE blacklisted_by_user = 0"))
        finally:
            db.close()


def _dpapi_decrypt(ciphertext: bytes) -> bytes:
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    if os.name != "nt":
        raise RuntimeError("浏览器密码解密需要在 Windows 当前用户会话中运行")
    source_buffer = ctypes.create_string_buffer(ciphertext)
    source = DATA_BLOB(len(ciphertext), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
    output = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(output)):
        raise RuntimeError("Windows 无法解密所选浏览器凭据")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)


def _decrypt_password(profile_dir: Path, encrypted: bytes) -> str:
    if encrypted.startswith((b"v10", b"v11")):
        state_path = profile_dir.parent / "Local State"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        encrypted_key = base64.b64decode(state["os_crypt"]["encrypted_key"])[5:]
        key = _dpapi_decrypt(encrypted_key)
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError as exc:
            raise RuntimeError("需要安装 cryptography 才能导入 Chrome/Edge 密码") from exc
        nonce, payload = encrypted[3:15], encrypted[15:]
        return AESGCM(key).decrypt(nonce, payload, None).decode("utf-8")
    if encrypted.startswith(b"v20"):
        raise RuntimeError("此浏览器条目使用 Chromium App-Bound 加密，当前系统账户接口无法解密")
    return _dpapi_decrypt(encrypted).decode("utf-8")
