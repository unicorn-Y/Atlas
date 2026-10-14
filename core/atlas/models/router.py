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
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Callable

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
_OLLAMA_LOCAL_BASE_URL = "http://127.0.0.1:11434/v1"


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
    # Atlas-only transport configuration; proxy credentials never appear in repr/logs.
    network_proxy_url: str | None = field(default=None, repr=False, compare=False)
    network_ca_bundle_path: str | None = field(default=None, repr=False, compare=False)


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
    from atlas.engine_core.agent.proxy_bypass import loopback_request_kwargs

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
        raw_provider = str(selected.get("hermes_provider") or selected.get("provider") or "")
        provider_id = catalog.resolve_catalog_id(raw_provider) or raw_provider
        provider_entry = catalog.get_provider(provider_id) or {}
        configured_mode = str(provider_entry.get("api_mode") or "openai")
        native_supported = configured_mode == "anthropic_messages"
        litellm_model = _model_for_provider(selected, native=False)
        native_model = _model_for_provider(selected, native=True)

        if selected.get("local_only") is True:
            # Local Ollama routes must not inherit provider/global credentials,
            # gateway endpoints, or the configured model proxy. Reject malformed
            # persisted entries instead of silently routing them elsewhere.
            if (
                provider_id != "ollama"
                or str(selected.get("base_url") or "") != _OLLAMA_LOCAL_BASE_URL
                or not litellm_model.startswith("ollama/")
                or not litellm_model.removeprefix("ollama/").strip()
            ):
                raise ValueError("Invalid local-only Ollama model route")
            return self._route(
                selected, provider_id, litellm_model, _OLLAMA_LOCAL_BASE_URL,
                None, None, "chat_completions", purpose,
                wire_model=native_model, direct_local=True,
            )

        provider_cfg = self.model_manager.provider_config(provider_id)
        provider_key = self.model_manager.resolve_api_key(provider_id)
        pool = self.model_manager.credential_pool(provider_id)
        if pool is not None:
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
        override = self.model_manager.get_api_mode_override(provider_id)

        if override == "anthropic_messages" and not native_supported:
            raise ValueError(f"Provider {provider_id} does not declare Anthropic Messages support")

        if override:
            if override == "anthropic_messages":
                use_provider_credentials = bool(provider_key)
                return self._route(
                    selected, provider_id, native_model, provider_base if use_provider_credentials else gateway_base,
                    provider_key if use_provider_credentials else gateway_key, pool if use_provider_credentials else None,
                    "anthropic_messages", purpose, wire_model=native_model,
                )
            base_url = provider_base if provider_key else gateway_base
            key = provider_key or gateway_key or None
            return self._route(
                selected, provider_id, litellm_model, base_url or None, key, pool if provider_key else None,
                self._canonical_mode(override), purpose, wire_model=native_model,
            )

        if native_supported and provider_key:
            return self._route(
                selected, provider_id, native_model, provider_base, provider_key, pool,
                "anthropic_messages", purpose, wire_model=native_model,
            )

        if native_supported and gateway_base and gateway_key:
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
            network_proxy_url=network.proxy_url,
            network_ca_bundle_path=network.ca_bundle_path,
        )

    async def complete(self, route: RouteSpec, messages: list[dict[str, Any]], **kwargs: Any) -> CompletionResult:
        """Run one auxiliary request over the same Atlas-owned HTTP transport."""
        wire_model = route.wire_model or route.model
        usage_callback = kwargs.pop("usage_callback", None) or _USAGE_CALLBACK.get()
        from atlas.usage import env_run_usage_budget
        from atlas.models.tokens import estimate_tokens
        from atlas.engine_core.agent.turn_usage import new_usage_request_id

        if route.purpose in _MEMORY_AUXILIARY_PURPOSES and kwargs.get("timeout") is None:
            kwargs["timeout"] = _MEMORY_AUXILIARY_TIMEOUT_SECONDS
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
            response = await asyncio.to_thread(_post_completion, route, messages, kwargs, network)
        except BaseException:
            if budget is not None:
                budget.release(request_id)
            raise
        text = _response_text(response)
        usage = response.get("usage") if isinstance(response, dict) else getattr(response, "usage", None)
        from atlas.engine_core.agent.turn_usage import report_auxiliary_usage

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
        )
        assert_transport_supported(network, provider=route.provider, api_mode=route.api_mode)
        return _stream_completion(route, messages, kwargs, network)

    async def complete_for(
        self, model_id: str, purpose: str, messages: list[dict[str, Any]],
        fallbacks: list[str] | None = None, **kwargs: Any,
    ) -> CompletionResult:
        candidates = [model_id, *(fallbacks or [])]
        for alt in ("deepseek-v4.1-flash", "deepseek-v3"):
            if alt not in candidates:
                candidates.append(alt)
        last_error = None
        for candidate in candidates:
            try:
                route = await self.resolve(candidate, purpose)
                return await self.complete(route, messages, **kwargs)
            except Exception as exc:
                last_error = exc
                continue
        if last_error is not None:
            raise last_error
        raise RuntimeError("No model candidates available")

    @staticmethod
    def hermes_agent_kwargs(route: RouteSpec) -> dict[str, Any]:
        """Kwargs accepted by the pinned Hermes AIAgent constructor, including its public pool seam.

        The agent's transport sends ``model`` verbatim on the wire (no litellm
        indirection), so the agent is pinned to ``wire_model`` — the bare id the
        endpoint exposes. Passing the registry's litellm-style id here made real
        relays 404 every conversation turn (H10.2-DEFECT-1).
        """
        network = ModelNetworkSettings(
            proxy_url=route.network_proxy_url,
            ca_bundle_path=route.network_ca_bundle_path,
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
    system: list[str] = []
    converted: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "user")
        content = message.get("content") or ""
        if role in {"system", "developer"}:
            system.append(str(content))
        elif role == "tool":
            converted.append({"role": "user", "content": [{
                "type": "tool_result", "tool_use_id": str(message.get("tool_call_id") or ""),
                "content": str(content),
            }]})
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
                        raise NotImplementedError("Anthropic image conversion is not supported by Atlas direct transport")
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
        payload["system"] = "\n\n".join(system)
    tools = kwargs.get("tools")
    if tools:
        payload["tools"] = [
            {"name": (tool.get("function") or {}).get("name", ""),
             "description": (tool.get("function") or {}).get("description", ""),
             "input_schema": (tool.get("function") or {}).get("parameters") or {"type": "object", "properties": {}}}
            for tool in tools
        ]
    if kwargs.get("temperature") is not None:
        payload["temperature"] = kwargs["temperature"]
    payload["stream"] = bool(kwargs.get("stream", False))
    return payload


