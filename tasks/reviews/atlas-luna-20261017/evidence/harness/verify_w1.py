"""Independent W1 verification — no repo test reuse, own assertions.

Checks the 7 spec items from the taskbook against the real complete_stream().
Run:  PYTHONPATH="D:/atlas-luna-w1-20261017/core" /d/Atlas/core/.venv/Scripts/python.exe \
        D:/Temp/luna-audit-20261017/verify_main/verify_w1.py
"""
from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

from atlas.kernel import model_call
from atlas.kernel.model_call import complete_stream

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    RESULTS.append((name, ok, detail))


def _silence_backoff(mp):
    """Neutralise waiting for BOTH baseline (asyncio.sleep) and W1 (_wait_for_retry)."""
    if getattr(model_call, "_wait_for_retry", None) is not None:
        mp.setattr(model_call, "_wait_for_retry", AsyncMock())
    mp.setattr(asyncio, "sleep", AsyncMock())


class Recorder:
    """Fake gateway: records every request's model + returns scripted outcomes."""

    def __init__(self, script):
        self.script = list(script)
        self.models: list[str] = []
        self.calls = 0

    def stream(self, route, *_a, **_kw):
        self.models.append(getattr(route, "model_id", "?"))
        idx = self.calls
        self.calls += 1
        item = self.script[idx] if idx < len(self.script) else self.script[-1]
        if isinstance(item, BaseException):
            raise item

        def gen():
            for chunk in item:
                if isinstance(chunk, BaseException):
                    raise chunk
                yield chunk

        return gen()


def route_for(model_id: str):
    return SimpleNamespace(
        provider="provider-" + model_id, wire_model="wire-" + model_id, model="wire-" + model_id,
        key="", base_url="http://127.0.0.1", api_mode="chat_completions", model_id=model_id,
    )


def finished(text="ok"):
    return [{"choices": [{"delta": {"content": text}, "finish_reason": None}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]}]


def http_error(status, message="upstream error", headers=None):
    err = RuntimeError(message)
    err.response = SimpleNamespace(status_code=status, headers=headers or {})
    return err


def agent_with(rec: Recorder, model_id="model-a"):
    resolved_models = []

    async def resolve(candidate, *_args, **_kwargs):
        resolved_models.append(candidate)
        return route_for(candidate)

    router = SimpleNamespace(
        resolve=AsyncMock(side_effect=resolve),
        resolved_models=resolved_models,
        calls=0,
    )
    router.stream = rec.stream
    return SimpleNamespace(_model_router=router)


async def t1_transient_then_success(monkeypatch):
    _silence_backoff(monkeypatch)
    rec = Recorder([http_error(503, "temporarily unavailable"), finished("recovered")])
    agent = agent_with(rec)
    res = await complete_stream(agent, "model-a", [], [], max_retries=20)
    ok = rec.calls == 2 and res.text == "recovered" and set(rec.models) == {"model-a"}
    record("1 瞬断一次后同模型成功", ok, f"requests={rec.calls} models={rec.models} text={res.text!r}")


async def t2_persistent_503_capped(monkeypatch):
    _silence_backoff(monkeypatch)
    rec = Recorder([http_error(503, "upstream unavailable")] * 40)
    agent = agent_with(rec)
    try:
        # No max_retries kwarg: exercises each side's own default.
        await complete_stream(agent, "model-a", [], [])
        record("2 持续503最多3次", False, "没有抛错")
    except model_call.ModelCallError as exc:
        # Baseline has no .attempts field; use getattr so the request count is the
        # primary signal and the field check only applies when the field exists.
        attempts = getattr(exc, "attempts", None)
        ok = rec.calls == 3 and exc.status == 503 and attempts == 3 \
            and getattr(exc, "model", "") == "model-a" \
            and getattr(exc, "provider", "") == "provider-model-a"
        record("2 持续503最多3次", ok,
               f"requests={rec.calls} status={exc.status} attempts={attempts} "
               f"model={getattr(exc, 'model', None)} provider={getattr(exc, 'provider', None)}")


async def t3_permanent_no_retry(monkeypatch):
    _silence_backoff(monkeypatch)
    for status in (401, 402, 404):
        rec = Recorder([http_error(status), finished()])
        agent = agent_with(rec)
        try:
            await complete_stream(agent, "model-a", [], [], max_retries=2)
            record(f"3 {status} 不重试", False, "没有抛错")
        except model_call.ModelCallError:
            record(f"3 {status} 不重试", rec.calls == 1, f"requests={rec.calls}")


