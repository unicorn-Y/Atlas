"""Run a read-only, live-provider smoke test through Atlas's W0 chat path.

Run from the repository root with its normal Python environment, for example:

    uv run --project core python core/scripts/w0_live_smoke.py --data-dir C:/AtlasData

This script reads Atlas configuration and credentials but never persists settings,
conversation history, or route-probe results.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import traceback
from pathlib import Path
from types import SimpleNamespace
from typing import Any


SYSTEM_PROMPT = (
    "You are Atlas, participating in a live integration smoke test. "
    "Follow the user's instructions exactly and keep answers concise."
)
TOOL_DEFINITION = [{
    "type": "function",
    "function": {
        "name": "get_time",
        "description": "Return the fixed fixture time for this smoke test.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}]
FIXED_TIME = "Atlas fixture time: 09:41 UTC on 2030-01-02."


def _new_read_only_model_manager() -> Any:
    """Delegate to Atlas routing while suppressing its optional settings writes."""
    from atlas.models import ModelManager

    class _Manager(ModelManager):
        def set_api_mode_probe(self, provider_id: str, probe: dict[str, Any]) -> None:
            # ModelRouter normally persists this optimization in user settings.
            # A smoke run must not write configuration.
            return None

        def credential_pool(self, provider_id: str) -> None:
            # Credential-pool retry rotation persists key status to settings.
            # Keep route selection and normal transport retry behavior active,
            # but don't allow the live probe to update credential state.
            return None

    return _Manager()


def _configure_data_dir(data_dir: str | None) -> None:
    if data_dir:
        os.environ["ATLAS_DATA_DIR"] = str(Path(data_dir).expanduser().resolve())

    # Atlas's normal load_config() creates a starter file when atlas.toml is
    # absent. Seed its singleton with an in-memory empty config in that case so
    # this read-only utility can never create files as a side effect.
    from atlas import config

    if not config.CONFIG_PATH.is_file():
        config._config = config.AtlasConfig()


def _find_model(manager: Any, model_id: str) -> dict[str, Any] | None:
    return next((
        item for item in manager.list_models()
        if str(item.get("id")) == model_id
        or str(item.get("litellm_model")) == model_id
    ), None)


def _has_reasoning_replay(messages: list[dict[str, Any]]) -> bool:
    for message in messages:
        if message.get("role") != "assistant":
            continue
        if message.get("reasoning_content") or message.get("reasoning"):
            return True
        details = message.get("reasoning_details")
        if isinstance(details, list) and any(
            isinstance(block, dict) and block.get("type") == "thinking"
            for block in details
        ):
            return True
        content = message.get("content")
        if isinstance(content, list) and any(
            isinstance(block, dict) and block.get("type") == "thinking"
            for block in content
        ):
            return True
    return False


def _request_carries_reasoning(route: Any, messages: list[dict[str, Any]]) -> bool:
    """Check reasoning fields in the provider-specific request passed by router."""
    provider = str(getattr(route, "provider", "")).lower()
    api_mode = str(getattr(route, "api_mode", ""))
    if api_mode == "anthropic_messages":
        for message in messages:
            if message.get("role") != "assistant":
                continue
            details = message.get("reasoning_details")
            if isinstance(details, list) and any(
                isinstance(block, dict) and block.get("type") == "thinking"
                for block in details
            ):
                return True
            content = message.get("content")
            if isinstance(content, list) and any(
                isinstance(block, dict) and block.get("type") == "thinking"
                for block in content
            ):
                return True
        return False

    model = str(getattr(route, "wire_model", "") or getattr(route, "model", "")).lower()
    supports_reasoning_content = "deepseek" in provider or "deepseek" in model
    return supports_reasoning_content and any(
        message.get("role") == "assistant" and bool(message.get("reasoning_content"))
        for message in messages
    )


def _http_error(exc: BaseException) -> tuple[int | None, str | None]:
    current: Any = exc
    seen: set[int] = set()
    for _ in range(8):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        response = getattr(current, "response", None)
        if response is not None:
            status = getattr(response, "status_code", None)
            try:
                status = int(status) if status is not None else None
            except (TypeError, ValueError):
                status = None
            body: str | None = None
            try:
                body = response.text
            except Exception:
                content = getattr(response, "content", None)
                if content is not None:
                    body = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else str(content)
            return status, body[:500] if body is not None else None
        current = getattr(current, "__cause__", None) or getattr(current, "__context__", None)
    return None, None


def _usage_cache_values(usage: Any) -> tuple[Any, Any]:
    if not isinstance(usage, dict):
        return None, None
    details = usage.get("input_tokens_details") or usage.get("prompt_tokens_details") or {}
    cached = next((usage.get(key) for key in (
        "cached_tokens", "cache_read_input_tokens", "cache_read",
    ) if usage.get(key) is not None), None)
    if cached is None and isinstance(details, dict):
        cached = next((details.get(key) for key in (
            "cached_tokens", "cache_read_input_tokens", "cache_read",
        ) if details.get(key) is not None), None)
    return cached, usage.get("cache_read", details.get("cache_read") if isinstance(details, dict) else None)


async def _complete(agent: Any, model_id: str, messages: list[dict[str, Any]], label: str) -> Any:
    from atlas.kernel.model_call import complete_stream

    attempts: list[dict[str, Any]] = []
    raw_errors: list[BaseException] = []
    reasoning_replay_by_attempt: list[bool] = []
    router = agent._model_router
    original_stream = router.stream

    def capture_stream_error(*args: Any, **kwargs: Any) -> Any:
        if len(args) >= 2:
            reasoning_replay_by_attempt.append(_request_carries_reasoning(args[0], args[1]))
        try:
            return original_stream(*args, **kwargs)
        except BaseException as exc:
            raw_errors.append(exc)
            raise

    # Observe the real router transport so provider HTTP status and response body
    # remain available even when complete_stream classifies and wraps an error.
    router.stream = capture_stream_error

    def on_attempt(event: dict[str, Any]) -> None:
        attempts.append(dict(event))

    replay = _has_reasoning_replay(messages)
    try:
        result = await complete_stream(
            agent,
            model_id,
            messages,
            TOOL_DEFINITION if label == "第 1 轮工具请求" else [],
            on_attempt=on_attempt,
            retry_source="foreground",
        )
    except BaseException as exc:
        print(f"\n[{label}] 异常：", flush=True)
        traceback.print_exception(type(exc), exc, exc.__traceback__)
        status, body = _http_error(raw_errors[-1]) if raw_errors else _http_error(exc)
        if status is not None:
            print(f"HTTP 状态：{status}", flush=True)
        if body is not None:
            print(f"HTTP 响应体前 500 字：{body}", flush=True)
        if not attempts:
            attempts.append({"ok": False, "model": model_id, "provider": "unknown"})
        _print_attempts(label, attempts, reasoning_replay_by_attempt, raw_errors)
        raise
    finally:
        router.stream = original_stream

    _print_attempts(label, attempts, reasoning_replay_by_attempt, raw_errors)
    print(f"  最终文本前 100 字：{(result.text or '')[:100]}", flush=True)
    return result


def _print_attempts(
    label: str,
    attempts: list[dict[str, Any]],
    reasoning_replay_by_attempt: list[bool],
    raw_errors: list[BaseException],
) -> None:
    retried = len(attempts) > 1 or any(bool(item.get("retry")) for item in attempts)
    successful_models = {str(item.get("model")) for item in attempts if item.get("ok")}
    switched = len(successful_models) > 1
    print(f"\n[{label}] 重试={retried} 切换模型={switched}", flush=True)
    for index, event in enumerate(attempts):
        replay = reasoning_replay_by_attempt[index] if index < len(reasoning_replay_by_attempt) else False
        usage = event.get("usage") if event.get("ok") else {}
        cached_tokens, cache_read = _usage_cache_values(usage)
        status = event.get("status")
        http = "SUCCESS" if event.get("ok") else (f"FAIL {status}" if status else "FAIL")
        print(
            f"  attempt={event.get('attempt', index + 1)} provider={event.get('provider', 'unknown')} "
            f"model={event.get('model', 'unknown')} HTTP={http} "
            f"retry={bool(event.get('retry'))} retry_kind={event.get('retry_kind') or '-'} "
            f"cached_tokens={cached_tokens} cache_read={cache_read} "
            f"reasoning_replay={replay}",
            flush=True,
        )
        if not event.get("ok"):
            raw_index = min(index, len(raw_errors) - 1)
            if raw_errors:
                raw_status, body = _http_error(raw_errors[raw_index])
                if raw_status is not None:
                    print(f"    provider HTTP 状态={raw_status}", flush=True)
                if body is not None:
                    print(f"    provider 响应体前 500 字={body}", flush=True)


def _assistant_message(result: Any) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": result.text or ""}
    if result.tool_calls:
        message["tool_calls"] = result.tool_calls
    if result.reasoning_content:
        message["reasoning_content"] = result.reasoning_content
    if result.reasoning_details:
        message["reasoning_details"] = result.reasoning_details
    return message


async def _run(args: argparse.Namespace) -> None:
    _configure_data_dir(args.data_dir)

    from atlas.models import ModelManager

    manager = _new_read_only_model_manager()
    model_id = args.model or manager.current_model
    if not _find_model(manager, model_id):
        raise ValueError(f"Atlas 配置中没有模型路由：{model_id}")
    agent = SimpleNamespace(_model_router=manager.model_router, source="foreground")

    first_messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            "请先调用 get_time 工具，然后只用工具返回值简短回答我。"
        )},
    ]
    tool_result = await _complete(agent, model_id, first_messages, "第 1 轮工具请求")
    if not tool_result.tool_calls:
        raise RuntimeError("模型没有调用 get_time 工具，工具调用冒烟失败")

    conversation = list(first_messages)
    conversation.append(_assistant_message(tool_result))
    for call in tool_result.tool_calls:
        function = call.get("function") or {}
        if function.get("name") != "get_time":
            raise RuntimeError(f"模型调用了意外工具：{function.get('name')!r}")
        conversation.append({
            "role": "tool",
            "tool_call_id": call.get("id") or "get_time-call",
            "name": "get_time",
            "content": FIXED_TIME,
        })

    first_answer = await _complete(agent, model_id, conversation, "第 1 轮工具结果回答")
    conversation.append(_assistant_message(first_answer))
    conversation.append({
        "role": "user",
        "content": "基于上一轮，精确复述 get_time 工具返回的日期和时间。",
    })

    second_answer = await _complete(agent, model_id, conversation, "第 2 轮上下文问题")
    print(f"\n最终文本（每次最多 100 字）：", flush=True)
    for label, result in (
        ("第 1 轮工具调用", tool_result),
        ("第 1 轮回答", first_answer),
        ("第 2 轮回答", second_answer),
    ):
        print(f"  {label}: {(result.text or '')[:100]}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="通过 Atlas W0 真实模型路径运行两轮冒烟对话。")
    parser.add_argument("--model", help="覆盖 Atlas 默认模型路由（模型 ID）")
    parser.add_argument("--data-dir", help="Atlas 数据目录；缺省沿用 Atlas 自身默认解析")
    args = parser.parse_args()
    try:
        asyncio.run(_run(args))
    except BaseException as exc:
        traceback.print_exception(type(exc), exc, exc.__traceback__)
        reason = str(exc).strip() or type(exc).__name__
        print(f"LIVE SMOKE FAIL: {reason}", flush=True)
        return 1
    print("LIVE SMOKE PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
