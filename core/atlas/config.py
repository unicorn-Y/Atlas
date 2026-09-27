"""Atlas configuration — load from atlas.toml with env-var overrides."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import structlog

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(
    os.environ.get("ATLAS_ROOT", Path(__file__).resolve().parent.parent.parent)
).resolve()  # D:\Atlas\core -> D:\Atlas
DATA_ROOT = Path(os.environ.get("ATLAS_DATA_DIR", PROJECT_ROOT)).resolve()
CONFIG_PATH = (DATA_ROOT if os.environ.get("ATLAS_DATA_DIR") else PROJECT_ROOT) / "config" / "atlas.toml"
EXAMPLE_CONFIG_PATH = PROJECT_ROOT / "config" / "atlas.example.toml"
USER_SETTINGS_PATH = DATA_ROOT / "data" / "user-settings.json"


def load_user_settings(path: Path | None = None) -> dict[str, Any]:
    """Load persistent settings written through the Atlas settings API."""
    settings_path = path or USER_SETTINGS_PATH
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        log.warning("settings.invalid_or_unreadable", path=str(settings_path))
        return {}
    return data if isinstance(data, dict) else {}


def save_user_settings(data: dict[str, Any], path: Path | None = None) -> None:
    """Atomically persist non-secret preferences and provider credentials."""
    settings_path = path or USER_SETTINGS_PATH
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = settings_path.with_suffix(settings_path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temporary.replace(settings_path)


# ---------------------------------------------------------------------------
# Config dataclass (plain dict wrapper — keeps it simple, no pydantic)
# ---------------------------------------------------------------------------

class AtlasConfig:
    """Thin typed wrapper around the parsed TOML dict.

    Access nested values with dotted helpers; falls back to sensible defaults
    so the app can always boot even with a minimal / empty config file.
    """

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self._data: dict[str, Any] = data or {}

    # -- helpers --

    def get(self, dotted_key: str, default: Any = None) -> Any:
        """Get a nested value like ``cfg.get('server.port', 8765)``."""
        keys = dotted_key.split(".")
        node: Any = self._data
        for k in keys:
            if isinstance(node, dict):
                node = node.get(k)
            else:
                return default
            if node is None:
                return default
        return node

    @property
    def raw(self) -> dict[str, Any]:
        return self._data

    # -- server --

    @property
    def server_host(self) -> str:
        return str(self.get("server.host", "0.0.0.0"))

    @property
    def server_port(self) -> int:
        return int(self.get("server.port", 8765))

    # -- models --

    @property
    def default_model(self) -> str:
        return str(self.get("models.default", "claude-sonnet-4"))

    @property
    def gateway_base_url(self) -> str:
        env = os.environ.get("ATLAS_API_BASE")
        if env:
            return env
        return str(self.get("models.gateway.base_url", "https://api.monkeyapi.net"))

    @property
    def gateway_api_key(self) -> str:
        env = os.environ.get("ATLAS_API_KEY")
        if env:
            return env
        return str(self.get("models.gateway.api_key", ""))

    @property
    def custom_models(self) -> list[dict[str, Any]]:
        return self.get("models.custom", []) or []

    # -- memory --

    @property
    def db_path(self) -> Path:
        raw = self.get("memory.db_path", "./data/atlas.db")
        p = Path(str(raw))
        if not p.is_absolute():
            p = DATA_ROOT / p
        return p

    @property
    def max_context_messages(self) -> int:
        return int(self.get("memory.max_context_messages", 50))

    # -- scheduler --

    @property
    def scheduler_enabled(self) -> bool:
        env = os.environ.get("ATLAS_SCHEDULER_ENABLED")
        if env is not None:
            return env.lower() in ("1", "true", "yes")
        return bool(self.get("scheduler.enabled", True))

    @property
    def scheduler_timezone(self) -> str:
        return str(self.get("scheduler.timezone", "Asia/Shanghai"))

    # -- notifications --

    @property
    def toast_enabled(self) -> bool:
        return bool(self.get("notifications.toast_enabled", True))

    # -- tools --

    @property
    def local_execution_permission_mode(self) -> str:
        """Return the opt-in permission policy for Atlas-owned local tools."""
        mode = str(self.get("local_execution.permission_mode", "full_access")).lower()
        return mode if mode in {"full_access", "deny"} else "full_access"

    @property
    def tools_auto_start(self) -> list[str]:
        return self.get("tools.auto_start", []) or []

    # -- logging --

    @property
    def log_level(self) -> str:
        return str(self.get("logging.level", "INFO")).upper()

    @property
    def log_format(self) -> str:
        return str(self.get("logging.format", "json"))


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def load_config(path: Path | None = None) -> AtlasConfig:
    """Load config from *path* (defaults to ``config/atlas.toml``).

    If the file doesn't exist, copy ``atlas.example.toml`` as a starting
    point and then load that.
    """
    cfg_path = path or CONFIG_PATH

    if not cfg_path.exists():
        if EXAMPLE_CONFIG_PATH.exists():
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(EXAMPLE_CONFIG_PATH, cfg_path)
            log.info("config.created_from_example", path=str(cfg_path))
        else:
            log.warning("config.not_found", path=str(cfg_path))
            return AtlasConfig()

    with open(cfg_path, "rb") as f:
        data = tomllib.load(f)

    log.info("config.loaded", path=str(cfg_path))
    return AtlasConfig(data)


# ---------------------------------------------------------------------------
# Module-level singleton (lazy)
# ---------------------------------------------------------------------------

_config: AtlasConfig | None = None


def get_config() -> AtlasConfig:
    """Return the global config singleton, loading on first call."""
    global _config
    if _config is None:
        _config = load_config()
    return _config
