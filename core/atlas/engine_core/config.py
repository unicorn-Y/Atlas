"""Small Atlas-backed adapter for configuration helpers used by ported code.

This module reads Atlas' ``config/atlas.toml``. It deliberately does not create
configuration files, import Hermes, or expose Hermes credentials and setup.
"""

from __future__ import annotations

import copy
import getpass
import json
import os
import stat
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

# Public environment metadata kept for source-ported tools. Atlas persists model
# credentials in its own settings/keyring; these names are only used for secret
# classification and environment scrubbing.
OPTIONAL_ENV_VARS: dict[str, dict[str, Any]] = {
    name: {"password": secret, "category": "provider"}
    for name, secret in {
        "OPENAI_API_KEY": True, "OPENAI_BASE_URL": False,
        "ANTHROPIC_API_KEY": True, "ANTHROPIC_BASE_URL": False,
        "GOOGLE_API_KEY": True, "GEMINI_API_KEY": True, "GEMINI_BASE_URL": False,
        "OPENROUTER_API_KEY": True, "OPENROUTER_BASE_URL": False,
        "DEEPSEEK_API_KEY": True, "DEEPSEEK_BASE_URL": False,
        "GROQ_API_KEY": True, "GROQ_BASE_URL": False,
        "MISTRAL_API_KEY": True, "MISTRAL_BASE_URL": False,
        "XAI_API_KEY": True, "XAI_BASE_URL": False,
        "MINIMAX_API_KEY": True, "MINIMAX_BASE_URL": False,
        "DASHSCOPE_API_KEY": True, "DASHSCOPE_BASE_URL": False,
        "ZAI_API_KEY": True, "GLM_API_KEY": True, "GLM_BASE_URL": False,
        "COHERE_API_KEY": True, "TOGETHER_API_KEY": True,
        "NVIDIA_API_KEY": True, "HF_TOKEN": True,
        "GOOGLE_APPLICATION_CREDENTIALS": False,
    }.items()
}
CORE_DECLARED_ENV_NAMES: frozenset[str] = frozenset(OPTIONAL_ENV_VARS)
PLATFORM_SECRET_ENV_SUFFIXES = ("_TOKEN", "_SECRET", "_KEY", "_PASSWORD", "_JSON")

TERMINAL_CONFIG_ENV_MAP = {
    "backend": "TERMINAL_ENV",
    **{
        key: f"TERMINAL_{key.upper()}"
        for key in (
            "modal_mode", "degraded_mode", "cwd", "temp_dir", "timeout", "lifetime_seconds",
            "docker_image", "docker_forward_env", "singularity_image", "modal_image",
            "daytona_image", "vercel_runtime", "vercel_image", "ssh_host", "ssh_user",
            "ssh_port", "ssh_key", "container_cpu", "container_memory", "container_disk",
            "container_persistent", "docker_volumes", "docker_env", "docker_mount_cwd_to_workspace",
            "docker_network", "docker_extra_args", "docker_shm_size", "docker_run_as_host_user",
            "docker_snap_compat", "docker_persist_across_processes", "docker_shared_container_key",
            "docker_orphan_reaper", "sandbox_dir", "persistent_shell",
        )
    },
}


def _terminal_env_value(value: Any) -> str:
    return json.dumps(value) if isinstance(value, (list, dict)) else str(value)


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


# Every SessionDB open read this ~8k-node YAML (three times) with the pure-Python
# parser: ~150ms each, ~95% of a session read and ~0.3-0.5s before each model turn.
# Keyed on mtime + size, so an edited config.yaml is picked up on the next read.
_LEGACY_HOME_CONFIG_CACHE: dict[str, tuple[tuple[int, int], Any]] = {}
try:
    from yaml import CSafeLoader as _YAML_LOADER
except ImportError:  # libyaml (or PyYAML) missing: same parser as yaml.safe_load
    try:
        from yaml import SafeLoader as _YAML_LOADER  # type: ignore[assignment]
    except ImportError:
        _YAML_LOADER = None  # type: ignore[assignment]


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
            stamp = path.stat()
        except OSError:
            continue
        key = (stamp.st_mtime_ns, stamp.st_size)
        cached = _LEGACY_HOME_CONFIG_CACHE.get(str(path))
        if cached is None or cached[0] != key:
            try:
                value = yaml.load(path.read_text(encoding="utf-8"), Loader=_YAML_LOADER)
            except OSError:
                continue
            except yaml.YAMLError:
                return {}
            cached = (key, value)
            _LEGACY_HOME_CONFIG_CACHE[str(path)] = cached
        if isinstance(cached[1], dict):
            return copy.deepcopy(cached[1])
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


