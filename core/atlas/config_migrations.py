"""Versioned, atomic migrations for Atlas TOML and user settings."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any


CONFIG_SCHEMA_VERSION = 2
SETTINGS_SCHEMA_VERSION = 2
GLOBAL_GATEWAY_KEY = "atlas.gateway.api_key"
# A different key found during migration (e.g. an atlas.toml key shadowed by user-settings) is kept here
# instead of being dropped; it is never used automatically.
SUPERSEDED_GATEWAY_KEY = "atlas.gateway.api_key.superseded"


def _keyring():
    from atlas.telegram import KeyringCredentialStore

    return KeyringCredentialStore()


def _atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    temp.replace(path)


def _backup_json_without_secrets(path: Path, data: dict[str, Any]) -> None:
    backup = path.with_suffix(path.suffix + ".pre-v2.bak")
    if backup.exists():
        return
    sanitized = dict(data)
    sanitized.pop("api_key", None)
    _atomic_json(backup, sanitized)


def _store_in_keyring(secret: str) -> str:
    """Put ``secret`` in the OS keyring and report "stored" only when reading it back matches.

    One keyring entry serves every Atlas data directory of this OS user, so a *different* key may
    already be there (another checkout, an older key). Never drop a plaintext key in that case:
    return "conflict" and let the caller keep it.
    """
    store = _keyring()
    existing = store.get(GLOBAL_GATEWAY_KEY)
    if not existing:
        store.set(GLOBAL_GATEWAY_KEY, secret)
        existing = store.get(GLOBAL_GATEWAY_KEY)
    if existing == secret:
        return "stored"
    return "conflict" if existing else "failed"


def _strip_gateway_key_line(raw_text: str) -> str:
    """Remove only `api_key = ...` inside [models.gateway]; comments and layout stay untouched."""
    import re

    out: list[str] = []
    section = ""
    for line in raw_text.splitlines(keepends=True):
        # Also recognise array-of-tables headers ([[models.custom]]): missing them kept "models.gateway"
        # as the current section and stripped a custom model's own api_key.
        header = re.match(r"\s*\[\[?([^\[\]]+)\]\]?\s*(#.*)?$", line)
        if header:
            section = header.group(1).strip()
        elif section == "models.gateway" and re.match(r"\s*api_key\s*=", line):
            continue
        out.append(line)
    return "".join(out)


def migrate_configuration(config_path: Path, settings_path: Path) -> dict[str, Any]:
    """Upgrade schemas and move legacy gateway keys into the OS credential store.

    Sanitized pre-migration files are retained as ``.pre-v2.bak`` once. Secret
    values are deliberately excluded so rollback cannot restore plaintext keys.
    """
    result: dict[str, Any] = {"config_version": 0, "settings_version": 0, "migrated": []}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            settings = {}
        if not isinstance(settings, dict):
            settings = {}
        old_version = int(settings.get("schema_version", 0) or 0)
        try:
            secret = str(settings.get("api_key") or "").strip()
            if secret:
                outcome = _store_in_keyring(secret)
                if outcome == "stored":
                    settings.pop("api_key", None)
                    result["migrated"].append("gateway_key_from_user_settings")
                else:
                    result["settings_conflict"] = (
                        "系统钥匙串里已有一个不同的网关 key，配置文件里的明文 key 保留未迁移"
                        if outcome == "conflict" else "钥匙串写入后读不回，配置文件里的明文 key 保留未迁移")
            settings["schema_version"] = SETTINGS_SCHEMA_VERSION
            if old_version < SETTINGS_SCHEMA_VERSION or result["migrated"]:
                _backup_json_without_secrets(settings_path, json.loads(settings_path.read_text(encoding="utf-8")))
                _atomic_json(settings_path, settings)
            result["settings_version"] = SETTINGS_SCHEMA_VERSION
        except Exception:
            # Do not delete a plaintext legacy key unless the keyring write succeeded.
            result["settings_version"] = int(settings.get("schema_version", 0) or 0)
            result["settings_error"] = "OS credential migration failed; existing settings were preserved"

    # user-settings' key (now in the keyring) overrides atlas.toml at runtime — whether it was moved in
    # this call or by an earlier start — so a different atlas.toml key is a shadowed, unused one.
    settings_owns_key = "gateway_key_from_user_settings" in result["migrated"]
    if not settings_owns_key and settings_path.exists():
        try:
            current = json.loads(settings_path.read_text(encoding="utf-8"))
            settings_owns_key = (isinstance(current, dict) and int(current.get("schema_version", 0) or 0) >= SETTINGS_SCHEMA_VERSION
                                 and not current.get("api_key"))
        except (OSError, ValueError, TypeError):
            settings_owns_key = False
    if config_path.exists():
        try:
            raw_text = config_path.read_text(encoding="utf-8")
            import tomllib
            config = tomllib.loads(raw_text)
            models = config.get("models") if isinstance(config.get("models"), dict) else {}
            gateway = models.get("gateway") if isinstance(models.get("gateway"), dict) else {}
            secret = str(gateway.get("api_key", "") or "").strip() if isinstance(gateway, dict) else ""
            # Only touch atlas.toml when it actually holds a key, and then remove just that line:
            # rewriting the whole file with tomli_w would drop the user's comments and layout.
            if secret:
                outcome = _store_in_keyring(secret)
                if outcome == "stored":
                    backup = config_path.with_suffix(config_path.suffix + ".pre-v2.bak")
                    stripped = _strip_gateway_key_line(raw_text)
                    if not backup.exists():
                        backup.write_text(stripped, encoding="utf-8")
                    tomllib.loads(stripped)  # never write something that no longer parses
                    temp = config_path.with_suffix(config_path.suffix + ".tmp")
                    temp.write_text(stripped, encoding="utf-8")
                    temp.replace(config_path)
                    result["migrated"].append("gateway_key_from_atlas_toml")
                elif outcome == "conflict" and settings_owns_key:
                    # user-settings' key wins at runtime, so this atlas.toml key was already unused:
                    # park it in a separate keyring entry, then strip the plaintext line.
                    store = _keyring()
                    store.set(SUPERSEDED_GATEWAY_KEY, secret)
                    if store.get(SUPERSEDED_GATEWAY_KEY) == secret:
                        stripped = _strip_gateway_key_line(raw_text)
                        tomllib.loads(stripped)
                        backup = config_path.with_suffix(config_path.suffix + ".pre-v2.bak")
                        if not backup.exists():
                            backup.write_text(stripped, encoding="utf-8")
                        temp = config_path.with_suffix(config_path.suffix + ".tmp")
                        temp.write_text(stripped, encoding="utf-8")
                        temp.replace(config_path)
                        result["migrated"].append("superseded_gateway_key_from_atlas_toml")
                    else:
                        result["config_conflict"] = "atlas.toml 中被覆盖的旧 key 无法存入钥匙串，保留未迁移"
                else:
                    result["config_conflict"] = "系统钥匙串里已有不同的网关 key，atlas.toml 中的 key 保留未迁移"
            result["config_version"] = CONFIG_SCHEMA_VERSION
        except Exception:
            result["config_error"] = "TOML schema migration failed; original config was preserved"
    return result


def rollback_configuration_migration(config_path: Path, settings_path: Path) -> dict[str, bool]:
    restored: dict[str, bool] = {}
    for label, target in (("config", config_path), ("settings", settings_path)):
        backup = target.with_suffix(target.suffix + ".pre-v2.bak")
        if backup.is_file():
            shutil.copy2(backup, target)
            restored[label] = True
        else:
            restored[label] = False
    return restored
