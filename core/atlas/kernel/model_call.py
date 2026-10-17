# Ported from openai/codex@6c0c6759d0617d7670826b61aca0a931bbb6db1f: codex-rs/core/src/responses_retry.rs (Apache-2.0)
# Claude Code v2.1.296 retry settings are modeled from https://code.claude.com/docs/en/env-vars.
# SPDX-License-Identifier: Apache-2.0
"""Routed streaming model calls with classified retries and partial response retention."""

from __future__ import annotations

import asyncio
import json
import math
import os
import random
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
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


_RATE_LIMIT_RETRY_RE = re.compile(
    r"try again in\s*(\d+(?:\.\d+)?)\s*(s|ms|seconds?)", re.IGNORECASE,
)


def _retry_environment(
    max_retries: int | None,
    retry_watchdog: bool | None,
    retry_watchdog_max_wait_s: float | None,
    overloaded_retry_base_delay_s: float | None,
) -> tuple[int, bool, float | None, float]:
    watchdog = (
        os.environ.get("CLAUDE_CODE_RETRY_WATCHDOG") == "1"
        if retry_watchdog is None else bool(retry_watchdog)
    )
    env_retry_count: int | None = None
    if max_retries is None:
        try:
            raw_retries = os.environ.get("CLAUDE_CODE_MAX_RETRIES")
            if raw_retries is not None:
                parsed_retries = float(raw_retries.replace("_", ""))
                if (
                    math.isfinite(parsed_retries)
                    and parsed_retries >= 0
                    and parsed_retries.is_integer()
                ):
                    env_retry_count = int(parsed_retries)
        except (TypeError, ValueError, OverflowError):
            pass
        retries = env_retry_count if env_retry_count is not None else (300 if watchdog else 10)
        if env_retry_count is not None and not watchdog:
            retries = min(retries, 15)
    else:
        retries = max(0, int(max_retries))

    if retry_watchdog_max_wait_s is None:
        try:
            raw_wait_ms = os.environ.get("CLAUDE_CODE_RETRY_WATCHDOG_MAX_WAIT_MS", "")
            wait_ms = int(raw_wait_ms) if raw_wait_ms.isdigit() else 0
            max_wait = wait_ms / 1000 if wait_ms > 0 else None
        except (TypeError, ValueError, OverflowError):
            max_wait = None
    else:
        try:
            value = float(retry_watchdog_max_wait_s)
            max_wait = value if math.isfinite(value) and value > 0 else None
        except (TypeError, ValueError, OverflowError):
            max_wait = None

    if overloaded_retry_base_delay_s is None:
        try:
            raw_base_ms = os.environ.get("CLAUDE_CODE_OVERLOADED_RETRY_BASE_DELAY_MS", "")
            base_ms = int(raw_base_ms) if raw_base_ms.isdigit() else 0
            base_delay = base_ms / 1000 if 500 <= base_ms <= 32000 else 0.5
        except (TypeError, ValueError, OverflowError):
            base_delay = 0.5
    else:
        try:
            value = float(overloaded_retry_base_delay_s)
            base_delay = value if math.isfinite(value) and 0.5 <= value <= 32.0 else 0.5
        except (TypeError, ValueError, OverflowError):
            base_delay = 0.5
    return retries, watchdog, max_wait, base_delay


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
    if limit < 8:
        return old + new
    for size in range(limit, 7, -1):
        if old.endswith(new[:size]):
            return old + new[size:]
    return old + new


def _status(exc: BaseException) -> int | None:
    current: Any = exc
    seen: set[int] = set()
    for _ in range(4):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        response = _get(current, "response")
        for value in (
            _get(response, "status_code"), _get(response, "status"), _get(current, "status_code"),
            _get(current, "status"), _get(current, "http_status"),
        ):
            try:
                if value is not None:
                    return int(value)
            except (TypeError, ValueError):
                continue
        current = _get(current, "__cause__") or _get(current, "__context__")
    match = re.search(r"\b(?:http|status|code|error)[-_\s:]*([45]\d{2})\b", str(exc).lower())
    if match:
        try:
            return int(match.group(1))
        except (TypeError, ValueError):
            pass
    return None


