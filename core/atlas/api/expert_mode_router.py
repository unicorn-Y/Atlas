"""专家模式：开关、仓库里各项的增删改和装卸、配置覆盖层、仓库同步（``/api/expert-mode``）。

每个改动之后都调用 ``expert_mode.apply_runtime()``，让变化不重启就生效。
"""

from __future__ import annotations

import asyncio
import tomllib
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from atlas import expert_mode

router = APIRouter()


class ToggleBody(BaseModel):
    enabled: bool


class OverlayBody(BaseModel):
    config_text: str = ""


class ItemBody(BaseModel):
    text: str | None = None


class InstallBody(BaseModel):
    installed: bool


class SyncBody(BaseModel):
    prefer: Literal["local", "remote"] | None = None


async def _changed() -> dict[str, Any]:
    await expert_mode.apply_runtime()
    return await asyncio.to_thread(expert_mode.status)


def _guard(work: Any) -> Any:
    try:
        return work()
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="没有这一项") from None
    except tomllib.TOMLDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"配置写法有错：{exc}") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.get("/api/expert-mode")
async def get_expert_mode() -> dict[str, Any]:
    return await asyncio.to_thread(expert_mode.status)


@router.post("/api/expert-mode/toggle")
async def toggle_expert_mode(body: ToggleBody) -> dict[str, Any]:
    expert_mode.set_enabled(body.enabled)
    return await _changed()


@router.put("/api/expert-mode/overlay")
async def save_overlay(body: OverlayBody) -> dict[str, Any]:
    _guard(lambda: expert_mode.save_overlay(body.config_text))
    return await _changed()


@router.get("/api/expert-mode/items/{kind}/{name}")
async def read_item(kind: str, name: str) -> dict[str, Any]:
    return _guard(lambda: expert_mode.read_item(kind, name))


@router.post("/api/expert-mode/items/{kind}/{name}", status_code=201)
async def create_item(kind: str, name: str, body: ItemBody) -> dict[str, Any]:
    _guard(lambda: expert_mode.create_item(kind, name, body.text))
    return await _changed()


@router.put("/api/expert-mode/items/{kind}/{name}")
async def save_item(kind: str, name: str, body: ItemBody) -> dict[str, Any]:
    _guard(lambda: expert_mode.save_item(kind, name, body.text or ""))
    return await _changed()


@router.delete("/api/expert-mode/items/{kind}/{name}")
async def delete_item(kind: str, name: str) -> dict[str, Any]:
    _guard(lambda: expert_mode.delete_item(kind, name))
    return await _changed()


@router.post("/api/expert-mode/items/{kind}/{name}/install")
async def install_item(kind: str, name: str, body: InstallBody) -> dict[str, Any]:
    _guard(lambda: expert_mode.set_installed(kind, name, body.installed))
    return await _changed()


@router.post("/api/expert-mode/sync")
async def sync_pack(body: SyncBody) -> dict[str, Any]:
    try:
        result = await asyncio.to_thread(expert_mode.sync, body.prefer)
    except Exception as exc:  # noqa: BLE001 — git 的各种失败原样告诉用户
        raise HTTPException(status_code=502, detail=f"同步失败：{exc}") from None
    return {"result": result, "status": await _changed()}


@router.post("/api/expert-mode/open")
async def open_folder(kind: str = "", name: str = "") -> dict[str, str]:
    return {"path": _guard(lambda: expert_mode.open_folder(kind, name))}
