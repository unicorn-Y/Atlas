"""Sync Atlas settings into the Hermes engine home config.yaml.

The pinned ``hermes-agent`` package reads its settings from
``$HERMES_HOME/config.yaml`` (HermesRuntime sets HERMES_HOME to
``<Atlas data>/engine``).  X2 bridges translate Atlas config sections
(``[computer_use]``, ``[browser]``) into that file so Hermes tooling picks them
up without forking its internals.  Existing keys are preserved; only the X2
managed sections are rewritten.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

MANAGED_SECTIONS = ("computer_use", "browser", "auxiliary")


def hermes_home() -> Path:
    home = os.environ.get("HERMES_HOME")
    if home:
        return Path(home).expanduser().resolve()
    from atlas.config import get_config

    return (get_config().db_path.parent / "engine").resolve()


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
        from hermes_cli import config as hc

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
    """Write Atlas X2 settings into the Hermes engine config.

    ``extra`` merges additional top-level sections (used by tests).  Returns
    the config path that now reflects the settings.
    """
    from atlas.config import get_config

    cfg = get_config()
    data = _load_yaml(config_file())

    data["computer_use"] = {
        "permission_mode": cfg.get("computer_use.permission_mode", "standard"),
        "no_overlay": bool(cfg.get("computer_use.no_overlay", True)),
        "cua_telemetry": bool(cfg.get("computer_use.cua_telemetry", False)),
        "ax_max_elements": cfg.get("computer_use.ax_max_elements", 200),
        "max_image_dimension": cfg.get("computer_use.max_image_dimension", 1456),
    }
    browser_mode = str(cfg.get("browser.mode", "builtin"))
    data["browser"] = {
        "mode": browser_mode,
        "use_real_profile": browser_mode == "real_profile",
        "cdp_url": cfg.get("browser.cdp_url", "") or "",
        "headed": bool(cfg.get("browser.headed", False)),
        "engine": cfg.get("browser.engine", "auto"),
        "inactivity_timeout": cfg.get("browser.inactivity_timeout", 600),
        "snapshot_threshold": cfg.get("browser.snapshot_threshold", 15000),
        "dialog_policy": cfg.get("browser.dialog_policy", "must_respond"),
        "extension_control": {
            "enabled": browser_mode == "extension",
        },
    }
    data["auxiliary"] = {"vision": _aux_vision_section()}

    if extra:
        for key, value in extra.items():
            if isinstance(value, dict) and isinstance(data.get(key), dict):
                data[key].update(value)
            else:
                data[key] = value

    _write_yaml(config_file(), data)
    _invalidate_hermes_config_cache()
    return config_file()
