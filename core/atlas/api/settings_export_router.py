"""Safe, versioned transfer of portable Atlas user preferences.

Only non-secret settings with a known Atlas schema are serialized. Provider
credentials, endpoints, paths, installed extensions and arbitrary user-settings
keys are deliberately kept local.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from atlas.config import load_user_settings, save_user_settings
from atlas.models.reasoning_effort import EFFORT_LADDER

router = APIRouter()

_FORMAT = "atlas-settings"
_VERSION = 1
_ALLOWED_KEYS = frozenset({
    "selected_model",
    "compression_model",
    "memory_model",
    "subagents_enabled",
    "subagent_default_model",
    "subagent_max_concurrent",
    "reasoning_stages",
})
_MODEL_PREFERENCE_KEYS = frozenset({
    "selected_model",
    "compression_model",
    "memory_model",
    "subagent_default_model",
})
_MAX_DOCUMENT_BYTES = 64 * 1024


class SettingsDocument(BaseModel):
    format: Literal["atlas-settings"]
    version: Literal[1]
    settings: dict[str, Any]
    exported_at: str | None = Field(default=None, max_length=64)

    class Config:
        extra = "forbid"


class ImportPreviewRequest(BaseModel):
    document: SettingsDocument

    class Config:
        extra = "forbid"


class ImportApplyRequest(BaseModel):
    document: SettingsDocument
    preview_hash: str = Field(min_length=64, max_length=64)

    class Config:
        extra = "forbid"


def _server() -> Any:
    import atlas.server

    return atlas.server


def _resolved_model_mgr(services: AppServices) -> Any:
    model_mgr = services.model_mgr
    if model_mgr is None:
        model_mgr = getattr(_server(), "model_mgr", None)
    if model_mgr is None:
        raise HTTPException(status_code=503, detail="模型配置暂不可用")
    return model_mgr


def _model_ids(model_mgr: Any) -> set[str]:
    try:
        return {
            str(item["id"])
            for item in model_mgr.list_models()
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
    except Exception as exc:  # noqa: BLE001 — the transfer surface must fail closed
        raise HTTPException(status_code=503, detail="无法读取本机模型列表") from exc


def _validate_settings(raw: Any, model_ids: set[str]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="settings 必须是 JSON 对象")
    unknown = sorted(set(raw) - _ALLOWED_KEYS)
    if unknown:
        raise HTTPException(status_code=400, detail=f"包含不支持的设置项：{', '.join(unknown)}")
    try:
        encoded = json.dumps(raw, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="设置内容不是有效 JSON") from exc
    if len(encoded.encode("utf-8")) > _MAX_DOCUMENT_BYTES:
        raise HTTPException(status_code=413, detail="设置文件超过 64 KiB")

    result: dict[str, Any] = {}
    for key in _MODEL_PREFERENCE_KEYS & raw.keys():
        value = raw[key]
        if not isinstance(value, str) or len(value) > 200:
            raise HTTPException(status_code=400, detail=f"{key} 必须是长度不超过 200 的字符串")
        value = value.strip()
        if key == "selected_model" and not value:
            raise HTTPException(status_code=400, detail="selected_model 不能为空")
        if value and value not in model_ids:
            raise HTTPException(status_code=400, detail="导入的模型未在本机配置")
        result[key] = value

    if "subagents_enabled" in raw:
        value = raw["subagents_enabled"]
        if not isinstance(value, bool):
            raise HTTPException(status_code=400, detail="subagents_enabled 必须是布尔值")
        result["subagents_enabled"] = value

    if "subagent_max_concurrent" in raw:
        value = raw["subagent_max_concurrent"]
        if type(value) is not int or value < 1 or value > 128:
            raise HTTPException(status_code=400, detail="subagent_max_concurrent 必须是 1 到 128 的整数")
        result["subagent_max_concurrent"] = value

    if "reasoning_stages" in raw:
        stages = raw["reasoning_stages"]
        expected = {"enabled", "planning", "execution", "verification"}
        if not isinstance(stages, dict) or set(stages) != expected:
            raise HTTPException(status_code=400, detail="reasoning_stages 字段不符合版本 1 schema")
        if not isinstance(stages["enabled"], bool):
            raise HTTPException(status_code=400, detail="reasoning_stages.enabled 必须是布尔值")
        normalized_stages: dict[str, Any] = {"enabled": stages["enabled"]}
        for phase in ("planning", "execution", "verification"):
            effort = stages[phase]
            if not isinstance(effort, str) or effort not in EFFORT_LADDER:
                raise HTTPException(status_code=400, detail=f"reasoning_stages.{phase} 档位无效")
            normalized_stages[phase] = effort
        result["reasoning_stages"] = normalized_stages

    return result


def _current_safe_settings(settings: dict[str, Any], model_ids: set[str]) -> dict[str, Any]:
    selected = {key: settings[key] for key in _ALLOWED_KEYS if key in settings}
    try:
        return _validate_settings(selected, model_ids)
    except HTTPException:
        # Legacy or stale preferences stay untouched and are not exposed in the preview.
        safe: dict[str, Any] = {}
        for key, value in selected.items():
            if key in _MODEL_PREFERENCE_KEYS and isinstance(value, str) and value in model_ids:
                safe[key] = value
            elif key == "subagents_enabled" and isinstance(value, bool):
                safe[key] = value
            elif key == "subagent_max_concurrent" and type(value) is int and 1 <= value <= 128:
                safe[key] = value
            elif key == "reasoning_stages" and isinstance(value, dict):
                try:
                    safe[key] = _validate_settings({key: value}, model_ids)[key]
                except HTTPException:
                    continue
        return safe


def _preview_hash(settings: dict[str, Any]) -> str:
    canonical = json.dumps(
        {"format": _FORMAT, "version": _VERSION, "settings": settings},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalized_document(document: SettingsDocument, model_ids: set[str]) -> dict[str, Any]:
    if document.format != _FORMAT or document.version != _VERSION:
        raise HTTPException(status_code=400, detail="不支持的配置文件格式或版本")
    return _validate_settings(document.settings, model_ids)


@router.get("/api/settings/export")
async def export_settings(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    """Export only the explicitly allowlisted portable preferences."""
    model_ids = _model_ids(_resolved_model_mgr(services))
    settings = _current_safe_settings(load_user_settings(), model_ids)
    return {
        "format": _FORMAT,
        "version": _VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "settings": settings,
    }


@router.post("/api/settings/import/preview")
async def preview_settings_import(
    req: ImportPreviewRequest,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    model_ids = _model_ids(_resolved_model_mgr(services))
    incoming = _normalized_document(req.document, model_ids)
    current = _current_safe_settings(load_user_settings(), model_ids)
    changes = [
        {
            "key": key,
            "before": current.get(key),
            "before_set": key in current,
            "after": value,
            "changed": current.get(key) != value,
        }
        for key, value in incoming.items()
    ]
    return {
        "format": _FORMAT,
        "version": _VERSION,
        "preview_hash": _preview_hash(incoming),
        "changes": changes,
        "unchanged_fields": sorted(set(current) & set(incoming) - {item["key"] for item in changes if item["changed"]}),
    }


@router.post("/api/settings/import/apply")
async def apply_settings_import(
    req: ImportApplyRequest,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    model_mgr = _resolved_model_mgr(services)
    incoming = _normalized_document(req.document, _model_ids(model_mgr))
    if len(req.preview_hash) != 64 or req.preview_hash != _preview_hash(incoming):
        raise HTTPException(status_code=409, detail="预览内容已变化，请重新预览后确认")

    if "selected_model" in incoming:
        try:
            model_mgr.select(incoming["selected_model"])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="本机无法选择导入的模型") from exc

    settings = load_user_settings()
    settings.update(incoming)
    save_user_settings(settings)
    return {
        "applied": sorted(incoming),
        "selected_model": getattr(model_mgr, "current_model", ""),
    }
