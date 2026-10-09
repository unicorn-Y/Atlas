"""Shared Atlas model routing over Hermes' provider transport layer.

Single entry for every Atlas LLM call: ``resolve()`` turns a model id plus a
purpose into a :class:`RouteSpec` (provider, api_mode, model, base_url, key,
credential pool), and :meth:`ModelRouter.complete` executes auxiliary requests
over Hermes' transport layer (which owns retries, fallbacks and the native
Anthropic Messages conversion). The main conversation uses
:meth:`ModelRouter.hermes_agent_kwargs` to build the pinned ``AIAgent`` with the
same route, so prompt-cache breakpoints and signed thinking survive on the
native channel.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx

from atlas.models import catalog

_MEMORY_AUXILIARY_TIMEOUT_SECONDS = 120.0
_MEMORY_AUXILIARY_PURPOSES = frozenset({"memory_observe", "memory_reflect"})
_MEMORY_LOW_REASONING_MODELS = frozenset({"gemini-3.8-flash"})


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
    # The model id the Hermes wire transport must actually send (H10.2-DEFECT-1).
    # ``model`` keeps the registry's litellm-style id (``openai/deepseek-...``);
    # the wire never sees that routing prefix — relays 404 it — so every Hermes
    # transport consumer sends ``wire_model`` (the bare/native id) instead.
    wire_model: str = ""
    model_id: str = ""


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
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
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
    """Resolve one model route and execute auxiliary requests with Hermes transports."""

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
        fallback_reason: str | None = None, wire_model: str = "",
    ) -> RouteSpec:
        return RouteSpec(
            provider=provider, api_mode=api_mode, model=model, base_url=base_url,
            key=key, credential_pool=pool, purpose=purpose, fallback_reason=fallback_reason,
            wire_model=wire_model or model, model_id=str(model_data.get("id") or ""),
        )

    async def complete(self, route: RouteSpec, messages: list[dict[str, Any]], **kwargs: Any) -> CompletionResult:
        """Run one auxiliary request over Hermes' transport layer.

        ``messages`` use the same OpenAI-internal shape every Hermes auxiliary
        caller uses (string contents, ``tool_calls`` + ``role: "tool"`` pairs).
        On an ``anthropic_messages`` route the transport converts them itself and
        preserves signed thinking supplied via the internal ``reasoning_details``
        / ``anthropic_content_blocks`` carriers plus any ``cache_control``
        breakpoints the caller placed. ``stream`` stays off: auxiliary purposes
        are single-shot text/tool answers.
        """
        from agent.auxiliary_client import call_llm

        # The Hermes transport sends ``model`` verbatim on the wire: the
        # litellm-style routing prefix in ``route.model`` never reaches a
        # provider untouched (H10.2-DEFECT-1), so auxiliary calls send
        # ``wire_model`` — the bare id the endpoint actually exposes.
        wire_model = route.wire_model or route.model
        usage_callback = kwargs.pop("usage_callback", None) or _USAGE_CALLBACK.get()
        from atlas.usage import env_run_usage_budget
        from atlas.models.tokens import estimate_tokens
        from agent.turn_usage import new_usage_request_id

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
        budget = env_run_usage_budget()
        request_text = "\n".join(str(item.get("content") or "") for item in messages)
        estimate = max(1, estimate_tokens(request_text, model=wire_model))
        if budget is not None and not budget.reserve(
            request_id, estimate, purpose=route.purpose,
            model=route.model_id or route.model, wire_model=wire_model,
        ):
            raise RuntimeError("Run input-token budget reached; the auxiliary model request was not sent.")
        try:
            response = await asyncio.to_thread(
                call_llm,
                task=route.purpose,
                provider=route.provider,
                model=wire_model,
                base_url=route.base_url,
                api_key=route.key,
                api_mode=route.api_mode,
                main_runtime={
                    "provider": route.provider,
                    "model": wire_model,
                    "base_url": route.base_url,
                    "api_key": route.key,
                    "api_mode": route.api_mode,
                    "disable_provider_retries": budget is not None,
                },
                messages=messages,
                stream=False,
                **kwargs,
            )
        except BaseException:
            if budget is not None:
                budget.release(request_id)
            raise
        text = _response_text(response)
        usage = response.get("usage") if isinstance(response, dict) else getattr(response, "usage", None)
        from agent.turn_usage import report_auxiliary_usage

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

    async def complete_for(
        self, model_id: str, purpose: str, messages: list[dict[str, Any]], **kwargs: Any,
    ) -> CompletionResult:
        route = await self.resolve(model_id, purpose)
        return await self.complete(route, messages, **kwargs)

    @staticmethod
    def hermes_agent_kwargs(route: RouteSpec) -> dict[str, Any]:
        """Kwargs accepted by the pinned Hermes AIAgent constructor, including its public pool seam.

        The agent's transport sends ``model`` verbatim on the wire (no litellm
        indirection), so the agent is pinned to ``wire_model`` — the bare id the
        endpoint exposes. Passing the registry's litellm-style id here made real
        relays 404 every conversation turn (H10.2-DEFECT-1).
        """
        return {
            "provider": route.provider,
            "model": route.wire_model or route.model,
            "base_url": route.base_url,
            "api_key": route.key,
            "api_mode": route.api_mode,
            "credential_pool": route.credential_pool,
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
