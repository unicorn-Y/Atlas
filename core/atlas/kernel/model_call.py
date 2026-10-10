# Ported from openai/codex@806d9732c974bc8a51b8317c1bd8985544fe627c: codex-rs/core/src/responses_retry.rs (Apache-2.0)
# SPDX-License-Identifier: Apache-2.0
"""Routed streaming model calls with bounded recovery and partial response retention."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


@dataclass(slots=True)
class ModelCallResult:
    text: str
    tool_calls: list[dict[str, Any]]
    usage: dict[str, Any]
    attempts: int
    duration_ms: int
    model: str
    provider: str


@dataclass(slots=True)
class _ToolDelta:
    call_id: str = ""
    name: str = ""
    arguments: str = ""


class ModelCallError(RuntimeError):
    def __init__(self, detail: str, *, category: str, status: int | None = None,
                 retryable: bool = False) -> None:
        super().__init__(detail)
        self.category = category
        self.status = status
        self.retryable = retryable


def _get(value: Any, key: str, default: Any = None) -> Any:
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def _overlap_merge(old: str, new: str) -> str:
    """Merge a restarted stream without dropping its already observed prefix."""
    if not old:
        return new
    if not new or old.startswith(new):
        return old
    if new.startswith(old):
        return new
    limit = min(len(old), len(new))
    for size in range(limit, 0, -1):
        if old.endswith(new[:size]):
            return old + new[size:]
    return old + new


def _status(exc: BaseException) -> int | None:
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    if value is None:
        value = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def classify_error(exc: BaseException) -> tuple[str, bool, int | None]:
    status = _status(exc)
    text = str(exc).lower()
    name = type(exc).__name__.lower()
    if status in {429, 529} or "overload" in text or "rate limit" in text:
        return "overloaded", True, status
    if status in {408, 425} or "timeout" in name or "timed out" in text:
        return "timeout", True, status
    if status is not None and (status >= 500 or status in {409}):
        return "provider", True, status
    if any(marker in name or marker in text for marker in (
        "connection", "connecterror", "incompleteread", "streamclosed", "remoteprotocol",
    )):
        return "connection", True, status
    return "model", False, status


def _retry_after(exc: BaseException) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    raw = headers.get("Retry-After") if headers is not None else None
    try:
        return max(0.0, min(float(raw), 60.0)) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _stream_next(stream: Any) -> tuple[bool, Any]:
    try:
        return True, next(stream)
    except StopIteration:
        return False, None


def _choice_delta(chunk: Any) -> tuple[Any, Any, Any]:
    choices = _get(chunk, "choices") or []
    if not choices:
        return None, None, _get(chunk, "usage")
    choice = choices[0]
    delta = _get(choice, "delta") or _get(choice, "message") or {}
    return _get(delta, "content"), _get(delta, "tool_calls"), _get(chunk, "usage")


def _usage_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            result = dump(exclude_none=True)
            if isinstance(result, dict):
                return result
        except Exception:
            pass
    fields = (
        "prompt_tokens", "completion_tokens", "input_tokens", "output_tokens",
        "total_tokens", "prompt_tokens_details", "completion_tokens_details",
        "input_tokens_details", "output_tokens_details", "cache_read_input_tokens",
        "cache_creation_input_tokens",
    )
    result = {}
    for key in fields:
        try:
            item = getattr(value, key, None)
        except Exception:
            continue
        if item is not None:
            result[key] = item.model_dump(exclude_none=True) if callable(
                getattr(item, "model_dump", None)
            ) else item
    return result


def _merge_delta(previous: str, piece: str) -> str:
    if not piece:
        return previous
    return _overlap_merge(previous, piece)


def _tool_calls(values: dict[int, _ToolDelta]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index in sorted(values):
        item = values[index]
        if not item.name:
            continue
        try:
            arguments = json.loads(item.arguments or "{}")
        except (TypeError, ValueError) as exc:
            raise ModelCallError(
                f"Model returned incomplete arguments for tool {item.name}",
                category="malformed_response", retryable=True,
            ) from exc
        if not isinstance(arguments, dict):
            raise ModelCallError(
                f"Model returned non-object arguments for tool {item.name}",
                category="malformed_response", retryable=True,
            )
        result.append({"id": item.call_id or f"call-{uuid.uuid4().hex}",
                       "name": item.name, "args": arguments})
    return result


def _wire_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep SessionDB identity/compaction metadata out of provider request messages."""
    allowed = {
        "role", "content", "tool_calls", "tool_call_id", "name", "refusal",
        "reasoning", "reasoning_content", "reasoning_details",
    }
    result = []
    for message in messages:
        wire = {key: value for key, value in message.items() if key in allowed}
        if wire.get("role") == "tool" and not wire.get("name") and message.get("tool_name"):
            wire["name"] = message["tool_name"]
        result.append(wire)
    return result