def _error_text(exc: BaseException) -> str:
    parts: list[str] = [str(exc)]
    current: Any = exc
    seen: set[int] = set()
    for _ in range(4):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        parts.append(type(current).__name__)
        for key in ("message", "body", "code", "type", "error", "detail"):
            try:
                value = _get(current, key)
                if value is None:
                    continue
                if isinstance(value, (dict, list, tuple)):
                    parts.append(json.dumps(value, ensure_ascii=False, default=str))
                else:
                    parts.append(str(value))
            except Exception:
                continue
        response = _get(current, "response")
        try:
            response_text = _get(response, "text")
            if response_text:
                parts.append(str(response_text))
        except Exception:
            pass
        current = _get(current, "__cause__") or _get(current, "__context__")
    return " ".join(parts).lower()


def classify_error(exc: BaseException) -> tuple[str, bool, int | None]:
    status = _status(exc)
    text = _error_text(exc)
    name = type(exc).__name__.lower()
    if status == 413 or any(marker in text for marker in (
        "context_length_exceeded", "context_window_exceeded", "context_length_error",
        "context window", "context length", "maximum context", "prompt is too long",
        "prompt_too_long", "input is too long", "too many tokens", "request_too_large",
    )):
        return "context_window_exceeded", False, status
    if any(marker in text for marker in (
        "content_filter", "content filter", "safety filter", "content was blocked",
        "content policy", "moderation_blocked", "blocked by policy",
    )):
        return "content_filter", True, status
    if status == 402 or any(marker in text for marker in (
        "insufficient_quota", "credit_balance_exhausted", "spend_limit_exceeded",
        "usage_limit_reached", "billing_error", "billing limit", "spend limit",
        "usage limit", "credit balance is too low", "insufficient balance",
        "quota exhausted", "exceeded your current quota",
    )):
        return "billing", False, status
    if status in {401, 403} or any(marker in text for marker in (
        "authentication_error", "invalid_api_key", "unauthorized", "permission_denied",
        "authentication failed",
    )):
        return "authentication", False, status
    if status == 404 or any(marker in text for marker in (
        "model_not_found", "model not found", "unknown model",
    )):
        return "model_not_found", False, status
    if status == 429 or any(marker in text for marker in (
        "rate_limit_error", "rate_limit_exceeded", "rate limit", "too many requests",
        "slow_down", "http 429", "(429)", "429",
    )):
        return "rate_limit", True, status or 429
    if status == 529 or "overload" in text or "server_is_overloaded" in text:
        return "overloaded", True, status
    if status in {408, 425, 504} or "timeout" in name or "timed out" in text:
        return "timeout", True, status
    if status is not None and (status >= 500 or status == 409):
        return "provider", True, status
    if any(marker in name or marker in text for marker in (
        "connection", "connecterror", "incompleteread", "streamclosed", "remoteprotocol",
        "network", "unexpected eof", "server disconnected", "connection reset", "broken pipe",
        "incomplete chunked read", "streamerror", "response stream",
        # A TLS stream cut mid-response (relay dropped it): httpx.ReadError with
        # "[SSL: RECORD_LAYER_FAILURE]" / "EOF occurred in violation of protocol".
        "readerror", "writeerror", "[ssl", "record layer", "eof occurred",
    )):
        return "connection", True, status
    if status in {400, 422}:
        return "invalid_request", False, status
    return "model", False, status


