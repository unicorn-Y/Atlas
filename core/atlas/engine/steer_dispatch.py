"""Send-now steering: queue a mid-run user message and background the running tool.

Claude Code 2.1.281 parity (core-refresh-map I7): "send now" on a queued/steered
message moves the CURRENT tool call to the background instead of cancelling it, and
the run proceeds immediately to the next model turn with the user message injected.
When the running tool cannot be backgrounded, the message falls back to Atlas'
existing queued-steer behavior (delivered at the next tool-batch boundary).

Hermes source (pin 27c63095b0, MIT):
- agent/interrupt_control.py::InterruptControlMixin.redirect (tool-execution branch:
  ``steer()`` + ``request_yield`` on the tool-worker threads — never cancels);
- tools/interrupt.py::request_yield / consume_yield (per-thread yield bit);
- tools/environments/base.py + tools/terminal_tool_background.py::yield_to_background_handler
  (a foreground local terminal command adopts its live process into
  tools/process_registry.py as a notify-on-complete background session and returns
  partial output at once — backgroundable; tools without a yield handler simply
  keep running and the queued steer is delivered at the batch boundary — fallback).

server.py stays untouched: the WS ``run.steer`` handler swaps its
``_queue_run_steer(...)`` call for :func:`queue_run_steer` (see module bottom).
"""

from __future__ import annotations

import uuid
from typing import Any

__all__ = [
    "is_send_now",
    "apply_send_now",
    "apply_steer_payload",
    "queue_run_steer",
]


def is_send_now(data: Any) -> bool:
    """Whether one raw ``run.steer`` payload asks for send-now delivery."""
    return isinstance(data, dict) and bool(data.get("send_now", False))


def apply_send_now(agent: Any, text: str) -> dict[str, Any]:
    """Queue ``text`` for the next model turn and ask the running tool to yield.

    The message is always queued through ``agent.steer`` first, so a tool that
    cannot be backgrounded degrades to the existing queue behavior by
    construction. When the agent is executing tools, every active tool-worker
    thread gets a yield request: the terminal hands its live process to the
    process registry (background, never killed) and returns immediately, which
    ends the tool batch and lets the next model turn pick up the steered text.
    """
    accepted = bool(text) and bool(agent.steer(text))
    yield_requested = False
    if accepted:
        tracker = getattr(agent, "_tool_worker_threads", None)
        tracker_lock = getattr(agent, "_tool_worker_threads_lock", None)
        if (getattr(agent, "_executing_tools", False)
                and tracker is not None and tracker_lock is not None):
            from atlas.engine.tools.interrupt import request_yield

            with tracker_lock:
                worker_tids = list(tracker)
            for tid in worker_tids:
                request_yield(tid)
            yield_requested = bool(worker_tids)
    return {"accepted": accepted, "yield_requested": yield_requested}


def apply_steer_payload(agent: Any, steer: dict[str, Any]) -> dict[str, Any]:
    """Dispatch one steered message per its flags and return ``run_steered`` fields.

    ``send_now`` wins over ``immediate`` when both are set: send-now never cancels
    a model request, while ``immediate`` (redirect) aborts an in-flight request.
    Legacy payloads without ``send_now`` behave exactly as before.
    """
    text = str(steer.get("content") or steer.get("text") or "").strip()
    immediate = bool(steer.get("immediate", False))
    if is_send_now(steer):
        outcome = apply_send_now(agent, text)
        return {"text": text, "accepted": outcome["accepted"], "immediate": False,
                "send_now": True, "yield_requested": outcome["yield_requested"]}
    if immediate and text:
        accepted = bool(agent.redirect(text))
    else:
        accepted = bool(text) and bool(agent.steer(text))
    return {"text": text, "accepted": accepted, "immediate": immediate,
            "send_now": False, "yield_requested": False}


def queue_run_steer(run: Any, data: Any) -> str | None:
    """Validate one raw ``run.steer`` WS payload and enqueue it on the run.

    Drop-in superset of ``server._queue_run_steer`` with the same rejection
    reasons plus ``send_now`` validation. Wiring (one call swap in server.py's
    ``run.steer`` branch, ~line 6379):

        from atlas.engine.steer_dispatch import queue_run_steer  # import section
        reason = queue_run_steer(run, data)   # was: _queue_run_steer(
                                              #     run, data.get("content"),
                                              #     data.get("event_id"),
                                              #     data.get("immediate", False))
    """
    if not isinstance(data, dict):
        data = {}
    content = data.get("content")
    event_id = data.get("event_id")
    immediate = data.get("immediate", False)
    send_now = data.get("send_now", False)
    status = getattr(run, "status", "")
    if status in {"completed", "failed", "cancelled"}:
        return "run_not_active"
    if not isinstance(content, str) or not content.strip():
        return "invalid_content"
    if not isinstance(immediate, bool):
        return "invalid_immediate"
    if not isinstance(send_now, bool):
        return "invalid_send_now"
    run.steer_queue.put_nowait({"content": content, "event_id": str(event_id or uuid.uuid4()),
                                "immediate": immediate, "send_now": send_now})
    return None
