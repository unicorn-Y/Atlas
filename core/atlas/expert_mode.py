"""专家模式：开着时，在普通配置之上额外叠加一份用户自己写的配置和一段附加说明。

- ``config/expert.toml``                覆盖层，和 atlas.toml 同结构，按键深度合并到普通配置上
- ``config/expert-instructions.md``     附加说明，每轮拼进系统提示词末尾
- 开关存在 ``data/user-settings.json`` 的 ``expert_mode``

两个文件都由用户自己写；关掉专家模式后普通配置原样不动。
"""

from __future__ import annotations

import copy
import tomllib
from pathlib import Path
from typing import Any

from atlas import config as _config

_SETTING_KEY = "expert_mode"


def config_path() -> Path:
    return _config.CONFIG_PATH.parent / "expert.toml"


def instructions_path() -> Path:
    return _config.CONFIG_PATH.parent / "expert-instructions.md"


def is_enabled() -> bool:
    return bool(_config.load_user_settings().get(_SETTING_KEY, False))


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def apply_overlay(data: dict[str, Any]) -> dict[str, Any]:
    """普通配置 → 专家模式开着时叠上 expert.toml 的结果；关着或文件有错时原样返回。"""
    if not is_enabled():
        return data
    text = _read(config_path())
    if not text.strip():
        return data
    try:
        overlay = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        _config.log.warning("expert_mode.overlay_invalid", path=str(config_path()))
        return data
    return deep_merge(data, overlay)


def instructions() -> str:
    """专家模式开着时的附加说明（没开或没写返回空串）。"""
    if not is_enabled():
        return ""
    return _read(instructions_path()).strip()


def _reload_config() -> None:
    _config.reload_config()


def set_enabled(enabled: bool) -> None:
    settings = _config.load_user_settings()
    settings[_SETTING_KEY] = bool(enabled)
    _config.save_user_settings(settings)
    _reload_config()


def save(config_text: str, instructions_text: str) -> None:
    if config_text.strip():
        tomllib.loads(config_text)  # 写坏了直接报错，不落盘
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(config_text, encoding="utf-8")
    instructions_path().write_text(instructions_text, encoding="utf-8")
    _reload_config()


def status() -> dict[str, Any]:
    text = _read(config_path())
    try:
        keys = sorted(tomllib.loads(text)) if text.strip() else []
        error = ""
    except tomllib.TOMLDecodeError as exc:
        keys, error = [], str(exc)
    return {
        "enabled": is_enabled(),
        "config_path": str(config_path()),
        "instructions_path": str(instructions_path()),
        "config_text": text,
        "instructions_text": _read(instructions_path()),
        "overlay_sections": keys,
        "config_error": error,
    }