def _openai_payload(route: RouteSpec, messages: list[dict[str, Any]], kwargs: dict[str, Any]) -> dict[str, Any]:
    if route.api_mode not in {"openai", "chat_completions"}:
        raise NotImplementedError(f"Atlas direct transport does not support API mode {route.api_mode!r}")
    payload: dict[str, Any] = {
        "model": route.wire_model or route.model,
        "messages": [
            {key: value for key, value in message.items() if key in {
                "role", "content", "tool_calls", "tool_call_id", "name", "refusal",
            }}
            for message in messages
        ],
        "stream": bool(kwargs.get("stream", False)),
    }
    for key in ("max_tokens", "max_completion_tokens", "temperature", "top_p", "stop", "stream_options", "tools", "tool_choice", "parallel_tool_calls"):
        if kwargs.get(key) is not None:
            payload[key] = kwargs[key]
    reasoning = kwargs.get("reasoning_config")
    if isinstance(reasoning, dict) and reasoning.get("effort"):
        payload["reasoning_effort"] = reasoning["effort"]
    extra = kwargs.get("extra_body")
    if isinstance(extra, dict):
        payload.update(extra)
    if isinstance(kwargs.get("extra_headers"), dict):
        payload["_atlas_headers"] = kwargs["extra_headers"]
    return payload


