"""Small Atlas-backed adapter for configuration helpers used by ported code.

This module reads Atlas' ``config/atlas.toml``. It deliberately does not create
configuration files, import Hermes, or expose Hermes credentials and setup.
"""

from __future__ import annotations

import getpass
import os
import subprocess
import tomllib
from pathlib import Path
from typing import Any

from atlas.config import CONFIG_PATH

DEFAULT_CONFIG: dict[str, Any] = {
    "models": {},
    "browser": {},
    "computer_use": {},
    "sessions": {},
    "database": {},
}

# Kept as dictionaries because existing callers clear these caches after a
# config write. The adapter itself favors fresh reads to preserve Atlas reloads.
_LOAD_CONFIG_CACHE: dict[str, Any] = {}
_RAW_CONFIG_CACHE: dict[str, Any] = {}
_LAST_EXPANDED_CONFIG_BY_PATH: dict[str, Any] = {}


def _config_path(path: str | os.PathLike[str] | None = None) -> Path:
    return Path(path) if path is not None else CONFIG_PATH


def _legacy_home() -> Path | None:
    home = os.environ.get("ATLAS_HOME") or os.environ.get("HERMES_HOME")
    return Path(home) if home else None


def read_raw_config(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Return the raw Atlas TOML mapping without creating or modifying files."""
    target = _config_path(path)
    try:
        with target.open("rb") as stream:
            value = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def load_config_readonly(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Compatibility name for a read-only Atlas config load."""
    return read_raw_config(path)


def load_config(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Return Atlas settings as a plain mapping, with no write-on-missing behavior."""
    return load_config_readonly(path)


def load_legacy_home_config() -> dict[str, Any]:
    """Read legacy engine settings from ATLAS_HOME or HERMES_HOME without writes.

    This remains separate from Atlas' ``config/atlas.toml``. It supports
    existing per-profile state database settings while the runtime migrates.
    """
    try:
        import yaml
    except ImportError:
        return {}
    homes = [os.environ.get("ATLAS_HOME"), os.environ.get("HERMES_HOME")]
    for home in dict.fromkeys(value for value in homes if value):
        path = Path(home) / "config.yaml"
        try:
            value = yaml.safe_load(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        except yaml.YAMLError:
            return {}
        if isinstance(value, dict):
            return value
    return {}


def save_config(config: dict[str, Any], path: str | os.PathLike[str] | None = None) -> None:
    """Persist Atlas TOML settings atomically and refresh Atlas' config singleton."""
    import tomli_w

    target = _config_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(tomli_w.dumps(config), encoding="utf-8")
    temporary.replace(target)
    _LOAD_CONFIG_CACHE.clear()
    _RAW_CONFIG_CACHE.clear()
    _LAST_EXPANDED_CONFIG_BY_PATH.clear()
    if path is None:
        from atlas.config import reload_config

        reload_config()


def load_env() -> dict[str, str]:
    """Read simple KEY=VALUE entries from the current profile's legacy .env file."""
    home = _legacy_home()
    if home is None:
        return {}
    result: dict[str, str] = {}
    try:
        lines = (home / ".env").read_text(encoding="utf-8").splitlines()
    except OSError:
        return result
    for line in lines:
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        if value.startswith("export "):
            value = value[7:].lstrip()
        key, separator, item = value.partition("=")
        if separator and key.strip():
            item = item.strip()
            if len(item) >= 2 and item[0] == item[-1] and item[0] in {"'", '"'}:
                item = item[1:-1]
            result[key.strip()] = item
    return result


def cfg_get(*keys: Any, default: Any = None) -> Any:
    """Read an Atlas setting, accepting both dotted and legacy section keys."""
    if keys and isinstance(keys[0], dict):
        node: Any = keys[0]
        parts = [str(part) for part in keys[1:]]
    else:
        node = load_config_readonly()
        parts = [str(part) for part in keys]
    if len(parts) == 1:
        parts = parts[0].split(".")
    for part in parts:
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return default if node is None else node


def is_managed() -> bool:
    """Whether the host explicitly marks Atlas configuration as managed."""
    return os.environ.get("ATLAS_CONFIG_MANAGED", "").strip().lower() in {"1", "true", "yes"}


def _secure_dir(path: str | os.PathLike[str]) -> Path:
    """Create a private cache directory where POSIX permissions are available."""
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        directory.chmod(0o700)
    else:
        subprocess.run(
            ["icacls", str(directory), "/inheritance:r", "/grant:r",
             f"{getpass.getuser()}:(OI)(CI)F"],
            check=True, capture_output=True, text=True,
        )
    return directory

