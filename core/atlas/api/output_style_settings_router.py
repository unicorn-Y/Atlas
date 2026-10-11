"""Persistent user-level output style preferences for new Atlas runs."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from atlas.config import load_user_settings, save_user_settings

router = APIRouter(tags=["output-style-settings"])

MAX_CUSTOM_PERSONA_CHARS = 2000
_PRESETS = {"concise", "balanced", "detailed", "custom"}


class OutputStyleSettingsUpdate(BaseModel):
    preset: Literal["concise", "balanced", "detailed", "custom"]
    custom_persona: str = Field(default="", max_length=MAX_CUSTOM_PERSONA_CHARS)


def _stored_settings(settings: dict[str, Any]) -> dict[str, str]:
    raw = settings.get("output_style")
    if not isinstance(raw, dict):
        raw = {}
    preset = raw.get("preset")
    if preset not in _PRESETS:
        preset = "balanced"
    custom_persona = raw.get("custom_persona")
    if not isinstance(custom_persona, str):
        custom_persona = ""
    return {"preset": preset, "custom_persona": custom_persona[:MAX_CUSTOM_PERSONA_CHARS]}


def _response() -> dict[str, Any]:
    return {
        **_stored_settings(load_user_settings()),
        "max_custom_persona_chars": MAX_CUSTOM_PERSONA_CHARS,
        "applies_to": "new_runs",
    }


@router.get("/api/settings/output-style")
def get_output_style_settings() -> dict[str, Any]:
    return _response()


@router.put("/api/settings/output-style")
def update_output_style_settings(payload: OutputStyleSettingsUpdate) -> dict[str, Any]:
    custom_persona = payload.custom_persona.strip()
    if payload.preset == "custom" and not custom_persona:
        raise HTTPException(status_code=422, detail="选择自定义风格时，请填写 persona 描述。")

    settings = load_user_settings()
    settings["output_style"] = {
        "preset": payload.preset,
        "custom_persona": custom_persona,
    }
    try:
        save_user_settings(settings)
    except OSError as exc:
        raise HTTPException(status_code=500, detail="无法保存输出风格设置。") from exc
    return _response()
