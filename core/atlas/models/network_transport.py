"""Atlas-scoped proxy and CA settings for model HTTP transports.

The settings are stored locally; proxy credentials live in the OS credential
store. Atlas applies them only to model HTTPX requests. Explicit ``proxy`` and
``verify`` options carry the configured proxy and PEM trust bundle.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
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

# A bracketed IPv6 literal inside NO_PROXY, e.g. ``[::1]``.
_BRACKETED_V6 = re.compile(r"^\[(?P<inner>[0-9A-Fa-f:.]+)\](?::(?P<port>\d+))?$")


def normalize_no_proxy_value(value: str) -> str:
    """Rewrite bracketed IPv6 entries in a ``NO_PROXY`` value to bare literals.

    curl accepts ``NO_PROXY=[::1]`` but httpx does not. httpx validates each
    entry with ``is_ipv6_hostname``, which rejects the bracketed form, so the
    entry falls through to the generic domain branch and becomes the mount key
    ``all://*[::1]``. That key is not a valid URL, and ``httpx.Client()`` raises
    ``InvalidURL: Invalid port: ':1]'`` during construction — so a single
    bracketed IPv6 entry anywhere in the user's environment makes *every* model
    request fail, before any network I/O happens. ``::1`` is the form both
    clients understand and means the same thing, so rewriting is safe.
    """
    if not value or "[" not in value:
        return value
    out: list[str] = []
    for raw in value.split(","):
        entry = raw.strip()
        if not entry:
            continue
        match = _BRACKETED_V6.match(entry)
        if match:
            port = match.group("port")
            out.append(f"{match.group('inner')}:{port}" if port else match.group("inner"))
        else:
            out.append(entry)
    return ",".join(out)


def normalize_no_proxy_env() -> list[str]:
    """Apply :func:`normalize_no_proxy_value` to the process environment.

    Returns the names of the variables that were rewritten, so callers can log
    the repair instead of silently mutating the user's environment.
    """
    changed: list[str] = []
    for name in ("NO_PROXY", "no_proxy"):
        current = os.environ.get(name)
        if not current:
            continue
        fixed = normalize_no_proxy_value(current)
        if fixed != current:
            os.environ[name] = fixed
            changed.append(name)
    return changed


class ModelNetworkSettingsError(ValueError):
    """A persisted model-network setting is invalid or cannot be loaded."""


@dataclass(frozen=True)
class ModelNetworkSettings:
    proxy_url: str | None = field(default=None, repr=False)
    ca_bundle_path: str | None = None
    trust_env: bool | None = None

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


def load_model_network_settings(tool: str = "model_requests") -> ModelNetworkSettings:
    raw = load_user_settings().get("model_network") or {}
    if not isinstance(raw, dict):
        raise ModelNetworkSettingsError("模型网络设置格式无效，请在设置中重新保存。")
    proxy_url: str | None = None
    tool_egress = raw.get("tool_egress") if isinstance(raw.get("tool_egress"), dict) else {}
    default_mode = "model_proxy" if tool == "model_requests" and raw.get("proxy_configured") is True else "system_proxy"
    mode = str(tool_egress.get(tool) or default_mode)
    if mode == "model_proxy" and raw.get("proxy_configured") is True:
        try:
            proxy_url = _credential_store().get(_PROXY_CREDENTIAL_KEY)
        except Exception as exc:  # noqa: BLE001 — fail closed; never bypass configured proxy
            raise ModelNetworkSettingsError("系统凭据库无法读取模型代理设置。") from exc
        if not proxy_url:
            raise ModelNetworkSettingsError("模型代理凭据缺失；请在设置中重新填写或清除代理。")
        proxy_url = validate_proxy_url(proxy_url)
    elif mode == "model_proxy":
        raise ModelNetworkSettingsError("此工具选择了模型代理，但尚未配置模型代理地址。")
    try:
        ca_bundle_path = validate_ca_bundle_path(raw.get("ca_bundle_path"))
    except ModelNetworkSettingsError as exc:
        raise ModelNetworkSettingsError(f"已保存的 CA bundle 无效：{exc}") from exc
    return ModelNetworkSettings(proxy_url=proxy_url, ca_bundle_path=ca_bundle_path,
                                trust_env=mode != "direct")


def network_settings_fingerprint(settings: ModelNetworkSettings) -> str:
    payload = json.dumps(
        {"proxy_url": settings.proxy_url, "ca_bundle_path": settings.ca_bundle_path, "trust_env": settings.trust_env},
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
    from atlas.engine.agent.ssl_verify import resolve_httpx_verify

    return resolve_httpx_verify(ca_bundle=settings.ca_bundle_path, base_url=base_url)


def _new_scoped_http_client(
    *, base_url: str, settings: ModelNetworkSettings, verify: Any, async_mode: bool,
    timeout: Any = None,
) -> Any:
    import httpx

    from atlas.engine.agent.proxy_bypass import loopback_request_kwargs

    kwargs: dict[str, Any] = {
        "verify": verify,
        "timeout": timeout or httpx.Timeout(connect=15.0, read=None, write=15.0, pool=10.0),
        "limits": httpx.Limits(max_keepalive_connections=20, max_connections=100, keepalive_expiry=20.0),
        "trust_env": (settings.trust_env if settings.trust_env is not None
                      else not loopback_request_kwargs(base_url).get("trust_env") is False),
    }
    if kwargs["trust_env"]:
        # httpx parses NO_PROXY during __init__ and raises on bracketed IPv6
        # entries; repair them first so the client can be constructed at all.
        normalize_no_proxy_env()
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


def build_tool_httpx_client(
    tool: str, *, base_url: str, async_mode: bool, timeout: Any = None,
) -> Any:
    """Create a client with the separately configured egress route for one tool family."""
    settings = load_model_network_settings(tool)
    if settings.enabled:
        return build_model_httpx_client(settings, base_url=base_url, async_mode=async_mode,
                                        timeout=timeout)
    import httpx
    from atlas.engine.agent.proxy_bypass import loopback_request_kwargs
    kwargs = loopback_request_kwargs(base_url)
    if settings.trust_env is not None:
        kwargs["trust_env"] = settings.trust_env
    if kwargs.get("trust_env", True):
        normalize_no_proxy_env()
    client_type = httpx.AsyncClient if async_mode else httpx.Client
    return client_type(timeout=timeout or 30.0, **kwargs)


@contextmanager
def model_network_scope(settings: ModelNetworkSettings) -> Iterator[None]:
    """Apply model-only transport overrides in this context and propagated worker threads."""
    token = _ACTIVE_SETTINGS.set(settings)
    try:
        yield
    finally:
        _ACTIVE_SETTINGS.reset(token)

