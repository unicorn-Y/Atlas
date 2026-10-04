"""C5 provider/model management routes (B4).

Mounted by ``atlas.server`` with a single ``app.include_router(models_router)``.
All endpoints inherit OriginGuard from the server middleware — never relax it.
Secrets only ever arrive inside a request body; they are stored in the OS
keyring and never echoed in any response, log or persisted setting.
"""

from __future__ import annotations

import time
from typing import Annotated, Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services

log = structlog.get_logger()

models_router = APIRouter()


def _mgr(services: AppServices) -> Any:
    """Resolve the ModelManager owned by this FastAPI application."""
    mgr = services.model_mgr
    assert mgr is not None, "ModelManager 尚未初始化"
    return mgr


def _catalog() -> Any:
    from atlas.models.catalog import PROVIDERS, get_provider  # B1 vendored catalog

    return PROVIDERS, get_provider


def _resolve_catalog_id(pid: str) -> str:
    """catalog id ↔ hermes provider id 双向归一（hermes id 是 catalog id 的别名）。"""
    from atlas.models.catalog import resolve_catalog_id

    return resolve_catalog_id(pid) or pid


def _provider_payload(mgr: Any, provider: dict[str, Any]) -> dict[str, Any]:
    """Catalog entry + live state. Keys carry metadata only, never the secret."""
    pid = str(provider["id"])
    config = mgr.provider_config(pid) or {}
    keys = mgr.list_keys(pid)
    return {
        **provider,
        "base_url": config.get("base_url") or provider.get("default_base_url"),
        "key_count": len(keys),
        "keys": keys,
        "api_mode_override": mgr.get_api_mode_override(pid),
        "api_mode_probe": mgr.get_api_mode_probe(pid),
        # 已配密钥或有 base_url 覆盖都算已配置。
        "configured": bool(keys) or bool(config.get("base_url")),
    }


def _require_provider(get_provider: Any, pid: str) -> dict[str, Any]:
    provider = get_provider(pid)
    if provider is None:
        raise HTTPException(status_code=404, detail=f"未知服务商：{pid}")
    return provider


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------


