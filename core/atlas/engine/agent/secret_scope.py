"""Environment-only credential access for the narrow ported tool boundary.

Atlas' provider configuration owns persistent secrets. These helpers intentionally
do not synthesize a routed profile scope from process-global environment state.
"""
from __future__ import annotations

import os
import codecs
import re
import threading
from collections import OrderedDict
from contextvars import ContextVar, Token
from pathlib import Path
from typing import Mapping, NamedTuple, Optional

from atlas.engine.utils import file_signature


class _BoundScope(NamedTuple):
    mapping: Mapping[str, str]
    profile_home: Optional[str]


_SECRET_SCOPE: ContextVar[Optional[_BoundScope]] = ContextVar("_SECRET_SCOPE", default=None)

_GLOBAL_ENV_EXACT = frozenset({
    "ATLAS_HOME", "HERMES_HOME", "HERMES_PROFILE", "HERMES_GATEWAY_LOCK_DIR",
    "HERMES_MAX_ITERATIONS", "HERMES_API_TIMEOUT", "HERMES_REDACT_SECRETS",
    "HERMES_NOUS_TIMEOUT_SECONDS", "_HERMES_GATEWAY",
    "PATH", "HOME", "USER", "LANG", "LC_ALL", "TZ", "PWD", "SHELL", "TMPDIR",
    "VIRTUAL_ENV", "PYTHONPATH", "SSL_CERT_FILE",
    "HERMES_KANBAN_DB", "HERMES_KANBAN_WORKSPACES_ROOT", "HERMES_KANBAN_BOARD",
    "API_SERVER_ENABLED", "API_SERVER_HOST", "API_SERVER_PORT", "API_SERVER_CORS_ORIGINS",
    "GATEWAY_RELAY_URL", "GATEWAY_RELAY_ENDPOINT", "GATEWAY_RELAY_ALLOW_DIRECT_PLATFORMS",
    "GATEWAY_RELAY_PLATFORMS", "GATEWAY_RELAY_BOT_IDS", "GATEWAY_RELAY_ROUTE_KEYS",
    "GATEWAY_RELAY_INSTANCE_ID", "GATEWAY_RELAY_WAKE_URL", "GATEWAY_RELAY_DISPLAY_NAME",
})
_GLOBAL_ENV_PREFIXES = ("HERMES_KANBAN_", "HERMES_TELEGRAM_", "TERMINAL_")


def _is_global_env(name: str) -> bool:
    """True for process-global settings that are not profile credentials."""
    return name in _GLOBAL_ENV_EXACT or name.startswith(_GLOBAL_ENV_PREFIXES)


_ENV_FILE_CACHE: OrderedDict[str, tuple[tuple[int, int, int, int], dict[str, str]]] = OrderedDict()
_ENV_FILE_CACHE_LOCK = threading.Lock()
_ENV_FILE_CACHE_MAX = 64


class UnscopedSecretError(RuntimeError):
    """Raised when profile-scoped secret access has no active scope."""

    def __init__(self, secret_name: str = "", developer_detail: str = ""):
        if secret_name and not developer_detail and any(ch.isspace() for ch in secret_name):
            secret_name, developer_detail = "", secret_name
        what = f"this profile's {secret_name}" if secret_name else "this profile's API key"
        super().__init__(
            f"Atlas could not read {what} (an internal profile-scoping bug on the multiplexed "
            "gateway, not your configuration). Restart Atlas; if it keeps happening, "
            "report it with the diagnostics bundle from Settings → Diagnostics."
        )
        self.secret_name = secret_name
        self.developer_detail = developer_detail
        if developer_detail:
            self.add_note(developer_detail)


def set_secret_scope(secrets: Optional[Mapping[str, str]], *, profile_home: Optional[str] = None) -> Token:
    """Install a task-local profile secret mapping and return its reset token."""
    if secrets is None:
        return _SECRET_SCOPE.set(None)
    return _SECRET_SCOPE.set(_BoundScope(secrets, str(profile_home) if profile_home else None))


def reset_secret_scope(token: Token) -> None:
    """Restore the secret scope that was active before :func:`set_secret_scope`."""
    _SECRET_SCOPE.reset(token)


