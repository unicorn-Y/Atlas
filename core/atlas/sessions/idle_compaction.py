"""Idle compaction: compact a big conversation before its prompt cache expires.

Design taken from Claude Code 2.1.299 (closed source, changelog only): a
conversation of 200K+ tokens left idle for about 54 minutes is compacted
before its one-hour prompt cache lapses, so the next message does not pay to
re-process the whole history uncached. Atlas delta: the threshold, idle window
and cache lifetime are settings (``context.idle_compaction*``) because Atlas
serves many providers with different cache lifetimes; the compaction itself is
the existing Hermes ``compact_session`` path used by ``/compact``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import structlog

log = structlog.get_logger()

_TERMINAL = {"completed", "failed", "cancelled"}
_task: asyncio.Task[None] | None = None
_done: set[str] = set()


def _settings() -> dict[str, Any]:
    from atlas.config import get_config

    config = get_config()
    return {
        "enabled": config.get("context.idle_compaction", True) is not False,
        "min_tokens": int(config.get("context.idle_compact_min_tokens", 100_000) or 100_000),
        "idle_s": int(config.get("context.idle_compact_after_s", 54 * 60) or 54 * 60),
        "cache_s": int(config.get("context.prompt_cache_ttl_s", 60 * 60) or 60 * 60),
    }


def _input_tokens(run: Any) -> int:
    best = 0
    for row in getattr(run, "usage", []) or []:
        for key in ("input_tokens", "prompt_tokens"):
            value = row.get(key) if isinstance(row, dict) else None
            if isinstance(value, (int, float)):
                best = max(best, int(value))
                break
    return best


def candidates(runs: list[Any], now: datetime, settings: dict[str, Any]) -> list[Any]:
    """Latest run per conversation that is idle inside the compaction window."""
    latest: dict[str, Any] = {}
    for run in runs:
        current = latest.get(run.conversation_id)
        if current is None or (run.updated_at or "") > (current.updated_at or ""):
            latest[run.conversation_id] = run
    picked = []
    for run in latest.values():
        if run.status not in _TERMINAL or run.run_id in _done:
            continue
        try:
            idle = (now - datetime.fromisoformat(run.updated_at)).total_seconds()
        except (TypeError, ValueError):
            continue
        if settings["idle_s"] <= idle < settings["cache_s"] and _input_tokens(run) >= settings["min_tokens"]:
            picked.append(run)
    return picked


async def _compact(conversation_id: str) -> None:
    from atlas import server
    from atlas.config import DATA_ROOT
    from atlas.engine import HermesRuntime

    memory, orchestrator = server.memory, server.orchestrator
    if memory is None or orchestrator is None:
        return
    conversation = await memory.get_conversation(conversation_id)
    if not conversation:
        return
    result = await HermesRuntime(data_dir=DATA_ROOT, model_manager=orchestrator._model_mgr).compact_session(
        conversation_id=conversation_id, workspace=conversation.get("workspace"),
        focus_topic=None, hook_store=server._hook_store(),
    )
    log.info("context.idle_compacted", conversation_id=conversation_id,
             result={key: result.get(key) for key in ("compacted", "before_tokens", "after_tokens")
                     if isinstance(result, dict) and key in result})


async def _loop() -> None:
    from atlas import server

    while True:
        await asyncio.sleep(120)
        try:
            settings = _settings()
            manager = getattr(server, "runtime_mgr", None)
            if not settings["enabled"] or manager is None:
                continue
            active = {run.conversation_id for run in manager.runs.values() if run.status not in _TERMINAL}
            for run in candidates(list(manager.runs.values()), datetime.now(UTC), settings):
                _done.add(run.run_id)
                if run.conversation_id in active:
                    continue
                try:
                    await _compact(run.conversation_id)
                except Exception:
                    log.exception("context.idle_compaction_failed", conversation_id=run.conversation_id)
        except Exception:
            log.exception("context.idle_compaction_loop_failed")


def start_idle_compaction() -> None:
    global _task
    if _task is None or _task.done():
        try:
            _task = asyncio.get_running_loop().create_task(_loop())
        except RuntimeError:
            _task = None
