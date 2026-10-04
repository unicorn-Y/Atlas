"""Event / webhook 触发入口（W4）.

- ``EventTriggerManager`` 用 watchdog 监听各 automation ``trigger.event_path``
  指向的目录（递归），命中后按 per-automation 防抖（默认 2s，取
  ``trigger.event_debounce``）调 ``engine.trigger_event``。
- ``trigger_webhook(automation_id, payload)`` 同路（server 侧路由/W10 接线时调用）。

watchdog 回调来自 observer 线程：经 ``run_coroutine_threadsafe`` 桥回创建
manager 时的事件循环（``attach_triggers`` 须在事件循环内调用）。watchdog 缺席时
webhook 仍可用，仅文件监听降级关闭。
"""

from __future__ import annotations

import asyncio
import fnmatch
import time
from pathlib import Path
from typing import Any

import structlog

from atlas.automation.engine import AutomationEngine

log = structlog.get_logger()

DEFAULT_DEBOUNCE = 2.0


class EventTriggerManager:
    """Own the watchdog observer for event-triggered automations."""

    def __init__(self, engine: AutomationEngine) -> None:
        self._engine = engine
        self._observer: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._debounce: dict[str, float] = {}

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None  # webhook-only；文件监听等下次 async 上下文再 attach
        self.sync()

    def stop(self) -> None:
        observer = self._observer
        self._observer = None
        if observer is not None:
            observer.stop()

    def sync(self) -> None:
        """Rebuild watchers from the current store (called after CRUD changes)."""
        if self._loop is None:
            return
        wanted: dict[str, str] = {}
        for record in self._engine.store.list():
            trigger = record.get("trigger") or {}
            if (
                record.get("enabled")
                and not (record.get("state") or {}).get("paused_reason")
                and trigger.get("kind") == "event"
                and trigger.get("event_path")
            ):
                wanted[record["id"]] = str(Path(str(trigger["event_path"])).resolve())

        self.stop()  # 全量重建（CRUD 低频，正确性优先）
        roots = sorted({root for root in wanted.values() if Path(root).is_dir()})
        if not roots:
            return
        try:
            from watchdog.observers import Observer
        except ImportError:
            log.warning("automation.watchdog_unavailable")
            return
        observer = Observer()
        handler = _DispatchingHandler(self)
        for root in roots:
            observer.schedule(handler, root, recursive=True)
        observer.daemon = True
        observer.start()
        self._observer = observer

    # -- dispatch ------------------------------------------------------------

    def on_file_event(self, src_path: str) -> None:
        """watchdog 线程回调：匹配 automation → 防抖 → 事件循环里触发。"""
        try:
            path = str(Path(src_path).resolve())
        except OSError:
            return
        now = time.monotonic()
        matched: list[str] = []
        for record in self._engine.store.list():
            trigger = record.get("trigger") or {}
            if trigger.get("kind") != "event" or not record.get("enabled"):
                continue
            if (record.get("state") or {}).get("paused_reason"):
                continue
            try:
                root = str(Path(str(trigger.get("event_path", ""))).resolve())
                relative = Path(path).relative_to(root).as_posix()
            except (OSError, ValueError):
                continue
            pattern = str(trigger.get("event_glob") or "")
            if pattern and not fnmatch.fnmatch(relative, pattern):
                continue
            automation_id = record["id"]
            debounce = max(0.0, float(trigger.get("event_debounce") or DEFAULT_DEBOUNCE))
            if now - self._debounce.get(automation_id, 0.0) < debounce:
                continue
            self._debounce[automation_id] = now
            matched.append(automation_id)
        for automation_id in matched:
            self._submit(automation_id, path)

    def _submit(self, automation_id: str, path: str) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return

        async def _fire() -> None:
            try:
                await self._engine.trigger_event(
                    automation_id, source="event", payload={"path": path}
                )
            except Exception as exc:
                log.exception(
                    "automation.event_trigger_failed",
                    automation_id=automation_id,
                    error=str(exc),
                )

        try:
            asyncio.run_coroutine_threadsafe(_fire(), loop)
        except RuntimeError:
            pass

    async def trigger_webhook(
        self, automation_id: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Webhook 入口：与文件事件同路（去重在 engine 的 dedup id 内完成）。"""
        return await self._engine.trigger_event(
            automation_id, source="webhook", payload=payload or {}
        )


class _DispatchingHandler:
    """Minimal watchdog handler (all fs event types → manager)."""

    def __init__(self, manager: EventTriggerManager) -> None:
        self._manager = manager

    def dispatch(self, event: Any) -> None:
        if getattr(event, "is_directory", False):
            return
        if getattr(event, "event_type", "") in {"opened", "closed_no_write"}:
            return
        src = getattr(event, "dest_path", "") or getattr(event, "src_path", "")
        if src:
            self._manager.on_file_event(str(src))

    on_any_event = dispatch
    on_created = dispatch
    on_modified = dispatch
    on_moved = dispatch
    on_deleted = dispatch


def attach_triggers(engine: AutomationEngine) -> EventTriggerManager:
    """Create + start the trigger manager for an engine (call inside the loop)."""
    manager = EventTriggerManager(engine)
    manager.start()
    engine.attach_triggers(manager)
    return manager
