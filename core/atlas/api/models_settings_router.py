"""Model catalog and provider settings surface (``/api/models, /api/settings, /api/images``), moved mechanically from atlas.server (H5).

Handlers resolve their services from ``app.state`` through FastAPI dependency
injection — never a module-level singleton — so two app instances stay isolated.
"""

from __future__ import annotations

from typing import Annotated, Any

import httpx
import structlog

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from atlas.config import get_config, load_user_settings, save_user_settings

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services

router = APIRouter()
log = structlog.get_logger(__name__)


@router.get("/api/models/service-tier")
def get_model_service_tier() -> dict[str, Any]:
    settings = load_user_settings()
    return {"fast_enabled": settings.get("fast_mode") is True}


@router.put("/api/models/service-tier")
def set_model_service_tier(req: dict[str, Any]) -> dict[str, Any]:
    value = req.get("fast_enabled")
    if not isinstance(value, bool):
        raise HTTPException(status_code=422, detail="fast_enabled must be a boolean")
    settings = load_user_settings()
    settings["fast_mode"] = value
    save_user_settings(settings)
    return {"fast_enabled": value}


@router.get("/api/models/fallback")
async def get_fallback_chain(services: Annotated[AppServices, Depends(get_app_services)]) -> dict[str, Any]:
    model_mgr = _resolved_model_mgr(services)
    models = [str(item.get("id")) for item in model_mgr.list_models() if item.get("id")]
    settings = load_user_settings()
    chain = settings.get("fallback_chain", [])
    if not isinstance(chain, list):
        chain = []
    return {"models": models, "chain": [item for item in chain if item in models]}


@router.put("/api/models/fallback")
async def set_fallback_chain(
    services: Annotated[AppServices, Depends(get_app_services)], req: dict[str, Any],
) -> dict[str, Any]:
    model_mgr = _resolved_model_mgr(services)
    configured = {str(item.get("id")) for item in model_mgr.list_models() if item.get("id")}
    chain = req.get("chain")
    if not isinstance(chain, list) or any(not isinstance(item, str) for item in chain):
        raise HTTPException(status_code=400, detail="chain must be a list of model ids")
    chain = list(dict.fromkeys(item for item in chain if item != model_mgr.current_model))
    unknown = [item for item in chain if item not in configured]
    if unknown:
        raise HTTPException(status_code=400, detail=f"unknown fallback models: {', '.join(unknown)}")
    settings = load_user_settings()
    settings["fallback_chain"] = chain
    save_user_settings(settings)
    return {"status": "ok", "chain": chain}


def _server() -> Any:
    """Late-bound atlas.server: its module globals stay the seam tests patch
    (``load_user_settings``/``save_user_settings`` are monkeypatched there)."""
    import atlas.server

    return atlas.server


class ModelListResponse(BaseModel):
    models: list[dict[str, Any]]
    current: str


class ModelSelectRequest(BaseModel):
    model: str


class ProviderSettingsRequest(BaseModel):
    gateway_base_url: str | None = None
    api_key: str | None = None
    compression_model: str | None = None
    memory_model: str | None = None
    subagents_enabled: bool | None = None
    subagent_default_model: str | None = None
    subagent_max_concurrent: int | None = None


class CustomModelRequest(BaseModel):
    id: str
    name: str
    provider: str
    litellm_model: str
    prompt_cache: str | None = None
    prompt_cache_ttl: str | None = None
    max_output_tokens: int | None = None
    price: dict[str, Any] | None = None


class ConnectionTestRequest(BaseModel):
    model: str | None = None