def _request_details(route: RouteSpec, messages: list[dict[str, Any]], kwargs: dict[str, Any]) -> tuple[str, dict[str, str], dict[str, Any]]:
    if route.api_mode == "anthropic_messages":
        url = _messages_endpoint(str(route.base_url or ""))
        headers = {
            "x-api-key": route.key or "", "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = _anthropic_payload(route, messages, kwargs)
    elif route.api_mode in {"openai", "chat_completions"}:
        url = _endpoint(route.base_url, "chat/completions")
        headers = {"content-type": "application/json"}
        if route.key:
            headers["authorization"] = f"Bearer {route.key}"
        payload = _openai_payload(route, messages, kwargs)
        headers.update(payload.pop("_atlas_headers", {}))
    else:
        raise NotImplementedError(f"Atlas direct transport does not support API mode {route.api_mode!r}")
    return url, headers, payload


def _client(route: RouteSpec, network: ModelNetworkSettings, timeout: Any) -> httpx.Client:
    if network.enabled:
        return build_model_httpx_client(network, base_url=str(route.base_url or ""), async_mode=False, timeout=timeout)
    from atlas.engine_core.agent.proxy_bypass import loopback_request_kwargs

    return httpx.Client(timeout=timeout, **loopback_request_kwargs(str(route.base_url or "")))


def _post_completion(route: RouteSpec, messages: list[dict[str, Any]], kwargs: dict[str, Any], network: ModelNetworkSettings) -> dict[str, Any]:
    timeout = kwargs.get("timeout") or httpx.Timeout(connect=15.0, read=120.0, write=30.0, pool=10.0)
    url, headers, payload = _request_details(route, messages, {**kwargs, "stream": False})
    with _client(route, network, timeout) as client:
        response = client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        if route.api_mode == "anthropic_messages" and "text/event-stream" in response.headers.get("content-type", ""):
            from types import SimpleNamespace

            blocks: dict[int, dict[str, Any]] = {}
            input_tokens = output_tokens = 0
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
                    elif delta.get("type") == "input_json_delta":
                        block["partial_json"] = str(block.get("partial_json") or "") + str(delta.get("partial_json") or "")
                elif kind == "content_block_start":
                    blocks[int(event.get("index", 0))] = dict(event.get("content_block") or {})
                elif kind == "message_start":
                    input_tokens = int(((event.get("message") or {}).get("usage") or {}).get("input_tokens") or 0)
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
                    reasoning.append({"type": "thinking", "thinking": str(block.get("thinking") or ""),
                                      "signature": str(block.get("signature") or "")})
            data = SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=text, tool_calls=tool_calls or None,
                                                                  reasoning_details=reasoning or None),
                                         finish_reason=None)],
                usage=SimpleNamespace(prompt_tokens=input_tokens, completion_tokens=output_tokens,
                                      total_tokens=input_tokens + output_tokens),
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
        )
        data = SimpleNamespace(
            choices=[SimpleNamespace(message=message, finish_reason=data.get("stop_reason"))],
            usage=usage_obj,
        )
    return data


def _stream_completion(route: RouteSpec, messages: list[dict[str, Any]], kwargs: dict[str, Any], network: ModelNetworkSettings):
    timeout = kwargs.get("timeout") or httpx.Timeout(connect=15.0, read=None, write=30.0, pool=10.0)
    url, headers, payload = _request_details(route, messages, {**kwargs, "stream": True})
    if route.api_mode == "anthropic_messages":
        payload["stream"] = True
    with _client(route, network, timeout) as client:
        with client.stream("POST", url, headers=headers, json=payload) as response:
            response.raise_for_status()
            if route.api_mode == "anthropic_messages":
                tool_indexes: dict[int, int] = {}
                next_tool_index = 0
                input_tokens = 0
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
                        input_tokens = int((item.get("message") or {}).get("usage", {}).get("input_tokens") or 0)
                    elif kind == "content_block_start":
                        block = item.get("content_block") or {}
                        if block.get("type") == "tool_use":
                            idx = next_tool_index
                            next_tool_index += 1
                            tool_indexes[int(item.get("index", idx))] = idx
                            yield {"choices": [{"delta": {"tool_calls": [{"index": idx, "id": block.get("id"), "function": {"name": block.get("name"), "arguments": ""}}]}, "finish_reason": None}]}
                    elif kind == "content_block_delta":
                        delta = item.get("delta") or {}
                        if delta.get("type") == "text_delta":
                            shaped = {"content": delta.get("text", "")}
                        elif delta.get("type") == "input_json_delta":
                            idx = tool_indexes.get(int(item.get("index", -1)))
                            shaped = {"tool_calls": [{"index": idx, "function": {"arguments": delta.get("partial_json", "")}}]} if idx is not None else {}
                        elif delta.get("type") in {"thinking_delta", "signature_delta"}:
                            raise NotImplementedError("Anthropic signed thinking streaming is not supported by Atlas direct transport")
                        else:
                            shaped = {}
                        if shaped:
                            yield {"choices": [{"delta": shaped, "finish_reason": None}]}
                    elif kind == "message_delta":
                        usage = item.get("usage") or {}
                        shaped_usage = {
                            "input_tokens": usage.get("input_tokens", input_tokens),
                            "output_tokens": usage.get("output_tokens"),
                        }
                        yield {"choices": [{"delta": {}, "finish_reason": item.get("delta", {}).get("stop_reason")}], "usage": shaped_usage}
            else:
                for raw in response.iter_lines():
                    if not raw.startswith("data: "):
                        continue
                    if raw[6:] == "[DONE]":
                        break
                    try:
                        yield json.loads(raw[6:])
                    except ValueError:
                        continue
