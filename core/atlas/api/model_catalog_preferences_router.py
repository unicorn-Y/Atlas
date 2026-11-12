"""Persist display preferences for the currently configured Atlas model catalog.

Preferences are keyed by model IDs that the live ModelManager recognizes. Stale
IDs are ignored on reads and rejected on writes; this router never invents or
registers model entries.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from atlas.config import load_user_settings, save_user_settings

router = APIRouter(tags=["model-catalog-preferences"])


class ModelCatalogPreferencesUpdate(BaseModel):
    hidden_ids: list[str]
    pinned_ids: list[str]
    order_ids: list[str]


def _model_manager(services: AppServices) -> Any:
    model_mgr = services.model_mgr
    if model_mgr is None:
        from atlas import server as _atlas_server

        model_mgr = _atlas_server.model_mgr
    if model_mgr is None:
        raise HTTPException(status_code=503, detail="模型目录尚未就绪")
    return model_mgr


def _catalog_rows(source_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in source_rows:
        model_id = item.get("id")
        if not isinstance(model_id, str) or not model_id or model_id in seen:
            continue
        seen.add(model_id)
        rows.append({
            "id": model_id,
            "name": str(item.get("name") or model_id),
            "provider": str(item.get("provider") or ""),
            "category": str(item.get("category") or ""),
            "atlas_provider": str(item.get("atlas_provider") or ""),
            "custom": item.get("custom") is True,
            "selected": item.get("selected") is True,
        })
    return rows


def _catalog(model_mgr: Any) -> list[dict[str, Any]]:
    return _catalog_rows(model_mgr.list_models())


def _saved_preferences(model_ids: list[str]) -> dict[str, list[str]]:
    raw_settings = load_user_settings().get("model_catalog_preferences")
    raw_settings = raw_settings if isinstance(raw_settings, dict) else {}
    valid = set(model_ids)

    def clean(name: str) -> list[str]:
        raw = raw_settings.get(name)
        if not isinstance(raw, list):
            return []
        result: list[str] = []
        seen: set[str] = set()
        for value in raw:
            if isinstance(value, str) and value in valid and value not in seen:
                result.append(value)
                seen.add(value)
        return result

    ordered = clean("order_ids")
    ordered.extend(model_id for model_id in model_ids if model_id not in set(ordered))
    return {
        "hidden_ids": clean("hidden_ids"),
        "pinned_ids": clean("pinned_ids"),
        "order_ids": ordered,
    }


def _payload(
    model_mgr: Any,
    *,
    q: str = "",
    provider: str = "",
    category: str = "",
    visibility: Literal["all", "visible", "hidden"] = "all",
) -> dict[str, Any]:
    source_rows = model_mgr.list_models()
    catalog = _catalog_rows(source_rows)
    sources = {row.get("id"): row for row in source_rows if isinstance(row.get("id"), str)}
    model_ids = [item["id"] for item in catalog]
    preferences = _saved_preferences(model_ids)
    hidden = set(preferences["hidden_ids"])
    pinned = set(preferences["pinned_ids"])
    order_rank = {model_id: index for index, model_id in enumerate(preferences["order_ids"])}
    catalog.sort(key=lambda item: (item["id"] not in pinned, order_rank.get(item["id"], len(order_rank))))

    query = q.strip().casefold()
    provider_filter = provider.strip().casefold()
    category_filter = category.strip().casefold()
    filtered = []
    for item in catalog:
        is_hidden = item["id"] in hidden
        if (visibility == "visible" and is_hidden) or (visibility == "hidden" and not is_hidden):
            continue
        if provider_filter and item["provider"].casefold() != provider_filter:
            continue
        if category_filter and item["category"].casefold() != category_filter:
            continue
        if query:
            source = sources.get(item["id"], {})
            searchable = " ".join(str(source.get(key) or "") for key in (
                "id", "name", "provider", "category", "atlas_provider", "native_model", "litellm_model",
            )).casefold()
            if query not in searchable:
                continue
        filtered.append({**item, "hidden": is_hidden, "pinned": item["id"] in pinned})

    providers = sorted({item["provider"] for item in catalog if item["provider"]})
    categories = sorted({item["category"] for item in catalog if item["category"]})
    return {
        "models": filtered,
        "preferences": preferences,
        "providers": providers,
        "categories": categories,
    }


@router.get("/api/model-catalog/preferences")
def get_model_catalog_preferences(
    services: Annotated[AppServices, Depends(get_app_services)],
    q: Annotated[str, Query(max_length=160)] = "",
    provider: Annotated[str, Query(max_length=160)] = "",
    category: Annotated[str, Query(max_length=160)] = "",
    visibility: Literal["all", "visible", "hidden"] = "all",
) -> dict[str, Any]:
    return _payload(_model_manager(services), q=q, provider=provider, category=category, visibility=visibility)


@router.put("/api/model-catalog/preferences")
def update_model_catalog_preferences(
    req: ModelCatalogPreferencesUpdate,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    model_mgr = _model_manager(services)
    catalog = _catalog(model_mgr)
    model_ids = [item["id"] for item in catalog]
    valid = set(model_ids)

    def validate_ids(name: str, values: list[str]) -> list[str]:
        if any(not value or value.strip() != value for value in values):
            raise HTTPException(status_code=422, detail=f"{name} 只接受非空且无首尾空格的模型 ID")
        if len(set(values)) != len(values):
            raise HTTPException(status_code=422, detail=f"{name} 不可包含重复模型 ID")
        unknown = [value for value in values if value not in valid]
        if unknown:
            raise HTTPException(status_code=409, detail="模型目录已变化或 ID 不存在，请刷新目录后重试")
        return values

    hidden_ids = validate_ids("hidden_ids", req.hidden_ids)
    pinned_ids = validate_ids("pinned_ids", req.pinned_ids)
    order_ids = validate_ids("order_ids", req.order_ids)
    if len(order_ids) != len(model_ids) or set(order_ids) != valid:
        raise HTTPException(status_code=409, detail="排序必须覆盖当前模型目录中的每个模型，请刷新目录后重试")

    settings = load_user_settings()
    settings["model_catalog_preferences"] = {
        "version": 1,
        "hidden_ids": hidden_ids,
        "pinned_ids": pinned_ids,
        "order_ids": order_ids,
    }
    try:
        save_user_settings(settings)
    except OSError as exc:
        raise HTTPException(status_code=500, detail="无法保存模型目录偏好") from exc
    return _payload(model_mgr)