@models_router.get("/api/providers")
async def list_providers(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> list[dict[str, Any]]:
    """All catalog providers with per-provider base_url and key-slot state."""
    mgr = _mgr(services)
    PROVIDERS, _ = _catalog()
    return [_provider_payload(mgr, provider) for provider in PROVIDERS]


class ProviderConfigUpdateRequest(BaseModel):
    base_url: str | None = None
    api_mode_override: Literal[
        "auto", "chat_completions", "anthropic_messages", "codex_responses",
    ] | None = None


@models_router.put("/api/providers/{pid}/config")
async def update_provider_config(
    pid: str, req: ProviderConfigUpdateRequest,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    _, get_provider = _catalog()
    _require_provider(get_provider, pid)
    base_url = req.base_url
    if base_url is not None and not base_url.strip().startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="服务地址必须以 http:// 或 https:// 开头")
    mgr = _mgr(services)
    mgr.update_provider_config(pid, base_url.strip() if base_url else None)
    if "api_mode_override" in req.model_fields_set:
        mgr.set_api_mode_override(pid, req.api_mode_override)
    log.info("provider.config_updated", provider=pid)
    return {"ok": True}


class ProviderKeyCreateRequest(BaseModel):
    secret: str
    label: str = ""


@models_router.post("/api/providers/{pid}/keys", status_code=201)
async def add_provider_key(
    pid: str, req: ProviderKeyCreateRequest,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    _, get_provider = _catalog()
    _require_provider(get_provider, pid)
    secret = req.secret.strip()
    if not secret:
        raise HTTPException(status_code=422, detail="密钥内容不能为空")
    try:
        return _mgr(services).add_key(pid, secret, req.label.strip())
    except RuntimeError as exc:  # keyring 不可用等系统级失败 → 500 中文
        raise HTTPException(status_code=500, detail=str(exc) or "密钥写入系统凭据库失败") from exc


@models_router.get("/api/providers/{pid}/keys")
async def list_provider_keys(
    pid: str, services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    """密钥元数据列表（前端按 {"keys": [...]} 解析）；永不包含密钥原文。"""
    _, get_provider = _catalog()
    _require_provider(get_provider, pid)
    return {"keys": _mgr(services).list_keys(pid)}


@models_router.delete("/api/providers/{pid}/keys/{key_id}", status_code=204)
async def remove_provider_key(
    pid: str, key_id: str,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> Response:
    _, get_provider = _catalog()
    _require_provider(get_provider, pid)
    mgr = _mgr(services)
    if key_id not in {key["id"] for key in mgr.list_keys(pid)}:
        raise HTTPException(status_code=404, detail=f"未知密钥：{key_id}")
    mgr.remove_key(pid, key_id)
    log.info("provider.key_removed", provider=pid)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Custom model editing (M6)
# ---------------------------------------------------------------------------


class CustomModelUpdateRequest(BaseModel):
    name: str | None = None
    base_url: str | None = None
    litellm_model: str | None = None
    native_model: str | None = None
    hermes_provider: str | None = None
    max_output_tokens: int | None = None
    price: dict[str, Any] | None = None
    capabilities: dict[str, Any] | None = None


@models_router.put("/api/models/custom/{model_id}")
async def update_custom_model(
    model_id: str, req: CustomModelUpdateRequest,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    patch = req.model_dump(exclude_unset=True)
    try:
        return _mgr(services).update_model(model_id, patch)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@models_router.delete("/api/models/custom/{model_id}", status_code=204)
async def delete_custom_model(
    model_id: str, services: Annotated[AppServices, Depends(get_app_services)],
) -> Response:
    try:
        _mgr(services).delete_model(model_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    log.info("model.deleted", model_id=model_id)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Reasoning stages (M2)
# ---------------------------------------------------------------------------


@models_router.get("/api/models/reasoning-stages")
async def get_reasoning_stages() -> dict[str, Any]:
    from atlas.models.reasoning_stages import load_stage_config

    return load_stage_config()


class ReasoningStagesUpdateRequest(BaseModel):
    enabled: bool | None = None
    planning: str | None = None
    execution: str | None = None
    verification: str | None = None


@models_router.put("/api/models/reasoning-stages")
async def update_reasoning_stages(req: ReasoningStagesUpdateRequest) -> dict[str, Any]:
    from atlas.models.reasoning_stages import load_stage_config, save_stage_config

    cfg = load_stage_config()
    for field in ("enabled", "planning", "execution", "verification"):
        value = getattr(req, field)
        if value is not None:
            cfg[field] = value
    try:
        save_stage_config(cfg)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"思考档位无效：{exc}") from exc
    return load_stage_config()


# ---------------------------------------------------------------------------
# Model connectivity test
# ---------------------------------------------------------------------------


class ModelTestRequest(BaseModel):
    model_id: str


@models_router.post("/api/models/test")
async def test_model(
    req: ModelTestRequest,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    """Probe one model with a 2-token completion through the shared model router."""
    mgr = _mgr(services)
    model = next((m for m in mgr.list_models() if m["id"] == req.model_id), None)
    if model is None:
        raise HTTPException(status_code=404, detail=f"未知模型：{req.model_id}")
    # 密钥按 hermes_provider（归一到 catalog id）解析；旧条目缺省回退 provider 字段。
    provider_id = str(model.get("hermes_provider") or model.get("provider") or "")
    provider_id = _resolve_catalog_id(provider_id)
    api_key = mgr.resolve_api_key(provider_id)
    if not api_key:
        raise HTTPException(status_code=400, detail="该模型所属服务商尚未配置可用密钥，请先添加密钥。")

    route = await mgr.model_router.resolve(req.model_id, "model_test")
    started = time.perf_counter()
    try:
        await mgr.model_router.complete(
            route,
            messages=[{"role": "user", "content": "Reply with OK."}],
            max_tokens=2,
        )
    except Exception as exc:  # noqa: BLE001 — 网关错误原样返回给 UI
        log.warning("model.test_failed", model_id=req.model_id, error=str(exc), exc_info=True)
        return {"ok": False, "latency_ms": _latency_ms(started), "error": str(exc)}
    return {"ok": True, "latency_ms": _latency_ms(started)}


def _latency_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
