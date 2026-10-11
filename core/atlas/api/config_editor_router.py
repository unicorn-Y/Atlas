"""设置 → 主体配置：直接查看和修改 atlas.toml、界面设置（user-settings.json），带自动备份。"""

from __future__ import annotations

import json
import time
import tomllib
from pathlib import Path
from typing import Any

import tomli_w
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from atlas import config as config_module
from atlas import expert_mode

router = APIRouter()

_KEEP_BACKUPS = 30


class TextBody(BaseModel):
    text: str


class RestoreBody(BaseModel):
    name: str


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _backup_glob(path: Path) -> list[Path]:
    return sorted(path.parent.glob(f"{path.name}.bak-*"), key=lambda p: p.name, reverse=True)


def _write_with_backup(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        stamp = time.strftime("%Y%m%d-%H%M%S")
        (path.parent / f"{path.name}.bak-{stamp}").write_bytes(path.read_bytes())
        for old in _backup_glob(path)[_KEEP_BACKUPS:]:
            old.unlink(missing_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _effective_text() -> str:
    try:
        return tomli_w.dumps(config_module.get_config().raw)
    except (TypeError, ValueError) as exc:
        return f"# 无法显示：{exc}"


def _state() -> dict[str, Any]:
    main = config_module.CONFIG_PATH
    settings = config_module.USER_SETTINGS_PATH
    return {
        "config_path": str(main),
        "config_text": _read(main),
        "settings_path": str(settings),
        "settings_text": _read(settings),
        "effective_text": _effective_text(),
        "expert_enabled": expert_mode.is_enabled(),
        "backups": [
            {"name": p.name, "kind": "config" if p.name.startswith(main.name) else "settings", "size": p.stat().st_size}
            for p in [*_backup_glob(main), *_backup_glob(settings)]
        ],
    }


@router.get("/api/config/main")
async def get_main_config() -> dict[str, Any]:
    return _state()


@router.put("/api/config/main")
async def save_main_config(body: TextBody) -> dict[str, Any]:
    try:
        tomllib.loads(body.text)
    except tomllib.TOMLDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"atlas.toml 写法有错，没有保存：{exc}") from None
    _write_with_backup(config_module.CONFIG_PATH, body.text)
    config_module.reload_config()
    return _state()


@router.put("/api/config/settings")
async def save_user_settings(body: TextBody) -> dict[str, Any]:
    try:
        data = json.loads(body.text or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"JSON 写法有错，没有保存：{exc}") from None
    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="界面设置必须是一个 JSON 对象（{ ... }）")
    _write_with_backup(config_module.USER_SETTINGS_PATH, json.dumps(data, ensure_ascii=False, indent=2))
    config_module.reload_config()
    return _state()


@router.post("/api/config/restore")
async def restore_backup(body: RestoreBody) -> dict[str, Any]:
    for target in (config_module.CONFIG_PATH, config_module.USER_SETTINGS_PATH):
        backup = target.parent / body.name
        if body.name.startswith(f"{target.name}.bak-") and "/" not in body.name and "\\" not in body.name and backup.is_file():
            _write_with_backup(target, backup.read_text(encoding="utf-8"))
            config_module.reload_config()
            return _state()
    raise HTTPException(status_code=404, detail="没有这个备份")
