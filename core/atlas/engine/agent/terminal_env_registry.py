"""Atlas-owned registry for optional terminal environment providers.

The runtime has no provider plugin loader yet. This module preserves the registry
contract for ported callers and supports scoped, in-process registrations without
depending on Hermes plugin infrastructure.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Optional

logger = logging.getLogger(__name__)

BUILTIN_BACKEND_NAMES = frozenset({
    "local", "docker", "singularity", "modal", "managed_modal",
    "daytona", "vercel_sandbox", "ssh",
})

_providers: dict[str, Any] = {}
_scoped_providers: dict[str, dict[str, Any]] = {}
_generation = 0
_scoped_generations: dict[str, int] = {}
_lock = threading.RLock()


def _scope_key(scope: Optional[str]) -> str | None:
    if scope is None:
        return None
    from atlas.engine.atlas_constants import atlas_home_key

    return atlas_home_key(scope)


def register_provider(provider: Any, *, scope: Optional[str] = None) -> None:
    global _generation
    name = getattr(provider, "name", None)
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Terminal environment provider .name must be a non-empty string")
    key = name.strip().lower()
    if key in BUILTIN_BACKEND_NAMES:
        raise ValueError(f"Terminal backend name '{name}' is reserved for a built-in backend")
    with _lock:
        scoped_key = _scope_key(scope)
        target = _providers if scoped_key is None else _scoped_providers.setdefault(scoped_key, {})
        target[key] = provider
        if scoped_key is None:
            _generation += 1
        else:
            _scoped_generations[scoped_key] = _scoped_generations.get(scoped_key, 0) + 1


def unregister_provider(name: str, *, scope: Optional[str] = None) -> None:
    global _generation
    key = name.strip().lower()
    with _lock:
        target = _providers if _scope_key(scope) is None else _scoped_providers.get(_scope_key(scope), {})
        if target.pop(key, None) is not None:
            scoped_key = _scope_key(scope)
            if scoped_key is None:
                _generation += 1
            else:
                _scoped_generations[scoped_key] = _scoped_generations.get(scoped_key, 0) + 1


def get_provider(name: str, *, scope: Optional[str] = None):
    key = name.strip().lower() if isinstance(name, str) else ""
    scoped_key = _scope_key(scope)
    with _lock:
        return (_scoped_providers.get(scoped_key, {}).get(key) if scoped_key else None) or _providers.get(key)


def list_providers(*, scope: Optional[str] = None) -> list[Any]:
    scoped_key = _scope_key(scope)
    with _lock:
        merged = dict(_providers)
        if scoped_key:
            merged.update(_scoped_providers.get(scoped_key, {}))
        return sorted(merged.values(), key=lambda provider: provider.name)


def plugin_backend_names(*, scope: Optional[str] = None) -> list[str]:
    return [provider.name.strip().lower() for provider in list_providers(scope=scope)]


def provider_flag(name: str, attr: str, default=False):
    provider = get_provider(name)
    if provider is None:
        return default
    try:
        return getattr(provider, attr, default)
    except Exception:
        logger.debug("Terminal environment provider '%s' attribute '%s' raised", name, attr, exc_info=True)
        return default


def plugin_strip_env_keys() -> frozenset:
    keys: set[str] = set()
    with _lock:
        providers = [*_providers.values(), *(p for scoped in _scoped_providers.values() for p in scoped.values())]
    for provider in providers:
        try:
            keys.update(provider.strip_env_keys)
        except Exception:
            logger.debug("Terminal environment provider strip_env_keys raised", exc_info=True)
    return frozenset(keys)


def registry_generation(*, scope: Optional[str] = None) -> tuple[int, int]:
    scoped_key = _scope_key(scope)
    with _lock:
        return _generation, _scoped_generations.get(scoped_key, 0) if scoped_key else 0


def snapshot_registration(name: str, *, scope: Optional[str] = None):
    key = _scope_key(scope)
    with _lock:
        return (_scoped_providers.get(key, {}) if key else _providers).get(name.strip().lower())


def restore_registration(name: str, current: Any, previous: Any, *, scope: Optional[str] = None) -> bool:
    global _generation
    key = _scope_key(scope)
    with _lock:
        target = _providers if key is None else _scoped_providers.setdefault(key, {})
        normalized = name.strip().lower()
        if target.get(normalized) is not current:
            return False
        if previous is None:
            target.pop(normalized, None)
        else:
            target[normalized] = previous
        if key is None:
            _generation += 1
        else:
            _scoped_generations[key] = _scoped_generations.get(key, 0) + 1
        return True


def _reset_for_tests() -> None:
    global _generation
    with _lock:
        _providers.clear()
        _scoped_providers.clear()
        _scoped_generations.clear()
        _generation += 1
