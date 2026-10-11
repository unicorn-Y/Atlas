"""Atlas-scoped proxy and CA settings for model HTTP transports.

The settings are stored locally; proxy credentials live in the OS credential
store. Transport overrides are carried by a ContextVar and applied only while
Atlas constructs or runs a model agent/call. The Hermes builders are wrapped
at runtime so plugins, updates, and other ordinary network traffic keep their
own transport policy.

The adapters wrap Hermes' model-client construction seams
(``agent.process_bootstrap.build_keepalive_http_client`` and
``agent.anthropic_adapter._new_sdk_client``). HTTPX accepts explicit ``proxy``
and ``verify`` options (https://www.python-httpx.org/advanced/proxies/); Python
SSL contexts load the configured PEM bundle for certificate verification.
"""

from __future__ import annotations

import hashlib
import json
import ssl
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlsplit

from atlas.config import load_user_settings

_PROXY_CREDENTIAL_KEY = "atlas.model_network.proxy_url"
_ACTIVE_SETTINGS: ContextVar["ModelNetworkSettings | None"] = ContextVar(
    "atlas_model_network_settings", default=None,
)
_PATCH_LOCK = threading.Lock()
_PATCHED = False


class ModelNetworkSettingsError(ValueError):
    """A persisted model-network setting is invalid or cannot be loaded."""


@dataclass(frozen=True)
class ModelNetworkSettings:
    proxy_url: str | None = field(default=None, repr=False)
    ca_bundle_path: str | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.proxy_url or self.ca_bundle_path)


def validate_proxy_url(value: str) -> str:
    candidate = str(value or "").strip()
    if not candidate or any(ch.isspace() or ord(ch) < 32 for ch in candidate):
        raise ModelNetworkSettingsError("代理地址不能为空，也不能包含空白字符。")
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError as exc:
        raise ModelNetworkSettingsError("代理地址格式无效，请检查端口号。") from exc
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ModelNetworkSettingsError("代理地址必须是有效的 http:// 或 https:// URL。")
    if parsed.fragment:
        raise ModelNetworkSettingsError("代理地址不能包含 #fragment。")
    if port is not None and not (1 <= port <= 65535):
        raise ModelNetworkSettingsError("代理端口必须在 1 到 65535 之间。")
    try:
        import httpx

        httpx.Proxy(candidate)
    except Exception as exc:  # noqa: BLE001 — normalize HTTPX URL/parser errors for the settings API
        raise ModelNetworkSettingsError("代理地址不是有效的 HTTPX 代理 URL。") from exc
    return candidate


def validate_ca_bundle_path(value: str | None) -> str | None:
    candidate = str(value or "").strip()
    if not candidate:
        return None
    path = Path(candidate).expanduser()
    try:
        resolved = path.resolve(strict=True)
        if not resolved.is_file():
            raise ModelNetworkSettingsError("CA bundle 必须指向一个文件。")
        if resolved.stat().st_size > 5 * 1024 * 1024:
            raise ModelNetworkSettingsError("CA bundle 不能大于 5 MiB。")
        contents = resolved.read_bytes()
        if b"-----BEGIN CERTIFICATE-----" not in contents:
            raise ModelNetworkSettingsError("CA bundle 必须包含 PEM 格式的证书。")
        ssl.create_default_context(cafile=str(resolved))
    except ModelNetworkSettingsError:
        raise
    except (OSError, ssl.SSLError, ValueError) as exc:
        raise ModelNetworkSettingsError("无法读取或解析此 CA bundle；请检查路径和 PEM 证书内容。") from exc
    return str(resolved)


def _credential_store() -> Any:
    from atlas.telegram import KeyringCredentialStore

    return KeyringCredentialStore()


def load_model_network_settings() -> ModelNetworkSettings:
    raw = load_user_settings().get("model_network") or {}
    if not isinstance(raw, dict):
        raise ModelNetworkSettingsError("模型网络设置格式无效，请在设置中重新保存。")
    proxy_url: str | None = None
    if raw.get("proxy_configured") is True:
        try:
            proxy_url = _credential_store().get(_PROXY_CREDENTIAL_KEY)
        except Exception as exc:  # noqa: BLE001 — fail closed; never bypass configured proxy
            raise ModelNetworkSettingsError("系统凭据库无法读取模型代理设置。") from exc
        if not proxy_url:
            raise ModelNetworkSettingsError("模型代理凭据缺失；请在设置中重新填写或清除代理。")
        proxy_url = validate_proxy_url(proxy_url)
    try:
        ca_bundle_path = validate_ca_bundle_path(raw.get("ca_bundle_path"))
    except ModelNetworkSettingsError as exc:
        raise ModelNetworkSettingsError(f"已保存的 CA bundle 无效：{exc}") from exc
    return ModelNetworkSettings(proxy_url=proxy_url, ca_bundle_path=ca_bundle_path)


def network_settings_fingerprint(settings: ModelNetworkSettings) -> str:
    payload = json.dumps(
        {"proxy_url": settings.proxy_url, "ca_bundle_path": settings.ca_bundle_path},
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:20]


