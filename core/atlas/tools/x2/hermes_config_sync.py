"""Compatibility shim retained for existing X2 call sites.

Atlas settings are read directly from Atlas configuration; no Hermes config
file is created or synchronized.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

MANAGED_SECTIONS = ("computer_use", "browser", "auxiliary")


def hermes_home() -> Path:
    from atlas.engine_core.hermes_constants import get_hermes_home

    return get_hermes_home()


def config_file() -> Path:
    return hermes_home() / "config.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml

        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return {}
    except Exception as exc:  # noqa: BLE001 - unreadable config must not break startup
        log.warning("x2.config_read_failed", extra={"error": str(exc)})
        return {}


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    import yaml

    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    path.write_text(text, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _invalidate_hermes_config_cache() -> None:
    try:
        from atlas.engine_core import config as hc

        for cache_name in ("_LOAD_CONFIG_CACHE", "_RAW_CONFIG_CACHE",
                           "_LAST_EXPANDED_CONFIG_BY_PATH"):
            cache = getattr(hc, cache_name, None)
            if isinstance(cache, dict):
                cache.clear()
    except Exception as exc:  # noqa: BLE001
        log.debug("x2.config_cache_invalidate_failed", extra={"error": str(exc)})


def _aux_vision_section() -> dict[str, Any]:
    """Translate Atlas vision-model settings into Hermes auxiliary.vision.

    Atlas settings (user-settings.json → model overrides, or config.toml
    ``computer_use.aux_vision_*``) decide the screenshot-describing model; it
    falls back to the main configured model.  When the main model can read
    images itself, vision_routing keeps the multimodal envelope and aux vision
    simply never fires.
    """
    from atlas.config import get_config

    cfg = get_config()
    provider = cfg.get("computer_use.aux_vision_provider", "")
    model = cfg.get("computer_use.aux_vision_model", "")
    base_url = cfg.get("computer_use.aux_vision_base_url", "")
    if provider or model or base_url:
        section: dict[str, Any] = {
            "provider": provider or "openai-compatible",
            "model": model or None,
        }
        if base_url:
            section["base_url"] = base_url
        api_key = cfg.get("computer_use.aux_vision_api_key", "")
        if api_key:
            section["api_key"] = api_key
        return section
    return {"provider": "auto", "model": "", "base_url": ""}


def sync_x2_config(extra: dict[str, Any] | None = None) -> Path:
    """Return the Atlas config path; kept for callers during the engine cutover."""
    del extra
    return config_file()