def get_secret(name: str, default=None):
    return os.environ.get(name, default)


def current_secret_scope():
    bound = _SECRET_SCOPE.get()
    return bound.mapping if bound is not None else None


def invalidate_env_file_cache(env_path: Optional[Path] = None) -> None:
    """Drop one parsed dotenv entry, or clear the full profile cache."""
    with _ENV_FILE_CACHE_LOCK:
        if env_path is None:
            _ENV_FILE_CACHE.clear()
        else:
            _ENV_FILE_CACHE.pop(str(env_path), None)


def _strip_inline_comment(value: str) -> str:
    """Strip dotenv comments while preserving hashes inside quoted or bare values."""
    value = value.strip()
    if not value:
        return value
    quote = value[0]
    if quote in ("'", '"'):
        index = 1
        while index < len(value):
            char = value[index]
            if quote == '"' and char == "\\":
                index += 2
                continue
            if char == quote:
                return value[:index + 1] if value[index + 1:].lstrip().startswith("#") else value
            index += 1
        return value
    return re.split(r"\s+#", value, maxsplit=1)[0].strip()


def _parse_env_value(raw_value: str) -> str:
    value = raw_value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        quoted = value[1:-1]
        parsed: list[str] = []
        index = 0
        while index < len(quoted):
            escaped = quoted[index] == "\\" and quoted[index + 1:index + 2] in ('"', "\\")
            parsed.append(quoted[index + 1] if escaped else quoted[index])
            index += 2 if escaped else 1
        return "".join(parsed)
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1]
    return value


def _decode_env_bytes(raw: bytes) -> str:
    raw = raw.removeprefix(codecs.BOM_UTF8)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _parse_env_text(text: str) -> dict[str, str]:
    secrets: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, separator, value = line.partition("=")
        key = key.strip()
        if separator and key:
            secrets[key] = _parse_env_value(_strip_inline_comment(value))
    return secrets


def load_env_file(env_path: Path) -> dict[str, str]:
    """Read and parse a profile dotenv file without changing process environment."""
    target = Path(env_path)
    key = str(target)
    try:
        with target.open("rb") as handle:
            signature = file_signature(os.fstat(handle.fileno()))
            with _ENV_FILE_CACHE_LOCK:
                cached = _ENV_FILE_CACHE.get(key)
                if cached is not None and cached[0] == signature:
                    _ENV_FILE_CACHE.move_to_end(key)
                    return dict(cached[1])
            raw = handle.read()
            settled = file_signature(os.fstat(handle.fileno())) == signature
    except OSError:
        invalidate_env_file_cache(target)
        return {}

    secrets = _parse_env_text(_decode_env_bytes(raw))
    if settled:
        with _ENV_FILE_CACHE_LOCK:
            _ENV_FILE_CACHE[key] = (signature, dict(secrets))
            _ENV_FILE_CACHE.move_to_end(key)
            while len(_ENV_FILE_CACHE) > _ENV_FILE_CACHE_MAX:
                _ENV_FILE_CACHE.popitem(last=False)
    return secrets


def build_profile_secret_scope(atlas_home: Path) -> dict[str, str]:
    """Read profile-local dotenv values without copying process-global variables."""
    values = load_env_file(Path(atlas_home) / ".env")
    return {key: value for key, value in values.items() if not _is_global_env(key)}


def is_multiplex_active() -> bool:
    """Return whether the current task is routed away from the process profile.

    Atlas tracks profile routing with home overrides and bound secret-scope
    provenance instead of a separate gateway process flag.
    """
    try:
        from atlas.engine.atlas_constants import (
            get_atlas_home_override,
            get_routing_process_atlas_home,
            atlas_home_key,
        )

        process_home = atlas_home_key(get_routing_process_atlas_home())
        bound = _SECRET_SCOPE.get()
        if bound is not None and bound.profile_home:
            if atlas_home_key(bound.profile_home) != process_home:
                return True
        override = get_atlas_home_override()
        return override is not None and atlas_home_key(override) != process_home
    except (OSError, RuntimeError):
        # Fail closed when routed-profile identity cannot be established.
        return True


def serves_routed_profile() -> bool:
    return is_multiplex_active()