def assert_transport_supported(
    settings: ModelNetworkSettings, *, provider: str, api_mode: str,
) -> None:
    """Reject transports outside the HTTPX client hooks rather than silently bypassing settings."""
    if not settings.enabled:
        return
    provider_id = str(provider or "").strip().lower()
    if provider_id in {"bedrock"} or api_mode == "bedrock_converse":
        raise ModelNetworkSettingsError(
            "当前启用了模型代理/CA 设置，但 AWS Bedrock 使用独立的 boto3 transport，尚不支持这些设置；"
            "请关闭模型代理/CA 设置，或改用 HTTPX 模型端点。"
        )
    if provider_id in {"google", "gemini", "google-gemini", "google-ai-studio"} and api_mode != "openai":
        raise ModelNetworkSettingsError(
            "当前启用了模型代理/CA 设置，但 Google Gemini 使用独立的原生 transport，尚不支持这些设置；"
            "请关闭模型代理/CA 设置，或改用 HTTPX 模型端点。"
        )


def _verify_for(settings: ModelNetworkSettings, base_url: str, fallback: Any = True) -> Any:
    if not settings.ca_bundle_path:
        return fallback
    from agent.ssl_verify import resolve_httpx_verify

    return resolve_httpx_verify(ca_bundle=settings.ca_bundle_path, base_url=base_url)


def _new_scoped_http_client(
    *, base_url: str, settings: ModelNetworkSettings, verify: Any, async_mode: bool,
    timeout: Any = None,
) -> Any:
    import httpx

    kwargs: dict[str, Any] = {
        "verify": verify,
        "timeout": timeout or httpx.Timeout(connect=15.0, read=None, write=15.0, pool=10.0),
        "limits": httpx.Limits(max_keepalive_connections=20, max_connections=100, keepalive_expiry=20.0),
        "trust_env": True,
    }
    if settings.proxy_url:
        kwargs["proxy"] = settings.proxy_url
    client_type = httpx.AsyncClient if async_mode else httpx.Client
    return client_type(**kwargs)


def build_model_httpx_client(
    settings: ModelNetworkSettings, *, base_url: str, async_mode: bool,
    verify: Any = True, timeout: Any = None,
) -> Any:
    """Construct an explicit model transport for Atlas-owned direct HTTP probes."""
    effective_verify = _verify_for(settings, base_url, verify)
    return _new_scoped_http_client(
        base_url=base_url, settings=settings, verify=effective_verify,
        async_mode=async_mode, timeout=timeout,
    )


def _install_hermes_adapters() -> None:
    global _PATCHED
    if _PATCHED:
        return
    with _PATCH_LOCK:
        if _PATCHED:
            return
        from agent import process_bootstrap

        original_builder = process_bootstrap.build_keepalive_http_client

        def atlas_keepalive_http_client(
            base_url: str = "", *, async_mode: bool = False, verify: Any = True,
        ) -> Any:
            settings = _ACTIVE_SETTINGS.get()
            if settings is None or not settings.enabled:
                return original_builder(base_url, async_mode=async_mode, verify=verify)
            effective_verify = _verify_for(settings, str(base_url or ""), verify)
            if not settings.proxy_url:
                return original_builder(base_url, async_mode=async_mode, verify=effective_verify)
            return _new_scoped_http_client(
                base_url=str(base_url or ""), settings=settings,
                verify=effective_verify, async_mode=async_mode,
            )

        atlas_keepalive_http_client.__wrapped__ = original_builder  # type: ignore[attr-defined]
        process_bootstrap.build_keepalive_http_client = atlas_keepalive_http_client

        # Standard Anthropic clients do not use Hermes' OpenAI keepalive builder.
        # Entra clients already provide a bearer-hook httpx.Client; patch that
        # factory separately so auth refresh hooks are preserved.
        try:
            from agent import anthropic_adapter

            original_anthropic_factory = anthropic_adapter._new_sdk_client

            def atlas_anthropic_factory(sdk: Any, kwargs: dict[str, Any], headers: dict[str, str], route: str = None) -> Any:
                settings = _ACTIVE_SETTINGS.get()
                if settings is not None and settings.enabled and "http_client" not in kwargs:
                    kwargs = dict(kwargs)
                    kwargs["http_client"] = _new_scoped_http_client(
                        base_url=str(route or kwargs.get("base_url") or ""),
                        settings=settings,
                        verify=_verify_for(settings, str(route or kwargs.get("base_url") or "")),
                        async_mode=False,
                    )
                return original_anthropic_factory(sdk, kwargs, headers, route=route)

            atlas_anthropic_factory.__wrapped__ = original_anthropic_factory  # type: ignore[attr-defined]
            anthropic_adapter._new_sdk_client = atlas_anthropic_factory
        except ImportError:
            # The adapter is only needed when native Anthropic is configured.
            pass

        try:
            from agent import azure_identity_adapter

            original_bearer_factory = azure_identity_adapter.build_bearer_http_client

            def atlas_bearer_http_client(token_provider: Any, **kwargs: Any) -> Any:
                settings = _ACTIVE_SETTINGS.get()
                if settings is not None and settings.enabled:
                    kwargs = dict(kwargs)
                    if settings.proxy_url:
                        kwargs["proxy"] = settings.proxy_url
                    kwargs["verify"] = _verify_for(settings, "")
                return original_bearer_factory(token_provider, **kwargs)

            atlas_bearer_http_client.__wrapped__ = original_bearer_factory  # type: ignore[attr-defined]
            azure_identity_adapter.build_bearer_http_client = atlas_bearer_http_client
        except ImportError:
            pass
        _PATCHED = True


@contextmanager
def model_network_scope(settings: ModelNetworkSettings) -> Iterator[None]:
    """Apply model-only transport overrides in this context and propagated worker threads."""
    if settings.enabled:
        _install_hermes_adapters()
    token = _ACTIVE_SETTINGS.set(settings)
    try:
        yield
    finally:
        _ACTIVE_SETTINGS.reset(token)

