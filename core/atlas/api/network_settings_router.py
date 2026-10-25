"""Local model-only proxy and CA settings.

Proxy credentials are kept in the OS credential store and never returned from
the API. These overrides only affect Atlas model HTTP clients; they do not set
process-wide proxy environment variables.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from atlas.config import load_user_settings, save_user_settings
from atlas.models.network_transport import (
    ModelNetworkSettingsError,
    _PROXY_CREDENTIAL_KEY,
    _credential_store,
    validate_ca_bundle_path,
    validate_proxy_url,
)

router = APIRouter()
_EGRESS_PROBE_URL = "https://api.ipify.org?format=json"


class ModelNetworkSettingsUpdate(BaseModel):
    proxy_url: str | None = None
    clear_proxy: bool = False
    ca_bundle_path: str | None = None
    tool_egress: dict[str, str] | None = None


def _payload() -> dict[str, Any]:
    raw = load_user_settings().get("model_network") or {}
    raw = raw if isinstance(raw, dict) else {}
    proxy_configured = raw.get("proxy_configured") is True
    proxy_status = "not_configured"
    proxy_label = None
    if proxy_configured:
        try:
            proxy_url = _credential_store().get(_PROXY_CREDENTIAL_KEY)
        except Exception:  # noqa: BLE001 — do not expose OS credential-store details
            proxy_url = None
            proxy_status = "unavailable"
        if proxy_url:
            try:
                proxy_url = validate_proxy_url(proxy_url)
                parsed = urlsplit(proxy_url)
                host = parsed.hostname or "代理地址"
                port = f":{parsed.port}" if parsed.port else ""
                proxy_label = f"{parsed.scheme}://{host}{port}"
                proxy_status = "configured"
            except ModelNetworkSettingsError:
                proxy_status = "unavailable"
        elif proxy_status != "unavailable":
            proxy_status = "missing"
    return {
        "proxy_configured": proxy_configured,
        "proxy_status": proxy_status,
        "proxy_label": proxy_label,
        "ca_bundle_path": raw.get("ca_bundle_path") or "",
        "restart_required": True,
        "supported_transports": ["OpenAI-compatible HTTPX", "Anthropic Messages HTTPX"],
        "unsupported_transports": ["AWS Bedrock boto3", "Google Gemini native transport"],
        "tool_egress": raw.get("tool_egress") if isinstance(raw.get("tool_egress"), dict) else {
            "model_requests": "model_proxy", "web_search": "system_proxy",
        },
        "egress_tools": ["model_requests", "web_search", "media_generation"],
    }


@router.get("/api/model-network-settings")
def get_model_network_settings() -> dict[str, Any]:
    return _payload()


@router.put("/api/model-network-settings")
def update_model_network_settings(req: ModelNetworkSettingsUpdate) -> dict[str, Any]:
    if req.clear_proxy and (req.proxy_url or "").strip():
        raise HTTPException(status_code=422, detail="清除代理时请勿同时填写新的代理地址。")
    try:
        proxy_url = validate_proxy_url(req.proxy_url) if (req.proxy_url or "").strip() else None
        ca_bundle_path = validate_ca_bundle_path(req.ca_bundle_path) if req.ca_bundle_path is not None else None
    except ModelNetworkSettingsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    settings = load_user_settings()
    network = settings.get("model_network")
    if not isinstance(network, dict):
        network = {}
    if req.tool_egress is not None:
        allowed_tools = {"model_requests", "web_search", "media_generation"}
        allowed_modes = {"system_proxy", "model_proxy", "direct"}
        invalid = {key: value for key, value in req.tool_egress.items()
                   if key not in allowed_tools or value not in allowed_modes}
        if invalid:
            raise HTTPException(status_code=422, detail="出网配置仅支持 model_requests / web_search 和 system_proxy / model_proxy / direct。")
        previous_modes = network.get("tool_egress") if isinstance(network.get("tool_egress"), dict) else {}
        network["tool_egress"] = {**previous_modes, **req.tool_egress}

    store = _credential_store()
    previous_proxy_configured = network.get("proxy_configured") is True
    try:
        previous_proxy = store.get(_PROXY_CREDENTIAL_KEY) if previous_proxy_configured else None
    except Exception:  # noqa: BLE001 — replacement/clear can still repair an unreadable setting
        previous_proxy = None
    proxy_changed = False
    try:
        if req.clear_proxy:
            store.delete(_PROXY_CREDENTIAL_KEY)
            network["proxy_configured"] = False
            proxy_changed = True
        elif proxy_url:
            store.set(_PROXY_CREDENTIAL_KEY, proxy_url)
            network["proxy_configured"] = True
            proxy_changed = True
    except Exception as exc:  # noqa: BLE001 — proxy credentials must not fall back to plaintext
        raise HTTPException(status_code=500, detail="无法将代理地址安全写入系统凭据库。") from exc

    if req.ca_bundle_path is not None:
        if ca_bundle_path:
            network["ca_bundle_path"] = ca_bundle_path
        else:
            network.pop("ca_bundle_path", None)
    settings["model_network"] = network
    try:
        save_user_settings(settings)
    except OSError as exc:
        if proxy_changed:
            try:
                if previous_proxy:
                    store.set(_PROXY_CREDENTIAL_KEY, previous_proxy)
                else:
                    store.delete(_PROXY_CREDENTIAL_KEY)
            except Exception:  # noqa: BLE001 — retain the original save failure
                pass
        raise HTTPException(status_code=500, detail="无法保存模型网络设置。") from exc
    return _payload()


@router.post("/api/model-network-settings/probe")
def probe_tool_egress(req: dict[str, Any]) -> dict[str, Any]:
    """Explicitly check the public egress IP for a supported tool route."""
    tool = str(req.get("tool") or "")
    if tool not in {"model_requests", "web_search", "media_generation"}:
        raise HTTPException(status_code=422, detail="未知出网目标。")
    settings = load_user_settings().get("model_network") or {}
    settings = settings if isinstance(settings, dict) else {}
    modes = settings.get("tool_egress") if isinstance(settings.get("tool_egress"), dict) else {}
    mode = str(modes.get(tool) or ("model_proxy" if tool == "model_requests" else "system_proxy"))
    try:
        import httpx
        if mode == "model_proxy":
            from atlas.models.network_transport import build_model_httpx_client, load_model_network_settings
            network = load_model_network_settings(tool)
            if not network.proxy_url:
                raise HTTPException(status_code=409, detail="尚未配置模型代理。")
            client = build_model_httpx_client(network, base_url="https://api.ipify.org", async_mode=False, timeout=httpx.Timeout(8.0))
        else:
            client = httpx.Client(timeout=8.0, trust_env=mode == "system_proxy")
        with client:
            response = client.get(_EGRESS_PROBE_URL, follow_redirects=False)
            response.raise_for_status()
            address = response.json().get("ip")
            if not isinstance(address, str):
                raise ValueError("IP 探测服务返回格式无效")
        return {"tool": tool, "mode": mode, "ok": True, "public_ip": address}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — do not echo proxy credentials
        raise HTTPException(status_code=502, detail=f"出网探测失败：{type(exc).__name__}") from exc