def _annotate_models(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach the reasoning-capability flag every model payload must carry.

    Both ``/api/models`` and ``/api/settings/configuration`` feed the composer, and the
    renderer only shows the reasoning switcher when this flag is present. Annotating in
    one place keeps the two surfaces from disagreeing.
    """
    for item in models:
        item["supports_reasoning_effort"] = _model_supports_reasoning(item)
    return models


@router.get("/api/models")
async def list_models(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> ModelListResponse:
    """Return available models and currently selected one."""
    model_mgr = services.model_mgr
    if model_mgr is None:
        from atlas import server as _atlas_server

        model_mgr = _atlas_server.model_mgr
    assert model_mgr is not None
    models = _annotate_models(model_mgr.list_models())
    return ModelListResponse(
        models=models,
        current=model_mgr.current_model,
    )


def _model_supports_reasoning(model: dict[str, Any]) -> bool:
    """Whether the composer should offer a thinking switch for this model.

    A model that declares ``reasoning_effort`` at all is controllable: the field exists
    precisely to turn thinking on or off, so "off" as a default must not read as "this
    model cannot think" (that mistake hid the switch entirely).
    """
    capabilities = model.get("capabilities")
    caps = capabilities if isinstance(capabilities, dict) else {}

    if model.get("reasoning_effort") or caps.get("reasoning_effort"):
        return True
    if "supports_reasoning" in caps:
        return bool(caps["supports_reasoning"])
    if "supports_reasoning" in model:
        return bool(model["supports_reasoning"]) or bool(model.get("reasoning_efforts"))

    model_name = str(model.get("litellm_model", model.get("id", ""))).lower()
    if any(keyword in model_name for keyword in ("deepseek", "r1", "gemini-2", "gemini-3", "o1", "o3", "o4", "reason", "thinking")):
        return True

    efforts = model.get("reasoning_efforts")
    if isinstance(efforts, list) and efforts:
        return True

    try:
        from litellm import get_supported_openai_params
        provider = model.get("provider")
        params = get_supported_openai_params(model=model_name, custom_llm_provider=provider)
        return isinstance(params, list) and "reasoning_effort" in params
    except (ImportError, AttributeError, KeyError, TypeError, ValueError):
        return False


@router.post("/api/models/select")
async def select_model(
    services: Annotated[AppServices, Depends(get_app_services)],
    req: ModelSelectRequest,
) -> dict[str, str]:
    """Switch the active model."""
    model_mgr = services.model_mgr
    if model_mgr is None:
        from atlas import server as _atlas_server

        model_mgr = _atlas_server.model_mgr
    assert model_mgr is not None
    try:
        model_mgr.select(req.model)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok", "model": model_mgr.current_model}


@router.get("/api/settings/configuration")
async def get_configuration(
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    return _configuration_payload(_resolved_model_mgr(services))


def _resolved_model_mgr(services: AppServices):
    model_mgr = services.model_mgr
    if model_mgr is None:
        from atlas import server as _atlas_server

        model_mgr = _atlas_server.model_mgr
    assert model_mgr is not None
    return model_mgr


def _configuration_payload(model_mgr) -> dict[str, Any]:
    settings = _server().load_user_settings()
    return {
        "gateway_base_url": model_mgr.gateway_base_url,
        "gateway_source": getattr(model_mgr, "gateway_source", ""),
        "atlas_toml_gateway_base_url": getattr(model_mgr, "atlas_toml_gateway_base_url", ""),
        "api_key_configured": model_mgr.api_key_configured,
        "models": _annotate_models(model_mgr.list_models()),
        "current": model_mgr.current_model,
        "compression_model": str(settings.get("compression_model", "")),
        "memory_model": str(settings.get("memory_model", "")),
        "subagents_enabled": (
            settings.get("subagents_enabled")
            if isinstance(settings.get("subagents_enabled"), bool) else True
        ),
        "subagent_default_model": str(settings.get("subagent_default_model") or ""),
        "subagent_max_concurrent": _subagent_max_concurrent(settings),
    }


def _subagent_max_concurrent(settings: dict[str, Any]) -> int:
    value = settings.get("subagent_max_concurrent", 8)
    return value if type(value) is int and value > 0 else 8


class ImageGenerateRequest(BaseModel):
    prompt: str
    model: str = "gpt-image-1"
    size: str = "1024x1024"
    n: int = 1


@router.post("/api/images/generate")
async def generate_image(
    services: Annotated[AppServices, Depends(get_app_services)],
    req: ImageGenerateRequest,
) -> dict[str, Any]:
    """Forward an image-generation request to the configured model gateway.

    Keeps the gateway API key server-side; the renderer never sees it.
    """
    model_mgr = services.model_mgr
    if model_mgr is None:
        from atlas import server as _atlas_server

        model_mgr = _atlas_server.model_mgr
    assert model_mgr is not None
    prompt = req.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="提示词不能为空")
    base = model_mgr.gateway_base_url.rstrip("/")
    key = getattr(model_mgr, "_api_key", "") or get_config().gateway_api_key
    if not key:
        raise HTTPException(status_code=400, detail="尚未配置模型网关密钥")
    payload = {"model": req.model, "prompt": prompt, "n": max(1, min(req.n, 4)), "size": req.size}
    try:
        from atlas.models.network_transport import build_tool_httpx_client
        client = build_tool_httpx_client("media_generation", base_url=base, async_mode=True, timeout=httpx.Timeout(180))
        async with client:
            resp = await client.post(
                f"{base}/images/generations",
                headers={"Authorization": f"Bearer {key}"},
                json=payload,
            )
    except Exception as exc:  # noqa: BLE001 — gateways and clients may expose provider-specific errors
        log.exception("images.gateway_request_failed", model=req.model)
        raise HTTPException(status_code=502, detail=f"图像网关请求失败：{exc}")
    if resp.status_code >= 400:
        detail = resp.text
        try:
            error = resp.json().get("error", {})
            message = error.get("message") if isinstance(error, dict) else None
            if isinstance(message, str):
                detail = message
        except (ValueError, AttributeError, TypeError):
            detail = resp.text
        raise HTTPException(status_code=resp.status_code, detail=detail)
    data = resp.json()
    images: list[dict[str, str]] = []
    for item in data.get("data", []):
        if item.get("url"):
            images.append({"url": item["url"]})
        elif item.get("b64_json"):
            images.append({"b64": item["b64_json"]})
    return {"images": images, "model": req.model}


@router.put("/api/settings/configuration")
async def update_configuration(
    services: Annotated[AppServices, Depends(get_app_services)],
    req: ProviderSettingsRequest,
) -> dict[str, Any]:
    model_mgr = services.model_mgr
    if model_mgr is None:
        from atlas import server as _atlas_server

        model_mgr = _atlas_server.model_mgr
    assert model_mgr is not None
    base_url = (
        req.gateway_base_url.strip()
        if req.gateway_base_url is not None else model_mgr.gateway_base_url
    )
    if req.gateway_base_url is not None and not base_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="服务地址必须以 http:// 或 https:// 开头")
    if req.compression_model is not None and req.compression_model and not any(
        item.get("id") == req.compression_model for item in model_mgr.list_models()
    ):
        raise HTTPException(status_code=400, detail="压缩模型必须来自已配置的模型列表")
    if req.memory_model is not None and req.memory_model and not any(
        item.get("id") == req.memory_model for item in model_mgr.list_models()
    ):
        raise HTTPException(status_code=400, detail="记忆模型必须来自已配置的模型列表")
    api_key = req.api_key.strip() if req.api_key and req.api_key.strip() else None
    if req.gateway_base_url is not None or api_key:
        model_mgr.update_provider(base_url, api_key)
    if req.compression_model is not None or req.memory_model is not None:
        settings = _server().load_user_settings()
        if req.compression_model is not None:
            settings["compression_model"] = req.compression_model
        if req.memory_model is not None:
            settings["memory_model"] = req.memory_model
        _server().save_user_settings(settings)
    if req.subagents_enabled is not None or req.subagent_default_model is not None or req.subagent_max_concurrent is not None:
        settings = _server().load_user_settings()
        if req.subagents_enabled is not None:
            settings["subagents_enabled"] = req.subagents_enabled
        if req.subagent_default_model is not None:
            subagent_model = req.subagent_default_model.strip()
            if subagent_model and not any(
                item.get("id") == subagent_model for item in model_mgr.list_models()
            ):
                raise HTTPException(status_code=400, detail="默认子 Agent 模型必须来自已配置的模型列表")
            settings["subagent_default_model"] = subagent_model
        if req.subagent_max_concurrent is not None:
            if type(req.subagent_max_concurrent) is not int or req.subagent_max_concurrent < 1 or req.subagent_max_concurrent > 128:
                raise HTTPException(status_code=422, detail="并行子 Agent 上限必须是 1 到 128 的正整数")
            settings["subagent_max_concurrent"] = req.subagent_max_concurrent
        _server().save_user_settings(settings)
        if req.subagent_max_concurrent is not None:
            from atlas.agent.subagent_capacity import get_subagent_capacity

            await get_subagent_capacity().set_limits(max_concurrent=req.subagent_max_concurrent)
    return _configuration_payload(_resolved_model_mgr(services))


@router.post("/api/models/custom")
async def add_custom_model(
    services: Annotated[AppServices, Depends(get_app_services)],
    req: CustomModelRequest,
) -> dict[str, Any]:
    model_mgr = services.model_mgr
    if model_mgr is None:
        from atlas import server as _atlas_server

        model_mgr = _atlas_server.model_mgr
    assert model_mgr is not None
    model_id = req.id.strip()
    if not model_id or not req.provider.strip() or not req.litellm_model.strip():
        raise HTTPException(status_code=400, detail="模型 ID、提供商和 LiteLLM 模型名均为必填项")
    try:
        model_mgr.add_model({
            "id": model_id,
            "name": req.name.strip() or model_id,
            "provider": req.provider.strip(),
            "litellm_model": req.litellm_model.strip(),
            "category": "custom",
            **({"prompt_cache": req.prompt_cache} if req.prompt_cache else {}),
            **({"prompt_cache_ttl": req.prompt_cache_ttl} if req.prompt_cache_ttl else {}),
            **({"max_output_tokens": req.max_output_tokens} if req.max_output_tokens else {}),
            **({"price": req.price} if req.price else {}),
        })
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _configuration_payload(_resolved_model_mgr(services))


@router.put("/api/models/custom/{model_id}")
async def update_custom_model(
    model_id: str,
    patch: dict[str, Any],
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    model_mgr = _resolved_model_mgr(services)
    try:
        return model_mgr.update_model(model_id, patch)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/api/models/custom/{model_id}")
async def delete_custom_model(
    model_id: str,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> dict[str, Any]:
    model_mgr = _resolved_model_mgr(services)
    try:
        model_mgr.delete_model(model_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _configuration_payload(model_mgr)


@router.post("/api/settings/test-connection")
async def test_connection(
    services: Annotated[AppServices, Depends(get_app_services)],
    req: ConnectionTestRequest,
) -> dict[str, Any]:
    model_mgr = services.model_mgr
    if model_mgr is None:
        from atlas import server as _atlas_server

        model_mgr = _atlas_server.model_mgr
    assert model_mgr is not None
    selected = req.model or model_mgr.current_model
    model = next((item for item in model_mgr.list_models() if item["id"] == selected), None)
    if model is None:
        raise HTTPException(status_code=400, detail=f"Unknown model: {selected}")

    # H4: probe through the shared model router (same seam as /api/models/test),
    # so native-channel probes and credential pools apply here too — never a
    # direct litellm.acompletion from a route handler.
    try:
        route = await model_mgr.model_router.resolve(selected, "model_test")
        await model_mgr.model_router.complete(
            route,
            messages=[{"role": "user", "content": "Reply with OK."}],
            max_tokens=2,
        )
    except Exception as exc:  # noqa: BLE001 — provider SDK exceptions must reach the connection-test UI
        log.exception("models.connection_test_failed", model=selected)
        return {"ok": False, "model": selected, "message": str(exc)}
    return {"ok": True, "model": selected, "message": "模型连接测试成功。"}