async def t4_no_model_switch(monkeypatch):
    _silence_backoff(monkeypatch)
    rec = Recorder([http_error(503, "down")] * 4)
    agent = agent_with(rec)
    router = agent._model_router
    try:
        await complete_stream(agent, "model-a", [], [], max_retries=20,
                              fallback_models=["model-b", "deepseek-v4.1-flash", "deepseek-v3"])
    except model_call.ModelCallError:
        pass
    expected_resolves = ["model-a"]
    ok = router.resolved_models == expected_resolves and rec.models == ["model-a"] * rec.calls
    record("4 失败时不请求别的模型", ok,
           f"requests={rec.calls} resolved={router.resolved_models} models={rec.models}")


async def t5_rate_limit(monkeypatch):
    _silence_backoff(monkeypatch)
    rec = Recorder([http_error(429, "slow down", {"Retry-After": "2"}), finished("ok")])
    agent = agent_with(rec)
    res = await complete_stream(agent, "model-a", [], [], max_retries=20)
    short_ok = rec.calls == 2 and res.text == "ok"

    rec2 = Recorder([http_error(429, "slow down", {"Retry-After": "60"}), finished()])
    agent2 = agent_with(rec2)
    long_ok = False
    detail = ""
    try:
        await complete_stream(agent2, "model-a", [], [], max_retries=20)
        detail = f"requests={rec2.calls} no-error"
    except model_call.ModelCallError as exc:
        ra = getattr(exc, "retry_after_s", None)
        long_ok = rec2.calls == 1 and ra == 60
        detail = f"requests={rec2.calls} retry_after_s={ra}"
    record("5 429 Retry-After 阈值", short_ok and long_ok,
           f"short(2s) requests={rec.calls} ok={short_ok}; long(60s) {detail}")


async def t6_partial_text_not_reissued(monkeypatch):
    _silence_backoff(monkeypatch)
    partial = [{"choices": [{"delta": {"content": "half answer"}, "finish_reason": None}]},
               RuntimeError("connection reset mid-stream")]
    rec = Recorder([partial, finished("duplicate")])
    agent = agent_with(rec)
    seen: list[str] = []
    try:
        await complete_stream(agent, "model-a", [], [], max_retries=20, on_text=seen.append)
    except model_call.ModelCallError:
        pass
    ok = rec.calls == 1 and "".join(seen) == "half answer"
    record("6 已有文本delta不重发", ok, f"requests={rec.calls} emitted={''.join(seen)!r}")


async def t7_tool_delta_not_reissued(monkeypatch):
    _silence_backoff(monkeypatch)
    partial = [{"choices": [{"delta": {"tool_calls": [{
        "index": 0, "id": "call-1",
        "function": {"name": "local_shell", "arguments": '{"command":"echo hi"}'}}]},
        "finish_reason": None}]},
        RuntimeError("reset after tool delta")]
    rec = Recorder([partial, finished("dup")])
    agent = agent_with(rec)
    try:
        await complete_stream(agent, "model-a", [], [], max_retries=20)
    except model_call.ModelCallError:
        pass
    record("7 工具delta后不重发", rec.calls == 1, f"requests={rec.calls}")


async def main() -> int:
    import contextlib

    class MP:
        def __init__(self):
            self.saved = []

        def setattr(self, obj, name, value):
            self.saved.append((obj, name, getattr(obj, name)))
            setattr(obj, name, value)

        def undo(self):
            for obj, name, value in reversed(self.saved):
                setattr(obj, name, value)
            self.saved.clear()

    for fn in (t1_transient_then_success, t2_persistent_503_capped, t3_permanent_no_retry,
               t4_no_model_switch, t5_rate_limit, t6_partial_text_not_reissued,
               t7_tool_delta_not_reissued):
        mp = MP()
        print(f"[start] {fn.__name__}", flush=True)
        try:
            await fn(mp)
        except Exception as exc:  # noqa: BLE001
            record(fn.__name__, False, f"EXC {type(exc).__name__}: {exc}")
        finally:
            mp.undo()

    print("\n=== W1 independent verification ===", flush=True)
    failed = 0
    for name, ok, detail in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name} :: {detail}")
        if not ok:
            failed += 1
    print(f"\n{len(RESULTS) - failed}/{len(RESULTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
