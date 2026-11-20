"""Shared Atlas model routing over Atlas-owned HTTPX transports.

Single entry for every Atlas LLM call: ``resolve()`` turns a model id plus a
purpose into a :class:`RouteSpec` (provider, api_mode, model, base_url, key,
credential pool). Auxiliary requests and main conversation streams use the
same HTTPX request construction and API mode validation.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx

from atlas.models import catalog
from atlas.models.network_transport import (
    ModelNetworkSettings,
    assert_transport_supported,
    build_model_httpx_client,
    load_model_network_settings,
)

_MEMORY_AUXILIARY_TIMEOUT_SECONDS = 120.0
_MEMORY_AUXILIARY_PURPOSES = frozenset({"memory_library"})
_MEMORY_LOW_REASONING_MODELS = frozenset({"gemini-3.8-flash"})
_CONTEXT_1M_BETA = "context-1m-2025-08-07"
_OLLAMA_LOCAL_BASE_URL = "http://127.0.0.1:11434/v1"
_PROVIDER_SEMAPHORES: dict[str, threading.BoundedSemaphore] = {}
_PROVIDER_SEMAPHORES_LOCK = threading.Lock()


def _provider_semaphore(route: Any) -> threading.BoundedSemaphore:
    """Queue provider requests at the configured upstream concurrency limit."""
    from atlas.config import get_config

    host = (urlsplit(str(getattr(route, "base_url", "") or "")).hostname or "").lower()
    provider = "d1api" if "d1api" in host else str(getattr(route, "provider", "default") or "default").lower()
    configured = get_config().get("models.provider_concurrency", {}) or {}
    try:
        limit = max(1, min(128, int(configured.get(provider, 8)))) if isinstance(configured, dict) else 8
    except (TypeError, ValueError):
        limit = 8
    key = f"{provider}:{limit}"
    with _PROVIDER_SEMAPHORES_LOCK:
        return _PROVIDER_SEMAPHORES.setdefault(key, threading.BoundedSemaphore(limit))


def _provider_timeout(route: Any, *, streaming: bool) -> httpx.Timeout:
    from atlas.config import get_config

    provider = str(getattr(route, "provider", "default") or "default").lower()
    configured = get_config().get("models.provider_timeouts", {}) or {}
    row = configured.get(provider, {}) if isinstance(configured, dict) else {}
    row = row if isinstance(row, dict) else {}
    defaults = {"connect": 15.0, "read": 300.0 if streaming else 120.0,
                "write": 30.0, "pool": 10.0}
    values = {}
    for key, default in defaults.items():
        try:
            values[key] = max(1.0, min(900.0, float(row.get(key, default))))
        except (TypeError, ValueError):
            values[key] = default
    return httpx.Timeout(**values)


@dataclass(frozen=True)
class RouteSpec:
    provider: str
    api_mode: str
    model: str
    base_url: str | None
    key: str | None = field(default=None, repr=False, compare=False)
    credential_pool: Any | None = field(default=None, repr=False, compare=False)
    purpose: str = "conversation"
    fallback_reason: str | None = None
    # The model id the provider endpoint expects on the wire.
    # ``model`` keeps the registry's litellm-style id (``openai/deepseek-...``);
    # the wire never sees that routing prefix — relays 404 it — so every request
    # transport consumer sends ``wire_model`` (the bare/native id) instead.
    wire_model: str = ""
    model_id: str = ""
    capabilities: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)
    # Atlas-only transport configuration; proxy credentials never appear in repr/logs.
    network_proxy_url: str | None = field(default=None, repr=False, compare=False)
    network_ca_bundle_path: str | None = field(default=None, repr=False, compare=False)
    network_trust_env: bool | None = field(default=None, repr=False, compare=False)


_USAGE_CALLBACK: ContextVar[Callable[[dict[str, Any]], Any] | None] = ContextVar(
    "atlas_model_usage_callback", default=None,
)


@contextmanager
def model_usage_callback(callback: Callable[[dict[str, Any]], Any] | None):
    """Scope auxiliary provider request rows to the active Atlas run."""
    if callback is None:
        yield
        return
    token = _USAGE_CALLBACK.set(callback)
    try:
        yield
    finally:
        _USAGE_CALLBACK.reset(token)


@dataclass(frozen=True)
class CompletionResult:
    text: str
    usage: Any = field(default=None, repr=False, compare=False)
    raw: Any = field(default=None, repr=False, compare=False)


NativeProbe = Callable[[str, str, str], Any]


async def _probe_anthropic_messages(base_url: str, api_key: str, model: str) -> tuple[bool, str | None]:
    endpoint = _messages_endpoint(base_url)
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": model,
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "OK"}],
    }
    network = load_model_network_settings()
    assert_transport_supported(network, provider="anthropic", api_mode="anthropic_messages")
    from atlas.engine.agent.proxy_bypass import loopback_request_kwargs

    client = (
        build_model_httpx_client(
            network, base_url=base_url, async_mode=True, timeout=httpx.Timeout(5.0),
        )
        if network.enabled else httpx.AsyncClient(timeout=5.0, **loopback_request_kwargs(base_url))
    )
    try:
        async with client:
            response = await client.post(endpoint, headers=headers, json=body)
    except httpx.HTTPError as exc:
        return False, f"Anthropic Messages 探测失败：{type(exc).__name__}"
    if response.status_code in {404, 405, 501}:
        return False, f"网关不支持 Anthropic Messages（HTTP {response.status_code}）"
    if response.status_code >= 500:
        return False, f"Anthropic Messages 探测返回 HTTP {response.status_code}"
    return True, None


def _messages_endpoint(base_url: str) -> str:
    base = base_url.rstrip("/")
    return f"{base}/messages" if base.lower().endswith("/v1") else f"{base}/v1/messages"


def _model_for_provider(model: dict[str, Any], native: bool) -> str:
    if not native:
        return str(model.get("litellm_model") or model.get("id") or "")
    native_model = str(model.get("native_model") or "").strip()
    if native_model:
        return native_model
    litellm_model = str(model.get("litellm_model") or model.get("id") or "")
    return litellm_model.split("/", 1)[1] if "/" in litellm_model else litellm_model


class ModelRouter:
    """Resolve model routes and execute supported requests over Atlas HTTPX transport."""

    def __init__(self, model_manager: Any, *, native_probe: NativeProbe | None = None) -> None:
        self.model_manager = model_manager
        self._native_probe = native_probe or _probe_anthropic_messages
        self._probe_locks: dict[str, asyncio.Lock] = {}

    async def resolve(self, model_id: str, purpose: str) -> RouteSpec:
        selected = next(
            (item for item in self.model_manager.list_models()
             if str(item.get("id")) == str(model_id)
             or str(item.get("litellm_model")) == str(model_id)),
            None,
        )
        if selected is None:
            raise ValueError(f"Unknown model route: {model_id}")
        raw_provider = str(selected.get("atlas_provider") or selected.get("provider") or "")
        provider_id = catalog.resolve_catalog_id(raw_provider) or raw_provider
        provider_entry = catalog.get_provider(provider_id) or {}
        configured_mode = str(selected.get("api_mode") or provider_entry.get("api_mode") or "openai")
        native_supported = configured_mode == "anthropic_messages"
        litellm_model = _model_for_provider(selected, native=False)
        native_model = _model_for_provider(selected, native=True)

        if selected.get("local_only") is True:
            # Local Ollama routes must not inherit provider/global credentials,
            # gateway endpoints, or the configured model proxy. Reject malformed
            # persisted entries instead of silently routing them elsewhere.
            if provider_id == "ollama":
                if (str(selected.get("base_url") or "") != _OLLAMA_LOCAL_BASE_URL
                        or not litellm_model.startswith("ollama/")
                        or not litellm_model.removeprefix("ollama/").strip()):
                    raise ValueError("Invalid local-only Ollama model route")
                return self._route(
                    selected, provider_id, litellm_model, _OLLAMA_LOCAL_BASE_URL,
                    None, None, "chat_completions", purpose,
                    wire_model=native_model, direct_local=True,
                )
            if provider_id == "llama-cpp":
                base_url = str(selected.get("base_url") or "")
                parsed = urlsplit(base_url)
                if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}
                        or not parsed.port or not litellm_model.startswith("llama-cpp/")
                        or not litellm_model.removeprefix("llama-cpp/").strip()):
                    raise ValueError("Invalid local-only llama.cpp model route")
                return self._route(
                    selected, provider_id, litellm_model, base_url,
                    None, None, "chat_completions", purpose,
                    wire_model=native_model, direct_local=True,
                )
            raise ValueError("Invalid local-only model route")

        provider_cfg = self.model_manager.provider_config(provider_id)
        provider_key = self.model_manager.resolve_api_key(provider_id)
        model_key = self.model_manager.resolve_model_api_key(str(selected.get("id") or "")) \
            if selected.get("custom") and hasattr(self.model_manager, "resolve_model_api_key") else None
        if model_key:
            provider_key = model_key
        pool = self.model_manager.credential_pool(provider_id)
        if pool is not None and not model_key:
            entry = pool.select(model=native_model)
            if entry is not None:
                provider_key = entry.runtime_api_key
        provider_base = (
            selected.get("base_url")
            or provider_cfg.get("base_url")
            or provider_entry.get("default_base_url")
        )

        gateway_base = str(getattr(self.model_manager, "gateway_base_url", "") or "").strip()
        gateway_key = str(getattr(self.model_manager, "gateway_api_key", "") or "")
        custom_endpoint = bool(selected.get("custom") and selected.get("base_url"))
        override = self.model_manager.get_api_mode_override(provider_id)
        if not override and selected.get("custom"):
            override = str(selected.get("api_mode") or "") or None

        if override == "anthropic_messages" and not native_supported:
            raise ValueError(f"Provider {provider_id} does not declare Anthropic Messages support")

        if override:
            if override == "anthropic_messages":
                use_provider_credentials = bool(provider_key)
                return self._route(
                    selected, provider_id, native_model,
                    provider_base if use_provider_credentials or custom_endpoint else gateway_base,
                    provider_key if use_provider_credentials else (None if custom_endpoint else gateway_key),
                    pool if use_provider_credentials and not model_key else None,
                    "anthropic_messages", purpose, wire_model=native_model,
                )
            base_url = provider_base if provider_key or custom_endpoint else gateway_base
            key = provider_key or (None if custom_endpoint else gateway_key) or None
            return self._route(
                selected, provider_id, litellm_model, base_url or None, key, pool if provider_key else None,
                self._canonical_mode(override), purpose, wire_model=native_model,
            )

        if native_supported and provider_key:
            return self._route(
                selected, provider_id, native_model, provider_base, provider_key, pool,
                "anthropic_messages", purpose, wire_model=native_model,
            )

        if custom_endpoint and not provider_key:
            # A model with its own endpoint must never receive the unrelated
            # gateway credential or silently fall back to the gateway route.
            return self._route(
                selected, provider_id, litellm_model, str(provider_base), None, None,
                self._canonical_mode(override or configured_mode), purpose,
                wire_model=native_model,
            )

        if native_supported and gateway_base and gateway_key and not custom_endpoint:
            supported, reason = await self._gateway_native_support(
                provider_id, gateway_base, gateway_key, native_model,
            )
            if supported:
                return self._route(
                    selected, provider_id, native_model, gateway_base, gateway_key, None,
                    "anthropic_messages", purpose, wire_model=native_model,
                )
            return self._route(
                selected, provider_id, litellm_model, gateway_base, gateway_key, None,
                "chat_completions", purpose, fallback_reason=reason, wire_model=native_model,
            )

        if provider_key:
            return self._route(
                selected, provider_id, litellm_model, provider_base, provider_key, pool,
                "chat_completions", purpose, wire_model=native_model,
            )
        if gateway_base and gateway_key:
            return self._route(
                selected, provider_id, litellm_model, gateway_base, gateway_key, None,
                "chat_completions", purpose, wire_model=native_model,
            )
        return self._route(
            selected, provider_id, litellm_model, provider_base or None, None, pool,
            "chat_completions", purpose, wire_model=native_model,
        )

    async def _gateway_native_support(
        self, provider_id: str, base_url: str, api_key: str, model: str,
    ) -> tuple[bool, str | None]:
        key_fingerprint = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]
        cached = self.model_manager.get_api_mode_probe(provider_id)
        if (cached and cached.get("base_url") == base_url.rstrip("/")
                and cached.get("credential_fingerprint") == key_fingerprint
                and isinstance(cached.get("supported"), bool)):
            return cached["supported"], cached.get("reason")
        lock = self._probe_locks.setdefault(provider_id, asyncio.Lock())
        async with lock:
            cached = self.model_manager.get_api_mode_probe(provider_id)
            if (cached and cached.get("base_url") == base_url.rstrip("/")
                    and cached.get("credential_fingerprint") == key_fingerprint
                    and isinstance(cached.get("supported"), bool)):
                return cached["supported"], cached.get("reason")
            result = self._native_probe(base_url, api_key, model)
            if inspect.isawaitable(result):
                supported, reason = await result
            else:
                supported, reason = result
            self.model_manager.set_api_mode_probe(provider_id, {
                "endpoint": _messages_endpoint(base_url),
                "base_url": base_url.rstrip("/"),
                "credential_fingerprint": key_fingerprint,
                "supported": bool(supported),
                "reason": reason,
                "checked_at": time.time(),
            })
            return bool(supported), reason

    @staticmethod
    def _canonical_mode(value: str) -> str:
        return "chat_completions" if value == "openai" else value

    @staticmethod
    def _route(
        model_data: dict[str, Any], provider: str, model: str, base_url: str | None,
        key: str | None, pool: Any | None, api_mode: str, purpose: str,
        fallback_reason: str | None = None, wire_model: str = "", direct_local: bool = False,
    ) -> RouteSpec:
        network = ModelNetworkSettings() if direct_local else load_model_network_settings()
        assert_transport_supported(network, provider=provider, api_mode=api_mode)
        return RouteSpec(
            provider=provider, api_mode=api_mode, model=model, base_url=base_url,
            key=key, credential_pool=pool, purpose=purpose, fallback_reason=fallback_reason,
            wire_model=wire_model or model, model_id=str(model_data.get("id") or ""),
            capabilities=dict(model_data.get("capabilities") or {})
            if isinstance(model_data.get("capabilities"), dict) else {},
            network_proxy_url=network.proxy_url,
            network_ca_bundle_path=network.ca_bundle_path,
            network_trust_env=network.trust_env,
        )

    async def complete(self, route: RouteSpec, messages: list[dict[str, Any]], **kwargs: Any) -> CompletionResult:
        """Run one auxiliary request over the same Atlas-owned HTTP transport."""
        wire_model = route.wire_model or route.model
        usage_callback = kwargs.pop("usage_callback", None) or _USAGE_CALLBACK.get()
        from atlas.usage import env_run_usage_budget
        from atlas.models.tokens import estimate_tokens
        from atlas.engine.agent.turn_usage import new_usage_request_id

        if route.purpose in _MEMORY_AUXILIARY_PURPOSES and kwargs.get("timeout") is None:
            kwargs["timeout"] = _MEMORY_AUXILIARY_TIMEOUT_SECONDS
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = _provider_timeout(route, streaming=False)
        if (
            route.purpose in _MEMORY_AUXILIARY_PURPOSES
            and (route.wire_model or route.model) in _MEMORY_LOW_REASONING_MODELS
        ):
            extra_body = kwargs.get("extra_body")
            memory_extra_body = dict(extra_body) if isinstance(extra_body, dict) else {}
            memory_extra_body.setdefault("reasoning_effort", "low")
            kwargs["extra_body"] = memory_extra_body

        request_id = new_usage_request_id()
        network = ModelNetworkSettings(
            proxy_url=route.network_proxy_url,
            ca_bundle_path=route.network_ca_bundle_path,
            trust_env=route.network_trust_env,
        )
        assert_transport_supported(network, provider=route.provider, api_mode=route.api_mode)
        budget = env_run_usage_budget()
        request_text = "\n".join(str(item.get("content") or "") for item in messages)
        estimate = max(1, estimate_tokens(request_text, model=wire_model))
        if budget is not None and not budget.reserve(
            request_id, estimate, purpose=route.purpose,
            model=route.model_id or route.model, wire_model=wire_model,
        ):
            reason = (
                "Estimated run cost limit reached or model price is unknown"
                if budget.cost_limit_usd is not None else "Run input-token budget reached"
            )
            raise RuntimeError(f"{reason}; the auxiliary model request was not sent.")
        try:
            response = await asyncio.to_thread(
                _post_completion_queued, route, messages, kwargs, network,
                _provider_semaphore(route), budget is None,
            )
        except BaseException:
            if budget is not None:
                budget.release(request_id)
            raise
        text = _response_text(response)
        usage = response.get("usage") if isinstance(response, dict) else getattr(response, "usage", None)
        from atlas.engine.agent.turn_usage import report_auxiliary_usage

        observed = report_auxiliary_usage(
            usage_callback, response, purpose=route.purpose,
            model=route.model_id or route.model, provider=route.provider,
            api_mode=route.api_mode, wire_model=wire_model, request_id=request_id,
        )
        if observed is not None and budget is not None:
            budget.record(observed[0])
        elif budget is not None:
            budget.release(request_id)
        observed = observed[1] if observed is not None else None
        if inspect.isawaitable(observed):
            try:
                await observed
            except Exception:
                import logging

                logging.getLogger(__name__).warning("Auxiliary usage observer callback failed", exc_info=True)
        return CompletionResult(text=text, usage=usage, raw=response)

    def stream(
        self, route: RouteSpec, messages: list[dict[str, Any]], **kwargs: Any,
    ) -> Any:
        """Return a blocking iterator of OpenAI-shaped chunks for the main run loop."""
        network = ModelNetworkSettings(
            proxy_url=route.network_proxy_url, ca_bundle_path=route.network_ca_bundle_path,
            trust_env=route.network_trust_env,
        )
        assert_transport_supported(network, provider=route.provider, api_mode=route.api_mode)
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = _provider_timeout(route, streaming=True)
        semaphore = _provider_semaphore(route)
        allow_transport_retries = kwargs.pop("_atlas_allow_transport_retries", True)

        managed: _ManagedBlockingStream

        def queued_stream():
            semaphore.acquire()
            try:
                yield from _stream_completion(
                    route, messages, kwargs, network,
                    allow_transport_retries=allow_transport_retries,
                    on_response=managed._set_response,
                    retry_allowed=managed.retry_allowed,
                )
            finally:
                semaphore.release()

        managed = _ManagedBlockingStream(queued_stream())
        return managed

    async def complete_for(
        self, model_id: str, purpose: str, messages: list[dict[str, Any]],
        fallbacks: list[str] | None = None, **kwargs: Any,
    ) -> CompletionResult:
        candidates = [model_id, *(fallbacks or [])]
        for alt in ("deepseek-v4.1-flash", "deepseek-v3"):
            if alt not in candidates:
                candidates.append(alt)
        last_error: Exception | None = None
        attempted: list[str] = []
        for candidate in candidates:
            try:
                route = await self.resolve(candidate, purpose)
                return await self.complete(route, messages, **kwargs)
            except Exception as exc:
                attempted.append(candidate)
                last_error = exc
                continue
        # Raise the FIRST failure, not the last. The candidate list ends with
        # hardcoded fallbacks ("deepseek-v4.1-flash", "deepseek-v3"); raising the
        # last error meant a genuinely broken primary route surfaced as
        # "Unknown model route: deepseek-v3", which sends every investigation to
        # the wrong place. The first error is the one about the model that was
        # actually asked for.
        if last_error is not None:
            detail = ", ".join(attempted)
            if len(attempted) > 1:
                raise RuntimeError(
                    f"All model candidates failed for {model_id!r} (tried: {detail})"
                ) from last_error
            raise last_error
        raise RuntimeError("No model candidates available")

    @staticmethod
    def atlas_agent_kwargs(route: RouteSpec) -> dict[str, Any]:
        """Kwargs accepted by the pinned engine agent constructor, including its public pool seam.

        The agent's transport sends ``model`` verbatim on the wire (no litellm
        indirection), so the agent is pinned to ``wire_model`` — the bare id the
        endpoint exposes. Passing the registry's litellm-style id here made real
        relays 404 every conversation turn (H10.2-DEFECT-1).
        """
        network = ModelNetworkSettings(
            proxy_url=route.network_proxy_url,
            ca_bundle_path=route.network_ca_bundle_path,
            trust_env=route.network_trust_env,
        )
        assert_transport_supported(network, provider=route.provider, api_mode=route.api_mode)
        return {
            "provider": route.provider,
            "model": route.wire_model or route.model,
            "base_url": route.base_url,
            "api_key": route.key,
            "api_mode": route.api_mode,
            "credential_pool": route.credential_pool,
            "_atlas_network_transport": {
                "proxy_url": route.network_proxy_url,
                "ca_bundle_path": route.network_ca_bundle_path,
                "trust_env": route.network_trust_env,
            },
        }


def _response_text(response: Any) -> str:
    choices = response.get("choices") if isinstance(response, dict) else getattr(response, "choices", None)
    if choices:
        message = choices[0].get("message") if isinstance(choices[0], dict) else getattr(choices[0], "message", None)
        content = message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
    else:
        content = response.get("content") if isinstance(response, dict) else getattr(response, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(part.get("text") or "") for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return str(content or "")


def _endpoint(base_url: str | None, suffix: str) -> str:
    base = str(base_url or "").rstrip("/")
    if not base:
        raise ValueError("Model endpoint URL is not configured")
    if base.endswith("/" + suffix):
        return base
    return base if base.endswith(suffix) else f"{base}/{suffix.lstrip('/')}"


def _anthropic_payload(route: RouteSpec, messages: list[dict[str, Any]], kwargs: dict[str, Any]) -> dict[str, Any]:
    system: list[dict[str, Any]] = []
    converted: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "user")
        content = message.get("content") or ""
        if role in {"system", "developer"}:
            if isinstance(content, str):
                system.append({"type": "text", "text": content})
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type", "text") == "text":
                        block = {"type": "text", "text": str(part.get("text") or "")}
                        if isinstance(part.get("cache_control"), dict):
                            block["cache_control"] = part["cache_control"]
                        system.append(block)
        elif role == "tool":
            result_block = {
                "type": "tool_result", "tool_use_id": str(message.get("tool_call_id") or ""),
                "content": str(content),
            }
            if isinstance(message.get("cache_control"), dict):
                result_block["cache_control"] = message["cache_control"]
            converted.append({"role": "user", "content": [result_block]})
        else:
            blocks: list[dict[str, Any]] = []
            if isinstance(content, str) and content:
                blocks.append({"type": "text", "text": content})
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        block = {"type": "text", "text": str(part.get("text") or "")}
                        if isinstance(part.get("cache_control"), dict):
                            block["cache_control"] = part["cache_control"]
                        blocks.append(block)
                    elif isinstance(part, dict) and part.get("type") in {"image", "image_url"}:
                        # Atlas tool results use OpenAI's image_url wrapper, while some
                        # callers already provide Anthropic's source block. Normalize
                        # both without fetching remote URLs or exposing image bytes.
                        source = part.get("source") if part.get("type") == "image" else None
                        image_url = part.get("image_url") if part.get("type") == "image_url" else None
                        if isinstance(source, dict):
                            if source.get("type") in {"base64", "url"}:
                                blocks.append({"type": "image", "source": dict(source)})
                            else:
                                raise ValueError("Unsupported Anthropic image source type")
                        elif isinstance(image_url, dict):
                            url = str(image_url.get("url") or "")
                            if url.startswith("data:") and ";base64," in url:
                                header, data = url[5:].split(",", 1)
                                media_type = header.split(";", 1)[0]
                                if "base64" not in header.lower():
                                    raise ValueError("Anthropic image data URLs must be base64 encoded")
                                blocks.append({"type": "image", "source": {
                                    "type": "base64", "media_type": media_type, "data": data,
                                }})
                            elif url.startswith(("https://", "http://")):
                                blocks.append({"type": "image", "source": {"type": "url", "url": url}})
                            else:
                                raise ValueError("Anthropic image_url must contain an HTTP(S) URL or base64 data URL")
                        else:
                            raise ValueError("Anthropic image content requires source or image_url")
                    elif isinstance(part, dict) and part.get("type") == "thinking":
                        blocks.append({key: part[key] for key in ("type", "thinking", "signature") if key in part})
            if role == "assistant":
                for detail in message.get("reasoning_details") or []:
                    if isinstance(detail, dict) and detail.get("type") == "thinking":
                        blocks.append({"type": "thinking", "thinking": str(detail.get("thinking") or ""),
                                       "signature": str(detail.get("signature") or "")})
                for call in message.get("tool_calls") or []:
                    function = call.get("function") or {}
                    try:
                        arguments = json.loads(function.get("arguments") or "{}")
                    except (TypeError, ValueError) as exc:
                        raise ValueError("Anthropic tool arguments must be valid JSON") from exc
                    blocks.append({"type": "tool_use", "id": call.get("id") or "", "name": function.get("name") or "", "input": arguments})
            converted.append({"role": "assistant" if role == "assistant" else "user", "content": blocks})
    if not converted:
        converted = [{"role": "user", "content": ""}]
    max_tokens = kwargs.get("max_tokens") or kwargs.get("max_output_tokens") or 8192
    payload: dict[str, Any] = {
        "model": route.wire_model or route.model, "messages": converted,
        "max_tokens": max(1, int(max_tokens)),
    }
    if system:
        payload["system"] = system
    reasoning = kwargs.get("reasoning_config")
    if isinstance(reasoning, dict):
        effort = str(reasoning.get("effort") or "").strip().lower()
        if reasoning.get("enabled") is False or effort in THINKING_OFF:
            payload["thinking"] = {"type": "disabled"}
        elif effort:
            max_tokens = int(payload["max_tokens"])
            numeric = None
            try:
                numeric = float(effort)
            except ValueError:
                pass
            if numeric is not None:
                effort = "low" if numeric <= 50 else "medium" if numeric <= 85 else "high"
            budget = {
                "minimal": 512, "low": 1024, "medium": 4096,
                "high": 8192, "max": 8192,
            }.get(effort, 4096)
            payload["thinking"] = {"type": "enabled", "budget_tokens": min(budget, max(1, max_tokens - 1))}
    tools = kwargs.get("tools")
    if route.capabilities.get("supports_tools") is False:
        tools = None
    if tools:
        payload["tools"] = []
        for tool in tools:
            function = tool.get("function") or {}
            converted_tool = {
                "name": function.get("name", ""),
                "description": function.get("description", ""),
                "input_schema": function.get("parameters") or {"type": "object", "properties": {}},
            }
            if isinstance(tool.get("cache_control"), dict):
                converted_tool["cache_control"] = tool["cache_control"]
            payload["tools"].append(converted_tool)
    if kwargs.get("temperature") is not None:
        payload["temperature"] = kwargs["temperature"]
    payload["stream"] = bool(kwargs.get("stream", False))
    return payload


THINKING_OFF = frozenset({"off", "none", "disabled", "false", "0"})


def _reasoning_wire(route: RouteSpec, reasoning: Any) -> dict[str, Any]:
    """Map Atlas' effort onto the switch an OpenAI-compatible endpoint actually honours.

    "off" is not an OpenAI effort value: relays drop or 400 it, and DeepSeek-family
    models then think by default (measured on a relay: reasoning_effort="off" still
    produced reasoning on about half the requests). Each family has its own off switch.
    """
    if not isinstance(reasoning, dict):
        reasoning = {}
    from atlas.models.reasoning_effort import (
        DEEPSEEK_V4_EFFORTS, KIMI_K3_OVERRIDES, clamp_effort,
        kimi_supported_efforts, route_supported_efforts, thinking_toggle_extras,
    )

    effort = str(reasoning.get("effort") or "").strip().lower()
    if reasoning.get("enabled") is False:
        effort = "off"
    provider = (route.provider or "").lower()
    model = (route.wire_model or route.model or "").lower()
    if not effort:
        if "deepseek" in provider or "deepseek" in model:
            return {"thinking": {"type": "enabled"}}
        return {}
    if effort not in THINKING_OFF:
        if "deepseek" in provider or "deepseek" in model:
            supported = DEEPSEEK_V4_EFFORTS if "v4" in model else ("low", "medium", "high")
            toggle, values = thinking_toggle_extras(
                {"effort": effort}, supported, always_emit_toggle=True,
            )
            return {**toggle, **values}
        if "moonshot" in provider or "kimi" in provider or "kimi" in model:
            return {"reasoning_effort": clamp_effort(
                effort, kimi_supported_efforts(model), KIMI_K3_OVERRIDES,
            )}
        return {"reasoning_effort": clamp_effort(
            effort, route_supported_efforts(provider, model),
        )}
    if any(tag in model for tag in ("deepseek", "kimi", "moonshot", "glm", "zhipu")):
        return {"thinking": {"type": "disabled"}}
    if "qwen" in model or "qwq" in model:
        return {"enable_thinking": False}
    if model.rsplit("/", 1)[-1].startswith(("gpt-5", "o1", "o3", "o4")):
        return {"reasoning_effort": "minimal"}
    if "gemini" in model:
        return {"reasoning_effort": "none"}
    return {}


def _openai_payload(route: RouteSpec, messages: list[dict[str, Any]], kwargs: dict[str, Any]) -> dict[str, Any]:
    if route.api_mode not in {"openai", "chat_completions"}:
        raise NotImplementedError(f"Atlas direct transport does not support API mode {route.api_mode!r}")
    payload: dict[str, Any] = {
        "model": route.wire_model or route.model,
        "messages": [
            {key: value for key, value in message.items() if key in {
                "role", "content", "tool_calls", "tool_call_id", "name", "refusal",
                *(('reasoning_content',) if (
                    "deepseek" in (route.provider or "").lower()
                    or "deepseek" in (route.wire_model or route.model or "").lower()
                ) else ()),
            }}
            for message in messages
        ],
        "stream": bool(kwargs.get("stream", False)),
    }
    for key in ("max_tokens", "max_completion_tokens", "temperature", "top_p", "stop", "stream_options", "tools", "tool_choice", "parallel_tool_calls", "service_tier"):
        if kwargs.get(key) is not None:
            payload[key] = kwargs[key]
    payload.update(_reasoning_wire(route, kwargs.get("reasoning_config")))
    extra = kwargs.get("extra_body")
    if isinstance(extra, dict):
        payload.update(extra)
    # Model capability gates apply to the final wire payload as well as the
    # standard arguments; provider-specific extra_body must not re-enable tools.
    if route.capabilities.get("supports_tools") is False:
        for key in ("tools", "tool_choice", "parallel_tool_calls"):
            payload.pop(key, None)
    return payload


def _request_details(route: RouteSpec, messages: list[dict[str, Any]], kwargs: dict[str, Any]) -> tuple[str, dict[str, str], dict[str, Any]]:
    if route.api_mode == "anthropic_messages":
        url = _messages_endpoint(str(route.base_url or ""))
        headers = {
            "x-api-key": route.key or "", "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        requested_betas = kwargs.get("sdk_betas")
        if isinstance(requested_betas, str):
            requested_betas = [requested_betas]
        context_window = route.capabilities.get("context_window")
        eligible_1m = (
            str(route.provider).lower() == "anthropic"
            and type(context_window) is int and context_window >= 1_000_000
        )
        if eligible_1m and isinstance(requested_betas, (list, tuple, set, frozenset)):
            # The only permitted direct Anthropic beta is the 1M context flag,
            # and only for models whose catalog entry explicitly qualifies.
            if _CONTEXT_1M_BETA in requested_betas:
                headers["anthropic-beta"] = _CONTEXT_1M_BETA
        payload = _anthropic_payload(route, messages, kwargs)
    elif route.api_mode in {"openai", "chat_completions"}:
        url = _endpoint(route.base_url, "chat/completions")
        headers = {"content-type": "application/json"}
        if route.key:
            headers["authorization"] = f"Bearer {route.key}"
        payload = _openai_payload(route, messages, kwargs)
    else:
        raise NotImplementedError(f"Atlas direct transport does not support API mode {route.api_mode!r}")
    extra_headers = kwargs.get("extra_headers")
    if isinstance(extra_headers, dict):
        reserved = {
            "authorization", "x-api-key", "anthropic-version", "anthropic-beta",
            "content-type",
        }
        for key, value in extra_headers.items():
            header = str(key).strip()
            if not header or header.lower() in reserved or value is None:
                continue
            headers[header] = str(value)
    return url, headers, payload


# One keep-alive pool per transport configuration. A fresh client per request paid a
# TCP + TLS handshake to the relay on every model step (hundreds of ms each).
_POOLS: dict[tuple[Any, ...], httpx.Client] = {}
_POOL_LAST_USE: dict[tuple[Any, ...], float] = {}
_POOLS_LOCK = threading.Lock()
# Below common server idle limits (nginx 60-75s), so a pooled socket is rarely stale.
_POOL_KEEPALIVE_S = 50.0
# A model relay may reset a socket during TLS setup or close an idle pooled socket.
# Retry only transient transport failures and server errors, with two bounded retries.
_TRANSIENT_MODEL_ERRORS = (
    httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError,
    httpx.ReadError, httpx.WriteError, httpx.ReadTimeout, httpx.WriteTimeout,
)
_MODEL_RETRY_DELAYS = (0.25, 0.6)


def _pool_key(route: RouteSpec, network: ModelNetworkSettings) -> tuple[Any, ...]:
    from atlas.engine.agent.proxy_bypass import loopback_request_kwargs

    base = str(route.base_url or "")
    return (network.enabled, network.proxy_url, network.ca_bundle_path, network.trust_env,
            bool(loopback_request_kwargs(base)))


def _shared_client(route: RouteSpec, network: ModelNetworkSettings) -> tuple[httpx.Client, tuple[Any, ...]]:
    key = _pool_key(route, network)
    with _POOLS_LOCK:
        client = _POOLS.get(key)
        if client is None or client.is_closed:
            limits = httpx.Limits(max_keepalive_connections=20, max_connections=100,
                                  keepalive_expiry=_POOL_KEEPALIVE_S)
            if network.enabled:
                client = build_model_httpx_client(network, base_url=str(route.base_url or ""),
                                                  async_mode=False)
            else:
                from atlas.engine.agent.proxy_bypass import loopback_request_kwargs
                client_kwargs = loopback_request_kwargs(str(route.base_url or ""))
                if network.trust_env is not None:
                    client_kwargs["trust_env"] = network.trust_env
                client = httpx.Client(limits=limits, **client_kwargs)
            _POOLS[key] = client
    return client, key


class _PooledClient:
    """Per-request view of a shared pool: carries the timeout, never closes the pool."""

    def __init__(
        self, route: RouteSpec, network: ModelNetworkSettings, timeout: Any,
        *, allow_retries: bool = True, retry_allowed: Callable[[], bool] | None = None,
    ) -> None:
        self._route = route
        self._network = network
        self._client, self._key = _shared_client(route, network)
        self._timeout = timeout
        self._allow_retries = bool(allow_retries)
        self._retry_allowed = retry_allowed

    def _rebuild_after_stale_socket(self) -> None:
        """Evict a failed keep-alive pool before retrying the request."""
        with _POOLS_LOCK:
            stale = _POOLS.get(self._key)
            if stale is self._client:
                _POOLS.pop(self._key, None)
                try:
                    stale.close()
                except Exception:
                    pass
        self._client, self._key = _shared_client(self._route, self._network)

    def _can_retry(self) -> bool:
        return self._allow_retries and (
            self._retry_allowed is None or self._retry_allowed()
        )

    def __enter__(self) -> "_PooledClient":
        return self

    def __exit__(self, *exc: Any) -> bool:
        _POOL_LAST_USE[self._key] = time.monotonic()
        return False

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        kwargs.setdefault("timeout", self._timeout)
        retry_delays = _MODEL_RETRY_DELAYS if self._allow_retries else ()
        for attempt in range(len(retry_delays) + 1):
            try:
                response = self._client.post(url, **kwargs)
            except _TRANSIENT_MODEL_ERRORS:
                if attempt == len(retry_delays):
                    raise
                self._rebuild_after_stale_socket()
            else:
                if response.status_code < 500 or attempt == len(retry_delays):
                    return response
                response.close()
            time.sleep(retry_delays[attempt])
        raise AssertionError("unreachable")

    def open_stream(self, url: str, **kwargs: Any) -> httpx.Response:
        request = self._client.build_request("POST", url, timeout=self._timeout, **kwargs)
        response: httpx.Response | None = None
        for attempt in range(len(_MODEL_RETRY_DELAYS) + 1):
            try:
                response = self._client.send(request, stream=True)
            except _TRANSIENT_MODEL_ERRORS:
                if attempt == len(_MODEL_RETRY_DELAYS) or not self._can_retry():
                    raise
                self._rebuild_after_stale_socket()
            else:
                if (response.status_code < 500 or attempt == len(_MODEL_RETRY_DELAYS)
                        or not self._can_retry()):
                    break
                response.read()
                response.close()
            time.sleep(_MODEL_RETRY_DELAYS[attempt])
            request = self._client.build_request("POST", url, timeout=self._timeout, **kwargs)
        assert response is not None
        if response.is_error:
            # Read the body so error classification (context length, quota...) sees it.
            try:
                response.read()
            finally:
                response.close()
            response.raise_for_status()
        return response


class _ManagedBlockingStream:
    """Blocking iterator with an abort handle safe to call during ``next()``."""

    def __init__(self, iterator: Any) -> None:
        self._iterator = iterator
        self._lock = threading.Lock()
        self._response: httpx.Response | None = None
        self._advancing = False
        self._closed = False

    def __iter__(self) -> "_ManagedBlockingStream":
        return self

    def __next__(self) -> Any:
        with self._lock:
            if self._closed:
                raise StopIteration
            self._advancing = True
        try:
            return next(self._iterator)
        finally:
            with self._lock:
                self._advancing = False

    def _set_response(self, response: httpx.Response | None) -> None:
        with self._lock:
            self._response = response
            should_close = self._closed and response is not None
        if should_close:
            response.close()

    def abort(self) -> None:
        """Close the active response from another thread without touching next()."""
        with self._lock:
            self._closed = True
            response = self._response
        if response is not None:
            response.close()

    def retry_allowed(self) -> bool:
        """Let an in-flight blocking transport observe cancellation before retrying."""
        with self._lock:
            return not self._closed

    def close(self) -> None:
        """Abort the response and close an idle generator."""
        self.abort()
        with self._lock:
            advancing = self._advancing
        if not advancing:
            self._iterator.close()


def _client(
    route: RouteSpec, network: ModelNetworkSettings, timeout: Any,
    *, allow_retries: bool = True, retry_allowed: Callable[[], bool] | None = None,
) -> _PooledClient:
    return _PooledClient(
        route, network, timeout, allow_retries=allow_retries,
        retry_allowed=retry_allowed,
    )


def prewarm(route: RouteSpec) -> None:
    """Open the pooled TLS connection ahead of the first model request of a run.

    Skipped when the pool was used within its keep-alive window (a live socket is
    already there). Errors are ignored: the real request reports them.
    """
    if route.api_mode not in {"openai", "chat_completions", "anthropic_messages"} or not route.base_url:
        return
    network = ModelNetworkSettings(proxy_url=route.network_proxy_url,
                                   ca_bundle_path=route.network_ca_bundle_path,
                                   trust_env=route.network_trust_env)
    key = _pool_key(route, network)
    if time.monotonic() - _POOL_LAST_USE.get(key, -1e9) < _POOL_KEEPALIVE_S - 5:
        return
    try:
        client, key = _shared_client(route, network)
        client.head(str(route.base_url), timeout=httpx.Timeout(10.0))
        _POOL_LAST_USE[key] = time.monotonic()
    except Exception:
        pass


def _post_completion_queued(route: RouteSpec, messages: list[dict[str, Any]],
                            kwargs: dict[str, Any], network: ModelNetworkSettings,
                            semaphore: threading.BoundedSemaphore,
                            allow_transport_retries: bool = True) -> dict[str, Any]:
    semaphore.acquire()
    try:
        return _post_completion(
            route, messages, kwargs, network,
            allow_transport_retries=allow_transport_retries,
        )
    finally:
        semaphore.release()


def _post_completion(
    route: RouteSpec, messages: list[dict[str, Any]], kwargs: dict[str, Any],
    network: ModelNetworkSettings, *, allow_transport_retries: bool = True,
) -> dict[str, Any]:
    timeout = kwargs.get("timeout") or httpx.Timeout(connect=15.0, read=120.0, write=30.0, pool=10.0)
    url, headers, payload = _request_details(route, messages, {**kwargs, "stream": False})
    with _client(route, network, timeout, allow_retries=allow_transport_retries) as client:
        response = client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        if route.api_mode == "anthropic_messages" and "text/event-stream" in response.headers.get("content-type", ""):
            from types import SimpleNamespace

            blocks: dict[int, dict[str, Any]] = {}
            reasoning_blocks: dict[int, dict[str, Any]] = {}
            input_tokens = output_tokens = cache_read = cache_creation = 0
            for line in response.iter_lines():
                if not line.startswith("data: ") or line[6:] == "[DONE]":
                    continue
                try:
                    event = json.loads(line[6:])
                except ValueError:
                    continue
                kind = event.get("type")
                if kind == "content_block_delta":
                    delta = event.get("delta") or {}
                    block = blocks.setdefault(int(event.get("index", 0)), {})
                    if delta.get("type") == "text_delta":
                        block["text"] = str(block.get("text") or "") + str(delta.get("text") or "")
                    elif delta.get("type") == "thinking_delta":
                        block["thinking"] = str(block.get("thinking") or "") + str(delta.get("thinking") or "")
                    elif delta.get("type") == "signature_delta":
                        block["signature"] = str(block.get("signature") or "") + str(delta.get("signature") or "")
                    elif delta.get("type") == "input_json_delta":
                        block["partial_json"] = str(block.get("partial_json") or "") + str(delta.get("partial_json") or "")
                elif kind == "content_block_start":
                    index = int(event.get("index", 0))
                    block = dict(event.get("content_block") or {})
                    blocks[index] = block
                    if block.get("type") == "thinking":
                        reasoning_blocks[index] = {
                            "type": "thinking", "thinking": str(block.get("thinking") or ""),
                            "signature": str(block.get("signature") or ""),
                        }
                elif kind == "message_start":
                    usage = ((event.get("message") or {}).get("usage") or {})
                    input_tokens = int(usage.get("input_tokens") or 0)
                    cache_read = int(usage.get("cache_read_input_tokens") or 0)
                    cache_creation = int(usage.get("cache_creation_input_tokens") or 0)
                elif kind == "message_delta":
                    output_tokens = int((event.get("usage") or {}).get("output_tokens") or 0)
            text = "".join(str(block.get("text") or "") for block in blocks.values()
                           if block.get("type") == "text")
            tool_calls = []
            reasoning = []
            for block in blocks.values():
                if block.get("type") == "tool_use":
                    raw_args = block.get("partial_json") or json.dumps(block.get("input") or {})
                    tool_calls.append(SimpleNamespace(
                        id=str(block.get("id") or ""), type="function",
                        name=str(block.get("name") or ""), arguments=str(raw_args),
                        function=SimpleNamespace(name=str(block.get("name") or ""), arguments=str(raw_args)),
                    ))
                elif block.get("type") == "thinking":
                    reasoning.append({key: block[key] for key in ("type", "thinking", "signature") if key in block})
            data = SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=text, tool_calls=tool_calls or None,
                                                                  reasoning_details=reasoning or None),
                                         finish_reason=None)],
                usage=SimpleNamespace(prompt_tokens=input_tokens, completion_tokens=output_tokens,
                                      total_tokens=input_tokens + output_tokens,
                                      cache_read_input_tokens=cache_read,
                                      cache_creation_input_tokens=cache_creation),
            )
        else:
            data = response.json()
    if route.api_mode == "anthropic_messages" and isinstance(data, dict) and "content" in data:
        from types import SimpleNamespace

        blocks = [block for block in data.get("content", []) if isinstance(block, dict)]
        text = "".join(str(block.get("text") or "") for block in blocks if block.get("type") == "text")
        tool_calls = [SimpleNamespace(
            id=str(block.get("id") or ""), type="function",
            function=SimpleNamespace(name=str(block.get("name") or ""),
                                     arguments=json.dumps(block.get("input") or {}, ensure_ascii=False)),
        ) for block in blocks if block.get("type") == "tool_use"]
        reasoning_details = [
            {"type": "thinking", "thinking": str(block.get("thinking") or ""),
             "signature": str(block.get("signature") or "")}
            for block in blocks if block.get("type") == "thinking"
        ]
        message = SimpleNamespace(content=text, tool_calls=tool_calls or None,
                                  reasoning_details=reasoning_details or None)
        usage = data.get("usage") or {}
        usage_obj = SimpleNamespace(
            prompt_tokens=usage.get("input_tokens"), completion_tokens=usage.get("output_tokens"),
            total_tokens=(int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)),
            cache_read_input_tokens=usage.get("cache_read_input_tokens"),
            cache_creation_input_tokens=usage.get("cache_creation_input_tokens"),
        )
        data = SimpleNamespace(
            choices=[SimpleNamespace(message=message, finish_reason=data.get("stop_reason"))],
            usage=usage_obj,
        )
    return data


def _dump_payload(payload: dict[str, Any]) -> None:
    """ATLAS_DUMP_MODEL_PAYLOAD=<dir>: keep each conversation request body (no headers, so
    no key) for diagnosing prompt-cache misses by diffing consecutive requests. Off by default."""
    import os

    target = os.environ.get("ATLAS_DUMP_MODEL_PAYLOAD")
    if not target:
        return
    try:
        from pathlib import Path

        folder = Path(target)
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{time.strftime('%Y%m%d-%H%M%S')}-{int(time.time() * 1000) % 1000:03d}.json"
        (folder / name).write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str),
                                   encoding="utf-8")
    except Exception:
        pass


def _stream_completion(
    route: RouteSpec, messages: list[dict[str, Any]], kwargs: dict[str, Any],
    network: ModelNetworkSettings, *, allow_transport_retries: bool = True,
    on_response: Callable[[httpx.Response | None], None] | None = None,
    retry_allowed: Callable[[], bool] | None = None,
):
    # read is only a backstop for a socket that went silent; the kernel's stream watchdog
    # (first-chunk / idle limits) gives up and retries well before it.
    timeout = kwargs.get("timeout") or httpx.Timeout(connect=15.0, read=300.0, write=30.0, pool=10.0)
    url, headers, payload = _request_details(route, messages, {**kwargs, "stream": True})
    if route.api_mode == "anthropic_messages":
        payload["stream"] = True
    _dump_payload(payload)
    with _client(
        route, network, timeout, allow_retries=allow_transport_retries,
        retry_allowed=retry_allowed,
    ) as client:
        response = client.open_stream(url, headers=headers, json=payload)
        if on_response is not None:
            on_response(response)
        try:
            if route.api_mode == "anthropic_messages":
                tool_indexes: dict[int, int] = {}
                next_tool_index = 0
                anthropic_reasoning_blocks: dict[int, dict[str, Any]] = {}
                input_tokens = 0
                cache_read = cache_creation = 0
                for raw in response.iter_lines():
                    if not raw.startswith("data: "):
                        continue
                    event = raw[6:]
                    if event == "[DONE]":
                        break
                    try:
                        item = json.loads(event)
                    except ValueError:
                        continue
                    kind = item.get("type")
                    if kind == "message_start":
                        usage = (item.get("message") or {}).get("usage", {})
                        input_tokens = int(usage.get("input_tokens") or 0)
                        cache_read = int(usage.get("cache_read_input_tokens") or 0)
                        cache_creation = int(usage.get("cache_creation_input_tokens") or 0)
                    elif kind == "content_block_start":
                        block = item.get("content_block") or {}
                        block_index = int(item.get("index", 0))
                        if block.get("type") == "thinking":
                            anthropic_reasoning_blocks[block_index] = {
                                "type": "thinking", "thinking": str(block.get("thinking") or ""),
                                "signature": str(block.get("signature") or ""),
                            }
                        if block.get("type") == "tool_use":
                            idx = next_tool_index
                            next_tool_index += 1
                            tool_indexes[int(item.get("index", idx))] = idx
                            yield {"choices": [{"delta": {"tool_calls": [{"index": idx, "id": block.get("id"), "function": {"name": block.get("name"), "arguments": ""}}]}, "finish_reason": None}]}
                    elif kind == "content_block_delta":
                        delta = item.get("delta") or {}
                        if delta.get("type") == "text_delta":
                            shaped = {"content": delta.get("text", "")}
                        elif delta.get("type") == "thinking_delta":
                            block = anthropic_reasoning_blocks.setdefault(
                                int(item.get("index", 0)), {"type": "thinking", "thinking": "", "signature": ""},
                            )
                            piece = str(delta.get("thinking") or "")
                            block["thinking"] += piece
                            shaped = {"reasoning_content": piece}
                        elif delta.get("type") == "signature_delta":
                            block = anthropic_reasoning_blocks.setdefault(
                                int(item.get("index", 0)), {"type": "thinking", "thinking": "", "signature": ""},
                            )
                            block["signature"] += str(delta.get("signature") or "")
                            shaped = {}
                        elif delta.get("type") == "input_json_delta":
                            idx = tool_indexes.get(int(item.get("index", -1)))
                            shaped = {"tool_calls": [{"index": idx, "function": {"arguments": delta.get("partial_json", "")}}]} if idx is not None else {}
                        else:
                            shaped = {}
                        if shaped:
                            yield {"choices": [{"delta": shaped, "finish_reason": None}]}
                    elif kind == "message_delta":
                        usage = item.get("usage") or {}
                        shaped_usage = {
                            "input_tokens": usage.get("input_tokens", input_tokens),
                            "output_tokens": usage.get("output_tokens"),
                            "cache_read_input_tokens": usage.get("cache_read_input_tokens", cache_read),
                            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", cache_creation),
                        }
                        yield {
                            "choices": [{"delta": {
                                "reasoning_details": list(anthropic_reasoning_blocks.values()),
                            }, "finish_reason": item.get("delta", {}).get("stop_reason")}],
                            "usage": shaped_usage,
                        }
            else:
                for raw in response.iter_lines():
                    # SSE allows "data:" without the space; some relays send it that way.
                    if not raw.startswith("data:"):
                        continue
                    data = raw[5:].lstrip()
                    if data == "[DONE]":
                        break
                    try:
                        yield json.loads(data)
                    except ValueError:
                        continue
        finally:
            try:
                response.close()
            finally:
                if on_response is not None:
                    on_response(None)