async def complete_stream(
    agent: Any,
    model_id: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    *,
    reasoning_effort: str | None = None,
    max_output_tokens: int | None = None,
    cancel_event: asyncio.Event | None = None,
    max_retries: int = 2,
    fallback_models: list[str] | None = None,
    on_text: Callable[[str], Awaitable[None] | None] | None = None,
    on_attempt: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
    usage_budget: Any = None,
) -> ModelCallResult:
    """Stream one model response through Atlas ModelRouter and Hermes transport."""
    from agent.auxiliary_client import call_llm
    from atlas.agent.fallback_cooldown import cool, is_cooling
    from atlas.models.tokens import estimate_tokens

    router = agent._model_router
    candidates = [model_id, *(fallback_models or [])]
    candidates = list(dict.fromkeys(str(item) for item in candidates if item))
    max_retries = max(0, min(int(max_retries), 8))
    combined_text = ""
    accumulated_tools: dict[int, _ToolDelta] = {}
    last_error: ModelCallError | None = None
    total_attempts = 0
    overall_started = time.monotonic()
    last_route: Any = None
    last_usage: dict[str, Any] = {}

    for candidate_index, candidate in enumerate(candidates):
        if candidate_index and is_cooling(candidate):
            continue
        try:
            route = await router.resolve(candidate, "conversation")
        except Exception as exc:
            last_error = ModelCallError(str(exc), category="route", retryable=False)
            if candidate_index + 1 < len(candidates):
                continue
            raise last_error from exc
        last_route = route
        wire_model = route.wire_model or route.model
        route_started = time.monotonic()

        for retry_index in range(max_retries + 1):
            if cancel_event is not None and cancel_event.is_set():
                raise asyncio.CancelledError
            total_attempts += 1
            request_id = uuid.uuid4().hex
            estimated = max(1, estimate_tokens(
                json.dumps(messages, ensure_ascii=False, default=str), model=wire_model,
            ))
            if usage_budget is not None and not usage_budget.reserve(
                request_id, estimated, purpose="conversation",
                model=route.model_id or candidate, wire_model=wire_model,
            ):
                raise ModelCallError("Run input-token budget reached", category="budget")
            stream = None
            attempt_text = ""
            attempt_tools: dict[int, _ToolDelta] = {}
            attempt_usage: dict[str, Any] = {}
            attempt_started = time.monotonic()
            main_runtime = {
                "provider": route.provider, "model": wire_model,
                "base_url": route.base_url, "api_key": route.key,
                "api_mode": route.api_mode, "disable_provider_retries": usage_budget is not None,
            }
            try:
                kwargs: dict[str, Any] = {
                    "task": "conversation", "provider": route.provider, "model": wire_model,
                    "base_url": route.base_url, "api_key": route.key,
                    "api_mode": route.api_mode, "main_runtime": main_runtime,
                    "messages": _wire_messages(messages), "tools": tools or None, "stream": True,
                    "stream_options": {"include_usage": True},
                }
                if max_output_tokens:
                    kwargs["max_tokens"] = max_output_tokens
                if reasoning_effort:
                    kwargs["reasoning_config"] = {"effort": reasoning_effort}
                stream = await asyncio.to_thread(call_llm, **kwargs)
                if hasattr(stream, "choices"):
                    chunks = iter((stream,))
                else:
                    chunks = iter(stream)
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise asyncio.CancelledError
                    next_task = asyncio.create_task(asyncio.to_thread(_stream_next, chunks))
                    if cancel_event is None:
                        has_chunk, chunk = await next_task
                    else:
                        cancel_task = asyncio.create_task(cancel_event.wait())
                        done, _ = await asyncio.wait(
                            {next_task, cancel_task}, return_when=asyncio.FIRST_COMPLETED,
                        )
                        if cancel_task in done and cancel_event.is_set():
                            close = getattr(stream, "close", None)
                            if callable(close):
                                await asyncio.to_thread(close)
                            next_task.cancel()
                            await asyncio.gather(next_task, return_exceptions=True)
                            raise asyncio.CancelledError
                        cancel_task.cancel()
                        await asyncio.gather(cancel_task, return_exceptions=True)
                        has_chunk, chunk = await next_task
                    if not has_chunk:
                        break
                    text_delta, tool_deltas, usage = _choice_delta(chunk)
                    if usage is not None:
                        attempt_usage = _usage_dict(usage)
                    if text_delta is not None:
                        piece = str(text_delta)
                        attempt_text += piece
                        merged = _merge_delta(combined_text, attempt_text)
                        if merged.startswith(combined_text) and len(merged) > len(combined_text):
                            delta = merged[len(combined_text):]
                            combined_text = merged
                            if on_text is not None:
                                published = on_text(delta)
                                if asyncio.iscoroutine(published):
                                    await published
                    if isinstance(tool_deltas, list):
                        for delta in tool_deltas:
                            index = int(_get(delta, "index", 0) or 0)
                            current = attempt_tools.setdefault(index, _ToolDelta())
                            function = _get(delta, "function") or {}
                            current.call_id += str(_get(delta, "id") or "")
                            current.name += str(_get(function, "name") or "")
                            current.arguments += str(_get(function, "arguments") or "")
                    if on_attempt is not None:
                        # This callback is intentionally request-level; callers log
                        # only completed attempts and retry boundaries.
                        pass
                for index, delta in attempt_tools.items():
                    current = accumulated_tools.setdefault(index, _ToolDelta())
                    current.call_id = _merge_delta(current.call_id, delta.call_id)
                    current.name = _merge_delta(current.name, delta.name)
                    current.arguments = _merge_delta(current.arguments, delta.arguments)
                last_usage = attempt_usage or last_usage
                duration_ms = int((time.monotonic() - overall_started) * 1000)
                result = ModelCallResult(
                    combined_text, _tool_calls(accumulated_tools), last_usage,
                    total_attempts, duration_ms, route.model_id or candidate, route.provider,
                )
                if usage_budget is not None:
                    usage_row = _usage_row(result, request_id, wire_model, estimated)
                    usage_row["usage_available"] = bool(
                        last_usage and any(key in last_usage for key in (
                            "prompt_tokens", "input_tokens", "completion_tokens", "output_tokens",
                        ))
                    )
                    usage_budget.record(usage_row)
                if on_attempt is not None:
                    event = {"ok": True, "attempt": total_attempts,
                             "model": route.model_id or candidate,
                             "provider": route.provider,
                             "duration_ms": int((time.monotonic() - attempt_started) * 1000),
                             "usage": last_usage}
                    published = on_attempt(event)
                    if asyncio.iscoroutine(published):
                        await published
                return result
            except asyncio.CancelledError:
                if usage_budget is not None:
                    usage_budget.release(request_id)
                raise
            except BaseException as exc:
                if usage_budget is not None:
                    usage_budget.record({
                        "request_id": request_id, "purpose": "conversation",
                        "model": route.model_id or candidate, "wire_model": wire_model,
                        "usage_available": False, "input_tokens": None,
                    })
                category, retryable, status = classify_error(exc)
                error = exc if isinstance(exc, ModelCallError) else ModelCallError(
                    str(exc), category=category, status=status, retryable=retryable,
                )
                last_error = error
                if status in {429, 529}:
                    cool(route.model_id or candidate, 60.0)
                if on_attempt is not None:
                    event = {"ok": False, "attempt": total_attempts,
                             "model": route.model_id or candidate,
                             "provider": route.provider, "category": error.category,
                             "status": error.status,
                             "duration_ms": int((time.monotonic() - attempt_started) * 1000),
                             "retry": bool(error.retryable and retry_index < max_retries)}
                    published = on_attempt(event)
                    if asyncio.iscoroutine(published):
                        await published
                if not error.retryable or retry_index >= max_retries:
                    break
                delay = _retry_after(exc)
                delay = delay if delay is not None else min(30.0, 0.5 * (2 ** retry_index))
                if cancel_event is not None:
                    try:
                        await asyncio.wait_for(cancel_event.wait(), timeout=delay)
                        raise asyncio.CancelledError
                    except asyncio.TimeoutError:
                        pass
                else:
                    await asyncio.sleep(delay)
            finally:
                if stream is not None:
                    close = getattr(stream, "close", None)
                    if callable(close):
                        try:
                            await asyncio.to_thread(close)
                        except Exception:
                            pass
        if last_error and last_error.status not in {429, 529} and candidate_index + 1 >= len(candidates):
            break

    if last_error is not None:
        raise last_error
    raise ModelCallError("No available model route", category="route")


def _usage_row(result: ModelCallResult, request_id: str, wire_model: str,
               estimated_input_tokens: int) -> dict[str, Any]:
    usage = result.usage
    input_tokens = usage.get("prompt_tokens", usage.get("input_tokens", usage.get("input", 0)))
    output_tokens = usage.get("completion_tokens", usage.get("output_tokens", usage.get("output", 0)))
    try:
        input_tokens = max(0, int(input_tokens or 0))
        output_tokens = max(0, int(output_tokens or 0))
    except (TypeError, ValueError):
        input_tokens = output_tokens = 0
    return {
        "request_id": request_id, "purpose": "conversation", "model": result.model,
        "provider": result.provider, "wire_model": wire_model,
        "input_tokens": input_tokens or estimated_input_tokens,
        "output_tokens": output_tokens,
        "context_tokens": input_tokens or estimated_input_tokens,
        "duration_ms": result.duration_ms,
        **{key: value for key, value in usage.items()
           if key not in {"prompt_tokens", "completion_tokens", "input_tokens", "output_tokens"}
           and isinstance(value, (str, int, float, bool))},
    }
