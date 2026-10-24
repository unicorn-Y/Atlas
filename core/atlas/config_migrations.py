"""Versioned, atomic migrations for Atlas TOML and user settings."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import tomli_w

CONFIG_SCHEMA_VERSION = 2
SETTINGS_SCHEMA_VERSION = 2
GLOBAL_GATEWAY_KEY = "atlas.gateway.api_key"


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
                store = _keyring()
                if not store.get(GLOBAL_GATEWAY_KEY):
                    store.set(GLOBAL_GATEWAY_KEY, secret)
                settings.pop("api_key", None)
                result["migrated"].append("gateway_key_from_user_settings")
            settings["schema_version"] = SETTINGS_SCHEMA_VERSION
            if old_version < SETTINGS_SCHEMA_VERSION or result["migrated"]:
                _backup_json_without_secrets(settings_path, json.loads(settings_path.read_text(encoding="utf-8")))
                _atomic_json(settings_path, settings)
            result["settings_version"] = SETTINGS_SCHEMA_VERSION
        except Exception:
            # Do not delete a plaintext legacy key unless the keyring write succeeded.
            result["settings_version"] = int(settings.get("schema_version", 0) or 0)
            result["settings_error"] = "OS credential migration failed; existing settings were preserved"

    if config_path.exists():
        try:
            raw_text = config_path.read_text(encoding="utf-8")
            import tomllib
            config = tomllib.loads(raw_text)
            if not isinstance(config, dict):
                config = {}
            version = int((config.get("meta") or {}).get("schema_version", 0))
            if version < CONFIG_SCHEMA_VERSION:
                models = config.get("models") if isinstance(config.get("models"), dict) else {}
                gateway = models.get("gateway") if isinstance(models.get("gateway"), dict) else {}
                secret = str(gateway.pop("api_key", "") or "").strip() if isinstance(gateway, dict) else ""
                if secret:
                    store = _keyring()
                    if not store.get(GLOBAL_GATEWAY_KEY):
                        store.set(GLOBAL_GATEWAY_KEY, secret)
                    result["migrated"].append("gateway_key_from_atlas_toml")
                config.setdefault("meta", {})["schema_version"] = CONFIG_SCHEMA_VERSION
                backup = config_path.with_suffix(config_path.suffix + ".pre-v2.bak")
                if not backup.exists():
                    clean = tomllib.loads(raw_text)
                    models = clean.get("models") if isinstance(clean.get("models"), dict) else {}
                    gateway = models.get("gateway") if isinstance(models.get("gateway"), dict) else {}
                    if isinstance(gateway, dict):
                        gateway.pop("api_key", None)
                    backup.write_text(tomli_w.dumps(clean), encoding="utf-8")
                temp = config_path.with_suffix(config_path.suffix + ".tmp")
                temp.write_text(tomli_w.dumps(config), encoding="utf-8")
                temp.replace(config_path)
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