def _retry_after_value(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            numeric = float(value)
            return max(0.0, numeric) if math.isfinite(numeric) else None
        except (TypeError, ValueError, OverflowError):
            return None
    seconds = getattr(value, "total_seconds", None)
    if callable(seconds):
        try:
            numeric = float(seconds())
            return max(0.0, numeric) if math.isfinite(numeric) else None
        except (TypeError, ValueError, OverflowError):
            return None
    raw = str(value).strip()
    try:
        numeric = float(raw)
        return max(0.0, numeric) if math.isfinite(numeric) else None
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        retry_at = parsedate_to_datetime(raw)
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max(0.0, retry_at.timestamp() - time.time())
    except (TypeError, ValueError, OverflowError, IndexError):
        return None


def _retry_after(exc: BaseException) -> float | None:
    status = _status(exc)
    reset_headers = (
        "anthropic-ratelimit-requests-reset",
        "anthropic-ratelimit-tokens-reset",
        "anthropic-ratelimit-input-tokens-reset",
        "anthropic-ratelimit-output-tokens-reset",
        "anthropic-priority-input-tokens-reset",
        "anthropic-priority-output-tokens-reset",
    )
    current: Any = exc
    seen: set[int] = set()
    for _ in range(4):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        response = _get(current, "response")
        headers = _get(response, "headers")
        raw = None
        if headers is not None:
            try:
                raw = headers.get("Retry-After")
                if raw is None:
                    raw = headers.get("retry-after")
                if raw is None and callable(getattr(headers, "items", None)):
                    raw = next((value for key, value in headers.items()
                                if str(key).lower() == "retry-after"), None)
            except Exception:
                raw = None
        delay = _retry_after_value(raw)
        if delay is not None:
            return delay
        if status in {429, 529} and headers is not None:
            try:
                items = headers.items() if callable(getattr(headers, "items", None)) else ()
                lowered = {str(key).lower(): value for key, value in items}
                for header in reset_headers:
                    reset = lowered.get(header)
                    if reset is None:
                        continue
                    try:
                        reset_at = datetime.fromisoformat(str(reset).strip().replace("Z", "+00:00"))
                        if reset_at.tzinfo is None:
                            reset_at = reset_at.replace(tzinfo=timezone.utc)
                        return max(0.0, reset_at.timestamp() - time.time())
                    except (TypeError, ValueError, OverflowError):
                        continue
            except Exception:
                pass
        delay = _retry_after_value(_get(current, "retry_after"))
        if delay is not None:
            return delay
        current = _get(current, "__cause__") or _get(current, "__context__")
    match = _RATE_LIMIT_RETRY_RE.search(_error_text(exc))
    if match:
        try:
            value = float(match.group(1))
            return max(0.0, value / 1000 if match.group(2).lower() == "ms" else value)
        except (TypeError, ValueError, OverflowError):
            pass
    return None


def _backoff(retry_index: int) -> float:
    """Codex's shared 200 ms exponential backoff with up to 10% jitter."""
    base = 0.2 * (2 ** max(0, retry_index))
    return base * random.uniform(0.9, 1.1)


def _overloaded_backoff(retry_index: int, base_delay_s: float) -> float:
    """Claude Code's documented 500 ms exponential start for 529 responses."""
    return min(300.0, base_delay_s * (2 ** min(max(0, retry_index), 16)))


async def _publish(
    callback: Callable[[dict[str, Any]], Awaitable[None] | None] | None,
    event: dict[str, Any],
) -> None:
    if callback is None:
        return
    published = callback(event)
    if asyncio.iscoroutine(published):
        await published


def _choice_auxiliary_delta(chunk: Any) -> tuple[str, str]:
    choices = _get(chunk, "choices") or []
    if not choices:
        return "", ""
    delta = _get(choices[0], "delta") or _get(choices[0], "message") or {}
    reasoning = _get(delta, "reasoning_content") or _get(delta, "reasoning") or ""
    if isinstance(reasoning, (list, tuple)):
        pieces = []
        for item in reasoning:
            item_type = str(_get(item, "type") or "").lower()
            if item_type in {"reasoning.text", "text", "summary_text"}:
                value = _get(item, "text") or _get(item, "content") or ""
                if isinstance(value, str):
                    pieces.append(value)
        reasoning = "".join(pieces)
    if not isinstance(reasoning, str):
        reasoning = ""
    refusal = _get(delta, "refusal") or ""
    return reasoning, refusal if isinstance(refusal, str) else ""


def _env_seconds(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) and value > 0 else default


def _stream_limits() -> tuple[float, float]:
    """(first chunk, idle between chunks) seconds before a silent stream is abandoned and retried.

    The first limit covers prefill of a long uncached prompt; the idle limit catches a
    relay that stops sending mid-response (seen: 297s of silence, then a TLS error).
    """
    return (_env_seconds("ATLAS_MODEL_FIRST_CHUNK_TIMEOUT", 180.0),
            _env_seconds("ATLAS_MODEL_STREAM_IDLE_TIMEOUT", 90.0))


def _discard_task(task: "asyncio.Task[Any]") -> None:
    """Let an abandoned stream read finish in its thread without an unretrieved-exception warning."""
    task.add_done_callback(lambda done: done.cancelled() or done.exception())


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


def _repair_arguments(raw: str) -> dict[str, Any] | None:
    """Best-effort repair of a broken JSON object; None when it cannot be trusted.

    Only closed objects are repaired (bad escapes, trailing commas, quote styles). An
    object that never closes was cut off, and "repairing" it would silently run the
    call with truncated content, e.g. write half a file.
    """
    if not raw.rstrip().endswith("}"):
        return None
    try:
        import json_repair
    except ImportError:
        return None
    try:
        repaired = json_repair.loads(raw)
    except Exception:
        return None
    return repaired if isinstance(repaired, dict) and repaired else None


def _endpoint(base_url: Any) -> str:
    """host:port of a provider URL (no path, query or credentials)."""
    from urllib.parse import urlsplit

    try:
        parts = urlsplit(str(base_url or ""))
        host = parts.hostname or ""
        return f"{host}:{parts.port}" if parts.port else host
    except ValueError:
        return ""


def _arg_diagnostics(raw: str, exc: Exception, finish_reason: str | None,
                     endpoint: str) -> dict[str, Any]:
    """Structure-only facts about broken arguments, for finding the cause in run logs.

    Never includes argument text: only sizes, the json module's fixed error wording,
    the class of the final character, the finish reason and the endpoint host:port.
    """
    stripped = raw.rstrip()
    last = stripped[-1:] if stripped else ""
    tail = ("close_brace" if last == "}" else "quote" if last == '"' else
            "backslash" if last == "\\" else "comma" if last == "," else
            "empty" if not last else "other")
    return {
        "length": len(raw),
        "error_kind": str(getattr(exc, "msg", type(exc).__name__))[:60],
        "error_pos": getattr(exc, "pos", None),
        "tail": tail,
        "finish_reason": finish_reason or "",
        "endpoint": endpoint,
    }


def _tool_calls(values: dict[int, _ToolDelta], *, truncated: bool = False,
                finish_reason: str | None = None, endpoint: str = "") -> list[dict[str, Any]]:
    """Parse streamed tool calls without discarding the whole response for one bad call.

    Broken arguments are repaired when possible (``args_repaired``). A call that cannot
    be repaired, or whose arguments were cut off by the output limit, comes back with
    ``arg_error`` so the kernel answers it with a tool error and the model resends just
    that call. Both carry ``arg_diag`` (structure only) for the run log.
    """
    result: list[dict[str, Any]] = []
    ordered = [index for index in sorted(values) if values[index].name]
    for position, index in enumerate(ordered):
        item = values[index]
        call: dict[str, Any] = {"id": item.call_id or f"call-{uuid.uuid4().hex}",
                                "name": item.name, "args": {}}
        raw = item.arguments or "{}"
        cut_off = truncated and position == len(ordered) - 1
        try:
            arguments = json.loads(raw)
        except (TypeError, ValueError) as exc:
            call["arg_diag"] = _arg_diagnostics(raw, exc, finish_reason, endpoint)
            arguments = None if cut_off else _repair_arguments(raw)
            if arguments is None:
                call["arg_error"] = (
                    f"The arguments for {item.name} were cut off by the output length limit "
                    f"after {len(raw)} characters, so the call was not run. Resend it with "
                    "smaller content: split a large file into several edits or appends."
                    if cut_off else
                    f"The arguments for {item.name} were not valid JSON ({exc}), so the call "
                    "was not run. Resend this call with valid JSON arguments; if the content "
                    "is large, split it into several smaller calls."
                )
                result.append(call)
                continue
            call["args_repaired"] = True
        if not isinstance(arguments, dict):
            call["arg_error"] = (
                f"The arguments for {item.name} must be a JSON object, so the call was not run. "
                "Resend it with an object of named arguments."
            )
        else:
            call["args"] = arguments
        result.append(call)
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
    max_retries: int | None = None,
    fallback_models: list[str] | None = None,
    on_text: Callable[[str], Awaitable[None] | None] | None = None,
    on_attempt: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
    on_event: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
    unbounded_connection_retries: bool = True,
    retry_watchdog: bool | None = None,
    retry_watchdog_max_wait_s: float | None = None,
    overloaded_retry_base_delay_s: float | None = None,
    usage_budget: Any = None,
) -> ModelCallResult:
    """Stream one model response through Atlas ModelRouter and HTTPX transport."""
    from atlas.agent.fallback_cooldown import cool, is_cooling
    from atlas.models.tokens import estimate_tokens

    router = agent._model_router
    candidates = [model_id, *(fallback_models or [])]
    candidates = list(dict.fromkeys(str(item) for item in candidates if item))
    max_retries, retry_watchdog, retry_watchdog_max_wait_s, overloaded_retry_base_delay_s = (
        _retry_environment(
            max_retries, retry_watchdog, retry_watchdog_max_wait_s,
            overloaded_retry_base_delay_s,
        )
    )
    combined_text = ""
    combined_reasoning = ""
    combined_refusal = ""
    request_messages = list(messages)
    content_filter_guidance_added = False
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
        retry_index = 0
        connection_retry_count = 0
        connection_retry_delay = 5.0
        overloaded_retry_count = 0
        watchdog_capacity_wait_s = 0.0

        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise asyncio.CancelledError
            total_attempts += 1
            request_id = uuid.uuid4().hex
            estimated = max(1, estimate_tokens(
                json.dumps(request_messages, ensure_ascii=False, default=str), model=wire_model,
            ))
            if usage_budget is not None and not usage_budget.reserve(
                request_id, estimated, purpose="conversation",
                model=route.model_id or candidate, wire_model=wire_model,
            ):
                raise ModelCallError("Run input-token budget reached", category="budget")
            stream = None
            attempt_text = ""
            attempt_reasoning = ""
            attempt_refusal = ""
            attempt_tools: dict[int, _ToolDelta] = {}
            attempt_usage: dict[str, Any] = {}
            finish_reason: str | None = None
            attempt_started = time.monotonic()
            first_token_ms: int | None = None
            got_chunk = False
            first_chunk_limit, idle_limit = _stream_limits()
            try:
                kwargs: dict[str, Any] = {
                    "tools": tools or None, "stream": True,
                    "stream_options": {"include_usage": True},
                }
                if max_output_tokens:
                    kwargs["max_tokens"] = max_output_tokens
                if reasoning_effort:
                    kwargs["reasoning_config"] = {"effort": reasoning_effort}
                stream = await asyncio.to_thread(
                    router.stream, route, _wire_messages(request_messages), **kwargs,
                )
                if hasattr(stream, "choices"):
                    chunks = iter((stream,))
                else:
                    chunks = iter(stream)
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise asyncio.CancelledError
                    next_task = asyncio.create_task(asyncio.to_thread(_stream_next, chunks))
                    waiters: set[asyncio.Task[Any]] = {next_task}
                    cancel_task = None
                    if cancel_event is not None:
                        cancel_task = asyncio.create_task(cancel_event.wait())
                        waiters.add(cancel_task)
                    limit = idle_limit if got_chunk else first_chunk_limit
                    done, _ = await asyncio.wait(
                        waiters, timeout=limit, return_when=asyncio.FIRST_COMPLETED,
                    )
                    if cancel_task is not None and cancel_task in done and cancel_event.is_set():
                        close = getattr(stream, "close", None)
                        if callable(close):
                            await asyncio.to_thread(close)
                        next_task.cancel()
                        await asyncio.gather(next_task, return_exceptions=True)
                        raise asyncio.CancelledError
                    if cancel_task is not None:
                        cancel_task.cancel()
                        await asyncio.gather(cancel_task, return_exceptions=True)
                    if next_task not in done:
                        # The read is blocked in a worker thread; leave it to the socket's own
                        # backstop timeout and retry now instead of waiting on a dead stream.
                        _discard_task(next_task)
                        stream = None
                        raise ModelCallError(
                            f"Model stream stalled: no data for {int(limit)}s "
                            f"({'before the first chunk' if not got_chunk else 'mid-response'})",
                            category="timeout", retryable=True,
                        )
                    has_chunk, chunk = next_task.result()
                    got_chunk = True
                    if not has_chunk:
                        break
                    choices = _get(chunk, "choices") or []
                    if choices:
                        terminal_reason = _get(choices[0], "finish_reason")
                        if terminal_reason is not None:
                            finish_reason = str(terminal_reason).lower()
                    text_delta, tool_deltas, usage = _choice_delta(chunk)
                    reasoning_delta, refusal_delta = _choice_auxiliary_delta(chunk)
                    if first_token_ms is None and (text_delta or reasoning_delta or tool_deltas):
                        first_token_ms = int((time.monotonic() - attempt_started) * 1000)
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
                            await _publish(on_event, {
                                "type": "text_delta", "delta": delta, "attempt": total_attempts,
                            })
                    if reasoning_delta:
                        attempt_reasoning += reasoning_delta
                        merged = _merge_delta(combined_reasoning, attempt_reasoning)
                        if merged.startswith(combined_reasoning) and len(merged) > len(combined_reasoning):
                            delta = merged[len(combined_reasoning):]
                            combined_reasoning = merged
                            await _publish(on_event, {
                                "type": "reasoning_delta", "delta": delta, "attempt": total_attempts,
                            })
                    if refusal_delta:
                        attempt_refusal += refusal_delta
                        merged = _merge_delta(combined_refusal, attempt_refusal)
                        if merged.startswith(combined_refusal) and len(merged) > len(combined_refusal):
                            delta = merged[len(combined_refusal):]
                            combined_refusal = merged
                            await _publish(on_event, {
                                "type": "refusal_delta", "delta": delta, "attempt": total_attempts,
                            })
                    if isinstance(tool_deltas, list):
                        for delta in tool_deltas:
                            try:
                                index = int(_get(delta, "index", 0) or 0)
                            except (TypeError, ValueError) as exc:
                                raise ModelCallError(
                                    "Model returned an invalid tool-call index",
                                    category="malformed_response", retryable=True,
                                ) from exc
                            current = attempt_tools.setdefault(index, _ToolDelta())
                            function = _get(delta, "function") or {}
                            call_id = str(_get(delta, "id") or "")
                            name = str(_get(function, "name") or "")
                            arguments = str(_get(function, "arguments") or "")
                            if call_id and not current.call_id:
                                current.call_id = call_id
                            # Some compatible gateways repeat the full function name
                            # alongside every argument delta. Do not concatenate it.
                            if name and current.name:
                                if name == current.name:
                                    name = ""
                                elif name.startswith(current.name):
                                    name = name[len(current.name):]
                            current.name += name
                            current.arguments += arguments
                            if call_id or name or arguments:
                                await _publish(on_event, {
                                    "type": "tool_call_delta", "attempt": total_attempts,
                                    "index": index,
                                    **({"id": call_id} if call_id else {}),
                                    **({"name": name} if name else {}),
                                    **({"arguments": arguments} if arguments else {}),
                                })
                if finish_reason == "content_filter":
                    raise ModelCallError(
                        "Model response stopped by the content filter",
                        category="content_filter", retryable=True,
                    )
                if finish_reason is None:
                    raise ModelCallError(
                        "Model stream ended before a completion marker",
                        category="connection", retryable=True,
                    )
                last_usage = attempt_usage or last_usage
                duration_ms = int((time.monotonic() - overall_started) * 1000)
                result = ModelCallResult(
                    combined_text,
                    _tool_calls(attempt_tools, truncated=finish_reason in {"length", "max_tokens"},
                                finish_reason=finish_reason, endpoint=_endpoint(route.base_url)),
                    last_usage, total_attempts, duration_ms, route.model_id or candidate,
                    route.provider,
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
                             "first_token_ms": first_token_ms,
                             "reasoning_chars": len(attempt_reasoning),
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
                retry_after = _retry_after(exc)
                connection_retry = bool(
                    error.retryable and error.category == "connection"
                    and unbounded_connection_retries
                    and "bedrock" not in str(route.provider).lower()
                )
                watchdog_capacity_retry = bool(
                    error.retryable and retry_watchdog and status in {429, 529}
                    and error.category in {"rate_limit", "overloaded"}
                )
                will_retry = connection_retry or watchdog_capacity_retry or bool(
                    error.retryable and retry_index < max_retries
                )
                if watchdog_capacity_retry and retry_watchdog_max_wait_s is not None:
                    remaining_wait = retry_watchdog_max_wait_s - watchdog_capacity_wait_s
                    if remaining_wait <= 0:
                        will_retry = False

                delay = connection_retry_delay if connection_retry else retry_after
                if will_retry and delay is None:
                    if status == 529 or error.category == "overloaded":
                        delay = _overloaded_backoff(
                            overloaded_retry_count, overloaded_retry_base_delay_s,
                        )
                    else:
                        delay = _backoff(retry_index)
                if watchdog_capacity_retry and will_retry and retry_watchdog_max_wait_s is not None:
                    remaining_wait = max(0.0, retry_watchdog_max_wait_s - watchdog_capacity_wait_s)
                    delay = min(delay or 0.0, remaining_wait)
                retry_kind = (
                    "connection" if connection_retry else
                    "watchdog_capacity" if watchdog_capacity_retry and will_retry else
                    "overloaded" if status == 529 or error.category == "overloaded" else
                    "standard" if will_retry else None
                )
                retry_number = (
                    connection_retry_count + 1 if connection_retry else
                    overloaded_retry_count + 1 if status == 529 or error.category == "overloaded" else
                    retry_index + 1
                )
                if on_attempt is not None:
                    event = {"ok": False, "attempt": total_attempts,
                             "model": route.model_id or candidate,
                             "provider": route.provider, "category": error.category,
                             "status": error.status,
                             "duration_ms": int((time.monotonic() - attempt_started) * 1000),
                             "retry": will_retry,
                             "retry_kind": retry_kind,
                             "retry_number": retry_number if will_retry else None,
                             "retry_delay_s": delay,
                             "retry_after_s": retry_after}
                    published = on_attempt(event)
                    if asyncio.iscoroutine(published):
                        await published
                if not will_retry:
                    break
                if error.category == "content_filter" and not content_filter_guidance_added:
                    # Expert mode hands back "reissue it and continue"; the stock
                    # Atlas path keeps its original wording.
                    from atlas.expert_harness import filter_guidance

                    request_messages.insert(0, {
                        "role": "system",
                        "content": filter_guidance(),
                    })
                    content_filter_guidance_added = True
                assert delay is not None
                if cancel_event is not None:
                    try:
                        await asyncio.wait_for(cancel_event.wait(), timeout=delay)
                        raise asyncio.CancelledError
                    except asyncio.TimeoutError:
                        pass
                else:
                    await asyncio.sleep(delay)
                if connection_retry:
                    connection_retry_count += 1
                    connection_retry_delay = min(60.0, connection_retry_delay * 2)
                elif watchdog_capacity_retry:
                    watchdog_capacity_wait_s += delay
                    if status == 529 or error.category == "overloaded":
                        overloaded_retry_count += 1
                else:
                    retry_index += 1
                    if status == 529 or error.category == "overloaded":
                        overloaded_retry_count += 1
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
