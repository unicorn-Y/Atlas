"""专家模式开关与它的两份文件（``/api/expert-mode``）。"""

from __future__ import annotations

import tomllib
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from atlas import expert_mode

router = APIRouter()


class ToggleBody(BaseModel):
    enabled: bool


class FilesBody(BaseModel):
    config_text: str = ""
    instructions_text: str = ""


@router.get("/api/expert-mode")
async def get_expert_mode() -> dict[str, Any]:
    return expert_mode.status()


@router.post("/api/expert-mode/toggle")
async def toggle_expert_mode(body: ToggleBody) -> dict[str, Any]:
    expert_mode.set_enabled(body.enabled)
    return expert_mode.status()


@router.put("/api/expert-mode")
async def save_expert_mode(body: FilesBody) -> dict[str, Any]:
    try:
        expert_mode.save(body.config_text, body.instructions_text)
    except tomllib.TOMLDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"配置写法有错：{exc}") from None
    return expert_mode.status()
