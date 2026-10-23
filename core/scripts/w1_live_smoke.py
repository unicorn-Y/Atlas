"""Real-provider validation for W1 recovery, compaction, and session resume.

Run from the Atlas checkout with ``ATLAS_ROOT`` pointing at the private local
configuration. Credentials are read by ModelManager and are never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any


ANCHOR = "W1-CONTEXT-ANCHOR-7Q4M"


def _manager() -> Any:
    from atlas.models import ModelManager

    class ReadOnlyModelManager(ModelManager):
        def set_api_mode_probe(self, provider_id: str, probe: dict[str, Any]) -> None:
            return None

        def credential_pool(self, provider_id: str) -> None:
            return None

    return ReadOnlyModelManager()


async def _complete(agent: Any, model: str, messages: list[dict[str, Any]], *,
                    label: str, max_tokens: int = 2048) -> Any:
    from atlas.kernel.model_call import complete_stream

    attempts: list[dict[str, Any]] = []
    result = await complete_stream(
        agent, model, messages, [], max_output_tokens=max_tokens,
        max_retries=2, on_attempt=attempts.append,
    )
    print(f"{label}: model={result.model} attempts={result.attempts} "
          f"finish={result.finish_reason or 'unknown'}", flush=True)
    return result


async def _auto_compaction(agent: Any, model: str, output_dir: Path) -> tuple[list[dict[str, Any]], str]:
    from atlas.kernel.context import ContextManager

    old_override = os.environ.get("ATLAS_AUTO_COMPACT_PCT")
    os.environ["ATLAS_AUTO_COMPACT_PCT"] = "1"
    manager = ContextManager({"engine": {
        "max_output_tokens": 4096,
        "context_keep_messages": 6,
        "post_compact_read_restore_tokens": 0,
    }}, output_dir=output_dir)
    history: list[dict[str, Any]] = [{
        "role": "user", "content": f"Remember this exact project marker: {ANCHOR}. Keep it in the summary.",
    }, {"role": "assistant", "content": f"I will retain {ANCHOR}."}]
    for index in range(54):
        history.append({"role": "user", "content": f"Old discussion {index}: " +
                        (f"implementation detail {index}, compatibility notes, migration state, "
                         "edge cases and decisions. " * 45)})
        history.append({"role": "assistant", "content": f"Recorded discussion {index}; continue."})

    before_tokens = manager.warning_state(
        __import__("atlas.kernel.context", fromlist=["estimate_tokens"]).estimate_tokens(history),
        1_048_576,
    )["thresholds"]
    before_count = __import__("atlas.kernel.context", fromlist=["estimate_tokens"]).estimate_tokens(history)

    async def summarize(old: list[dict[str, Any]], prompt: str) -> str:
        result = await _complete(agent, model, [
            {"role": "system", "content": "Summarize the conversation faithfully for continuation."},
            *old,
            {"role": "user", "content": prompt},
        ], label="auto-compaction summary", max_tokens=1800)
        return result.text

    try:
        compacted = await manager.prepare(
            history, model_window=1_048_576, summarize=summarize,
            preserved={"critical_marker": ANCHOR}, focus=f"Preserve {ANCHOR} exactly.",
        )
    finally:
        if old_override is None:
            os.environ.pop("ATLAS_AUTO_COMPACT_PCT", None)
        else:
            os.environ["ATLAS_AUTO_COMPACT_PCT"] = old_override
    if compacted.method != "summary":
        raise RuntimeError(f"automatic compaction did not summarize: {compacted.method}")
    summary = next((str(item.get("content") or "") for item in compacted.messages
                    if item.get("_compressed_summary") or str(item.get("content") or "").startswith(
                        "[Conversation continuation summary]")), "")
    if ANCHOR not in summary:
        raise RuntimeError("auto-compaction summary lost the preserved marker")
    print(f"auto-compaction: before={before_count} tokens after={compacted.after_tokens} "
          f"window=1048576 thresholds=auto:{before_tokens.auto_compact},"
          f"warning:{before_tokens.warning},blocking:{before_tokens.blocking}", flush=True)
    print(f"summary first 200 chars: {summary[:200]}", flush=True)
    followup = await _complete(agent, model, [
        *compacted.messages,
        {"role": "user", "content": "What exact project marker did I ask you to remember? Reply with only the marker."},
    ], label="post-compaction recall", max_tokens=128)
    if ANCHOR not in followup.text:
        raise RuntimeError("model could not answer the pre-compaction marker question")
    print("auto-compaction recall: PASS", flush=True)
    return compacted.messages, summary


def _tool_output_clip(output_dir: Path) -> None:
    from atlas.kernel.context import ContextManager

    source = "TOOL-HEAD\n" + ("large tool evidence line. " * 3_000) + "\nTOOL-TAIL"
    manager = ContextManager(output_dir=output_dir)
    clipped = manager.clip_tool_result(source, tool_name="w1_live_fixture")
    if not clipped.output_ref or clipped.clipped_bytes >= clipped.original_bytes:
        raise RuntimeError("oversized tool output was not clipped and saved")
    if "Tool output truncated" not in clipped.content or "TOOL-HEAD" not in clipped.content \
            or "TOOL-TAIL" not in clipped.content:
        raise RuntimeError("tool output preview did not preserve head, tail, and truncation notice")
    if Path(clipped.output_ref).read_text(encoding="utf-8") != source:
        raise RuntimeError("full tool output artifact does not match original content")
    print(f"tool clipping: original={clipped.original_bytes} bytes "
          f"context={clipped.clipped_bytes} bytes ref=present", flush=True)


async def _session_recovery(agent: Any, model: str, temp_root: Path,
                            summarize: Any) -> None:
    from atlas.engine.session_sync import (
        append_session_message, append_user_message_before_model,
        append_session_messages,
        begin_session_compaction, compact_session_messages,
        read_session_model_messages, restore_session_snapshot,
    )
    from atlas.kernel.context import ContextManager

    home = temp_root / "session-db"
    session_id = "w1-live-session"
    first = f"Remember my exact deployment marker: {ANCHOR}. Confirm briefly."
    append_user_message_before_model(home, session_id, first, {"turn": 1})
    first_answer = await _complete(agent, model, [{"role": "user", "content": first}],
                                   label="session turn 1", max_tokens=128)
    append_session_message(home, session_id, "assistant", first_answer.text,
                           {"finish_reason": first_answer.finish_reason})
    second = "Explain why retaining the deployment marker matters, in one sentence."
    append_user_message_before_model(home, session_id, second, {"turn": 2})
    second_answer = await _complete(agent, model, [
        {"role": "user", "content": first},
        {"role": "assistant", "content": first_answer.text},
        {"role": "user", "content": second},
    ], label="session turn 2", max_tokens=160)
    append_session_message(home, session_id, "assistant", second_answer.text,
                           {"finish_reason": second_answer.finish_reason})

    filler_batch: list[dict[str, Any]] = []
    for index in range(8):
        filler_batch.extend((
            {"role": "user", "content": f"Deployment review note {index}: " +
             ("Keep the release plan, rollback checks, and service ownership aligned. " * 24)},
            {"role": "assistant", "content": f"Deployment review {index} recorded: " +
             ("the release remains reversible and the health check is documented. " * 24)},
        ))
    append_session_messages(home, session_id, filler_batch)

    interrupted_prompt = "I am resuming after a simulated interruption; keep the marker available."
    append_user_message_before_model(home, session_id, interrupted_prompt,
                                    {"turn": 3, "simulated_interruption": True})
    held = await asyncio.to_thread(read_session_model_messages, home, session_id)
    if len(held) != 21 or held[-1]["content"] != interrupted_prompt:
        raise RuntimeError("durable session is missing a pre-request turn or prior message")
    print(f"session interruption: persisted {len(held)} messages before the next request", flush=True)

    manager = ContextManager({"engine": {
        "context_keep_messages": 2, "max_output_tokens": 2048,
        "post_compact_read_restore_tokens": 0,
    }}, output_dir=temp_root / "session-output")
    compacted = await manager.prepare(
        held, model_window=1_048_576, summarize=summarize,
        preserved={"critical_marker": ANCHOR}, focus=f"Preserve {ANCHOR} exactly.", force=True,
    )
    if compacted.method != "summary":
        raise RuntimeError(f"session snapshot did not produce a summary: {compacted.method}")
    holder = "w1-live-compaction"
    watermark = await asyncio.to_thread(begin_session_compaction, home, session_id, holder)
    from atlas.kernel.loop import _compaction_payload

    snapshot_messages, tail_count, carried = _compaction_payload(
        compacted.messages, held, synthetic_system_prompt="", method=compacted.method,
    )
    await asyncio.to_thread(
        compact_session_messages, home, session_id, holder, watermark,
        held, snapshot_messages, tail_count=tail_count, carried_messages=carried,
        snapshot_state={"plan": {"step": "resume live smoke"},
                        "open_tool_call_ids": []},
    )
    restored = await asyncio.to_thread(restore_session_snapshot, home, session_id)
    if not restored or restored["legacy"] or restored["snapshot"]["boundary_watermark"] != watermark:
        raise RuntimeError("session snapshot boundary did not restore")
    if not any(interrupted_prompt in str(item.get("content") or "") for item in restored["messages"]):
        raise RuntimeError("post-snapshot interrupted user message was not restored")
    if restored["snapshot"]["state"].get("plan", {}).get("step") != "resume live smoke":
        raise RuntimeError("session runtime boundary state was not restored")
    resumed = await _complete(agent, model, [
        *restored["messages"],
        {"role": "user", "content": "What exact deployment marker did I ask you to remember?"},
    ], label="snapshot resume", max_tokens=128)
    if ANCHOR not in resumed.text:
        raise RuntimeError("model could not continue from the restored session snapshot")
    print(f"session recovery: snapshot + {restored['post_snapshot_count']} later messages; "
          "marker recalled: PASS", flush=True)


class _FakeHTTPError(RuntimeError):
    def __init__(self, status: int):
        super().__init__(f"local fake provider returned HTTP {status}")
        self.status_code = status
        self.response = SimpleNamespace(status_code=status, headers={})


class _FakeRouter:
    def __init__(self, scripts: dict[str, list[int | str]]):
        self.scripts = scripts
        self.calls: dict[str, int] = {}

    async def resolve(self, model: str, _purpose: str) -> Any:
        return SimpleNamespace(
            model=model, model_id=model, wire_model=model, provider="local-fixture",
            base_url="http://127.0.0.1/fake", api_mode="openai_compatible",
            credential_pool=None, key="fixture-only",
        )

    def stream(self, route: Any, _messages: Any, **_kwargs: Any) -> Any:
        model = route.model_id
        index = self.calls.get(model, 0)
        self.calls[model] = index + 1
        outcome = self.scripts.get(model, ["ok"])[min(index, len(self.scripts.get(model, ["ok"])) - 1)]
        if isinstance(outcome, int):
            raise _FakeHTTPError(outcome)
        if outcome == "timeout":
            raise TimeoutError("local fake provider timeout")
        return [
            {"choices": [{"delta": {"content": "fixture-ok"}, "finish_reason": None}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        ]


async def _fake_failure_recovery() -> None:
    from atlas.agent.fallback_cooldown import clear, is_cooling
    from atlas.kernel.model_call import ModelCallError, complete_stream

    agent = SimpleNamespace(_model_router=_FakeRouter({
        "primary": [529, 529, 529], "backup": ["ok"],
    }), source="foreground")
    previous_attempts = os.environ.get("ATLAS_MODEL_RETRY_BUDGET_ATTEMPTS")
    previous_wait = os.environ.get("ATLAS_MODEL_RETRY_BUDGET_SECONDS")
    previous_base = os.environ.get("CLAUDE_CODE_OVERLOADED_RETRY_BASE_DELAY_MS")
    os.environ["ATLAS_MODEL_RETRY_BUDGET_ATTEMPTS"] = "2"
    os.environ["ATLAS_MODEL_RETRY_BUDGET_SECONDS"] = "2"
    os.environ["CLAUDE_CODE_OVERLOADED_RETRY_BASE_DELAY_MS"] = "500"
    try:
        clear()
        events: list[dict[str, Any]] = []
        recovered = await complete_stream(
            agent, "primary", [{"role": "user", "content": "probe"}], [],
            max_retries=0, fallback_models=["backup"], on_attempt=events.append,
        )
        if recovered.model != "backup" or recovered.text != "fixture-ok":
            raise RuntimeError("local fake 529 did not retry and switch to the fallback model")
        if agent._model_router.calls.get("primary") != 3:
            raise RuntimeError("529 retry count did not honor the task-wide two-retry budget")
        if not is_cooling("primary"):
            raise RuntimeError("three consecutive 529 responses did not open the model circuit")
        print("local failure recovery: 529 retried twice, switched to backup, circuit opened", flush=True)

        clear()
        budget_agent = SimpleNamespace(_model_router=_FakeRouter({"slow": [504, 504, 504]}),
                                       source="foreground")
        os.environ["ATLAS_MODEL_RETRY_BUDGET_ATTEMPTS"] = "1"
        os.environ["ATLAS_MODEL_RETRY_BUDGET_SECONDS"] = "0.05"
        budget_events: list[dict[str, Any]] = []
        try:
            await complete_stream(
                budget_agent, "slow", [{"role": "user", "content": "probe"}], [],
                max_retries=8, on_attempt=budget_events.append,
            )
        except ModelCallError:
            pass
        else:
            raise RuntimeError("local fake timeout should end with a bounded error")
        if budget_agent._model_router.calls.get("slow") != 2:
            raise RuntimeError("global retry attempt budget did not cap repeated timeout failures")
        print("local failure recovery: 504 timeout stopped at one retry / 0.05s wait budget", flush=True)

        clear()
        rate_agent = SimpleNamespace(_model_router=_FakeRouter({"rate": [429, "ok"]}),
                                     source="foreground")
        os.environ["ATLAS_MODEL_RETRY_BUDGET_ATTEMPTS"] = "1"
        os.environ["ATLAS_MODEL_RETRY_BUDGET_SECONDS"] = "1"
        rate_events: list[dict[str, Any]] = []
        rate = await complete_stream(
            rate_agent, "rate", [{"role": "user", "content": "probe"}], [],
            max_retries=1, on_attempt=rate_events.append,
        )
        if rate.text != "fixture-ok" or rate_agent._model_router.calls.get("rate") != 2:
            raise RuntimeError("local fake 429 was not distinctly retried")
        print("local failure recovery: 429 classified and retried separately from 529", flush=True)
    finally:
        for key, value in (
            ("ATLAS_MODEL_RETRY_BUDGET_ATTEMPTS", previous_attempts),
            ("ATLAS_MODEL_RETRY_BUDGET_SECONDS", previous_wait),
            ("CLAUDE_CODE_OVERLOADED_RETRY_BASE_DELAY_MS", previous_base),
        ):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        clear()


async def _run(model_override: str | None) -> None:
    root_value = os.environ.get("ATLAS_ROOT")
    if not root_value:
        raise RuntimeError("ATLAS_ROOT must point at the real local test environment")
    root = Path(root_value).expanduser().resolve()
    if not root.is_dir():
        raise RuntimeError("ATLAS_ROOT directory does not exist")
    manager = _manager()
    model = model_override or manager.current_model
    if not any(item.get("id") == model or item.get("litellm_model") == model
               for item in manager.list_models()):
        raise RuntimeError(f"configured live model route not found: {model}")
    agent = SimpleNamespace(_model_router=manager.model_router, source="foreground")
    with tempfile.TemporaryDirectory(prefix="atlas-w1-live-", dir=root) as temp:
        temp_root = Path(temp)
        print(f"live provider: configured route={model}", flush=True)
        _tool_output_clip(temp_root / "tool-output")
        compacted, _summary = await _auto_compaction(agent, model, temp_root / "auto-output")

        async def summarize(old: list[dict[str, Any]], prompt: str) -> str:
            result = await _complete(agent, model, [
            {"role": "system", "content": "Summarize faithfully for the next turn, briefly."},
            *old, {"role": "user", "content": prompt},
        ], label="session snapshot summary", max_tokens=2200)
            return result.text

        await _session_recovery(agent, model, temp_root, summarize)
        if not compacted:
            raise RuntimeError("automatic compaction returned an empty history")
        await _fake_failure_recovery()


def main() -> int:
    parser = argparse.ArgumentParser(description="Atlas W1 live and local-failure smoke")
    parser.add_argument("--model", help="override the configured live model route")
    args = parser.parse_args()
    try:
        asyncio.run(_run(args.model))
    except BaseException as exc:
        # Do not dump provider exceptions, request headers, or response documents.
        reason = " ".join(str(exc).split())
        reason = re.sub(r"(?i)\bsk-[A-Za-z0-9_-]+", "[REDACTED]", reason)
        reason = re.sub(
            r"(?i)(api[_-]?key|access[_-]?token|authorization|bearer)\s*[:=]\s*[^\s,;]+",
            r"\1=[REDACTED]", reason,
        )
        print(f"FAIL: {type(exc).__name__}: {reason[:500]}", flush=True)
        return 1
    print("W1 LIVE SMOKE PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