def get_env_value(key: str) -> str | None:
    """Read a scoped process secret first, then its legacy profile .env value."""
    try:
        from atlas.engine_core.agent.secret_scope import get_secret

        value = get_secret(key)
    except Exception:
        value = os.environ.get(key)
    return load_env().get(key) if value is None else value


def read_raw_config_readonly(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Read the unmerged Atlas TOML mapping without copying or modifying it."""
    return read_raw_config(path)


def _platform_manifest_paths(home: Path | None = None, source: str = "all"):
    from atlas.config import PROJECT_ROOT

    roots: list[tuple[Path, bool]] = []
    if source in ("all", "bundled"):
        roots.append((PROJECT_ROOT / "plugins" / "platforms", False))
    if source in ("all", "user"):
        user_plugins = (home or (_legacy_home() or Path.home())) / "plugins"
        roots.extend(((user_plugins / "platforms", False), (user_plugins, True)))
    for root, require_kind in roots:
        try:
            with os.scandir(root) as entries:
                directories = [entry for entry in entries if entry.is_dir()]
        except (FileNotFoundError, NotADirectoryError):
            continue
        except OSError as exc:
            yield str(root), None, require_kind, exc
            continue
        for directory in directories:
            for file_name in ("plugin.yaml", "plugin.yml"):
                path = Path(directory.path) / file_name
                try:
                    info = path.stat()
                except OSError:
                    continue
                if stat.S_ISREG(info.st_mode):
                    yield directory.name, path, require_kind, info
                    break


def _platform_plugin_manifests(home: Path | None = None, source: str = "all", *,
                               strict: bool = False, skipped: list | None = None):
    for name, path, require_kind, info in _platform_manifest_paths(home, source):
        if path is None:
            if skipped is not None:
                skipped.append(name)
            continue
        try:
            import yaml
            manifest = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
        except OSError:
            if strict and not require_kind:
                raise
            if skipped is not None:
                skipped.append(str(path))
            continue
        except Exception:
            if skipped is not None:
                skipped.append(str(path))
            continue
        if isinstance(manifest, dict) and (not require_kind or manifest.get("kind") == "platform"):
            yield name, manifest


def _manifest_secret_envs(manifests) -> frozenset[str]:
    names: set[str] = set()
    for _directory, manifest in manifests:
        entries = [*(manifest.get("requires_env") or []), *(manifest.get("optional_env") or [])]
        for entry in entries:
            item = {"name": entry} if isinstance(entry, str) else entry if isinstance(entry, dict) else {}
            name = item.get("name")
            if not isinstance(name, str) or not name:
                continue
            secret = bool(item.get("password") or item.get("secret"))
            if not secret and item.get("password") is not False:
                secret = name.upper().endswith(PLATFORM_SECRET_ENV_SUFFIXES)
            if secret and (item.get("category") or "messaging") == "messaging":
                names.add(name.upper())
    return frozenset(names - {name.upper() for name in CORE_DECLARED_ENV_NAMES})


def platform_manifest_stamp(home: Path | None = None) -> tuple:
    rows = []
    for name, path, _require_kind, info in _platform_manifest_paths(home, "user"):
        signature = ((info.st_mtime_ns, info.st_size, info.st_ino, info.st_ctime_ns)
                     if path is not None else type(info).__name__)
        rows.append((name, str(path) if path is not None else None, signature))
    return tuple(rows)


def platform_manifest_secret_envs(home: Path | None = None, source: str = "user", *,
                                  strict: bool = False) -> frozenset[str]:
    return _manifest_secret_envs(_platform_plugin_manifests(home, source, strict=strict))


def platform_manifest_secret_scan(home: Path | None = None) -> tuple[frozenset[str], bool]:
    skipped: list[str] = []
    names = _manifest_secret_envs(
        _platform_plugin_manifests(home, "user", strict=True, skipped=skipped)
    )
    return names, not skipped


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

