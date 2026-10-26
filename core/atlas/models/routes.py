"""C5 provider/model management routes (B4).

Mounted by ``atlas.server`` with a single ``app.include_router(models_router)``.
All endpoints inherit OriginGuard from the server middleware — never relax it.
Secrets only ever arrive inside a request body; they are stored in the OS
keyring and never echoed in any response, log or persisted setting.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

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


_PROVIDER_ACCOUNT_LINKS = {
    "anthropic": "https://platform.claude.com/usage",
    "deepseek": "https://platform.deepseek.com/usage",
    "google": "https://aistudio.google.com/",
    "mistral": "https://console.mistral.ai/usage/",
    "openai": "https://platform.openai.com/usage",
}


@models_router.get("/api/providers/account-usage")
async def provider_account_usage(
    services: Annotated[AppServices, Depends(get_app_services)],
    provider_id: str = "",
) -> dict[str, Any]:
    """Read official provider account balances where Atlas has a compatible key.

    This is separate from Atlas' local run ledger. It never returns key material,
    and unsupported providers remain explicitly unsupported instead of receiving
    estimated account quota values.
    """
    mgr = _mgr(services)
    PROVIDERS, get_provider = _catalog()
    requested = _resolve_catalog_id(provider_id.strip()) if provider_id.strip() else ""
    selected = get_provider(requested) if requested else None
    selected_id = str(selected["id"]) if selected else requested
    rows: list[dict[str, Any]] = []
    for provider in PROVIDERS:
        pid = str(provider["id"])
        config = mgr.provider_config(pid) or {}
        keys = config.get("keys") if isinstance(config.get("keys"), list) else []
        configured = bool(keys or config.get("base_url"))
        if not configured and pid != selected_id:
            continue
        row: dict[str, Any] = {
            "provider_id": pid,
            "label": str(provider.get("label") or pid),
            "configured": configured,
            "status": "unsupported",
            "status_text": "此服务商没有可用的只读账户余额接口，Atlas 不会估算订阅额度。",
            "account_url": _PROVIDER_ACCOUNT_LINKS.get(pid) or str(provider.get("docs_url") or ""),
            "balances": [],
            "is_available": None,
            "reset_at": None,
            "checked_at": None,
        }
        if pid == "deepseek":
            endpoint_base = str(config.get("base_url") or provider.get("default_base_url") or "")
            parsed = urlsplit(endpoint_base)
            official_direct = parsed.scheme == "https" and parsed.hostname == "api.deepseek.com"
            api_key = mgr.resolve_api_key(pid) if official_direct else None
            if not official_direct:
                row["status_text"] = "当前服务地址不是 DeepSeek 官方 API；账户余额不支持查询。"
            elif not api_key and not configured and selected_id == pid:
                row["status_text"] = "当前模型经 Atlas 网关调用；本机没有可用于 DeepSeek 官方账户查询的密钥，因此账户余额不支持 API 查询。"
            elif not api_key:
                row["status"] = "unavailable"
                row["status_text"] = "未找到可用于 DeepSeek 官方账户查询的本机 API 密钥。"
            else:
                try:
                    import httpx

                    async with httpx.AsyncClient(timeout=8.0, follow_redirects=False) as client:
                        response = await client.get(
                            "https://api.deepseek.com/user/balance",
                            headers={"Authorization": f"Bearer {api_key}"},
                        )
                    response.raise_for_status()
                    payload = response.json()
                    balances = payload.get("balance_infos") if isinstance(payload, dict) else None
                    if not isinstance(balances, list):
                        raise ValueError("DeepSeek 返回的账户余额格式无效")
                    row.update({
                        "status": "available",
                        "status_text": "DeepSeek 官方账户余额（不是 Atlas 本机用量）；官方接口未提供周期重置时间。",
                        "balances": [
                            {key: str(item[key]) for key in ("currency", "total_balance", "granted_balance", "topped_up_balance")
                             if key in item}
                            for item in balances if isinstance(item, dict)
                        ],
                        "is_available": bool(payload.get("is_available")),
                        "checked_at": datetime.now(timezone.utc).isoformat(),
                    })
                except Exception as exc:
                    status_code = getattr(getattr(exc, "response", None), "status_code", None)
                    row["status"] = "error"
                    row["status_text"] = (f"官方账户余额读取失败（HTTP {status_code}）。请检查密钥权限或稍后重试。"
                                          if status_code else "官方账户余额读取失败；请检查网络或稍后重试。")
        elif selected_id == pid and not configured:
            row["status_text"] = "当前模型走 Atlas 网关或未配置官方账号密钥，无法读取供应商账户额度。"
        rows.append(row)
    if requested and selected is None:
        rows.append({
            "provider_id": requested,
            "label": requested,
            "configured": True,
            "status": "unsupported",
            "status_text": "此服务商不在 Atlas 官方账户查询目录中；请在当前服务商控制台查看订阅和额度。",
            "account_url": "",
            "balances": [],
            "is_available": None,
            "reset_at": None,
            "checked_at": None,
        })
    return {"providers": rows, "source": "provider-official-account-api", "read_only": True}


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
