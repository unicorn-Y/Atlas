# Ported from openclaw/openclaw@59cb44796b0f1f0daa0e37af8b1495abb45d9bc1: src/agents/tools/sessions-spawn-visible.ts (MIT)
# Ported from openclaw/openclaw@59cb44796b0f1f0daa0e37af8b1495abb45d9bc1: src/agents/subagents/announce/subagent-announce-active-wake.ts (MIT)
# Ported from openclaw/openclaw@59cb44796b0f1f0daa0e37af8b1495abb45d9bc1: src/agents/subagents/announce/subagent-announce-output.ts (MIT)
# Ported from openclaw/openclaw@59cb44796b0f1f0daa0e37af8b1495abb45d9bc1: src/agents/tools/sessions-send-tool.ts (MIT)
"""Independent side sessions: proposal cards, real sidebar sessions, reports.

Behaviour follows Claude Desktop's ``start_session`` contract (proposal card the
user starts, a real conversation in the sidebar that can be opened and
stopped, an automatic report to the parent when the child ends a turn,
messages between sessions, optional git worktree) on top of OpenClaw's
visible-session spawn and announce flow:

* spawn (sessions-spawn-visible.ts): the child is a normal persistent session,
  optional managed worktree, inherits the parent's workspace and permissions;
* announce (subagent-announce-*.ts): when a child turn settles, its last reply
  plus a compact stats line goes back to the requester. If the requester run is
  active the report is steered into it; otherwise the requester is woken with a
  fresh turn ("direct fallback");
* send (sessions-send-tool.ts): steer an active target, else start a follow-up
  turn in it.

Atlas delta: no second run loop or session store. A child is an Atlas
conversation driven by the same ``run.start`` path the desktop uses
(``atlas.api.run_drive._handle_run_start``) on a server-side connection, so the
desktop can attach to it later by run id, approve its requests and stop it.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

import structlog

from atlas.sessions.store import ACTIVE, SessionStore

log = structlog.get_logger()

TERMINAL_EVENTS = {"run.completed", "run.failed", "run.cancelled"}
_RUN_ACTIVE = {"running", "paused", "waiting"}
# Auto-wakes of an idle parent within this window before reports just wait
# for the parent's next turn (CCD: "after many such messages in a row ... notes
# wait for your next turn").
_WAKE_WINDOW_S = 1800
_WAKE_LIMIT = 8
_REPORT_CHARS = 4000


class _CaptureSocket:
    """Stand-in websocket for a server-side run connection.

    ``RuntimeManager.send`` delivers to it until a desktop client attaches to
    the run; it only remembers whether the run was rejected at start.
    """

    def __init__(self) -> None:
        self.first: dict[str, Any] | None = None

    async def send_json(self, data: dict[str, Any]) -> None:
        if self.first is None:
            self.first = data


def _server() -> Any:
    from atlas import server

    return server


class SessionHub:
    def __init__(self, store: SessionStore) -> None:
        self.store = store
        self._wakes: dict[str, list[float]] = {}
        # Runs that another session or a report started (not the user). A
        # turn like that may only propose new sessions, never start them.
        self.hub_run_ids: set[str] = set()
        self._listening = False
        self._lock = asyncio.Lock()

    # -- wiring --------------------------------------------------------------

    def attach(self) -> None:
        manager = getattr(_server(), "runtime_mgr", None)
        if manager is None or self._listening:
            return
        listeners = getattr(manager, "terminal_listeners", None)
        if isinstance(listeners, list):
            listeners.append(self._on_run_terminal)
            self._listening = True
            from atlas.sessions.idle_compaction import start_idle_compaction

            start_idle_compaction()

    @staticmethod
    def _manager() -> Any:
        manager = getattr(_server(), "runtime_mgr", None)
        if manager is None:
            raise RuntimeError("Atlas 运行时还没就绪")
        return manager

    @staticmethod
    def _memory() -> Any:
        memory = getattr(_server(), "memory", None)
        if memory is None:
            raise RuntimeError("Atlas 会话存储还没就绪")
        return memory

    def active_run(self, conversation_id: str) -> Any:
        manager = self._manager()
        candidates = [run for run in manager.runs.values()
                      if run.conversation_id == conversation_id and run.status in _RUN_ACTIVE]
        return candidates[-1] if candidates else None

    # -- queries ---------------------------------------------------------------

    def list(self, parent: str | None = None) -> list[dict[str, Any]]:
        items = self.store.list(parent)
        for item in items:
            self._refresh_status(item)
        return items

    def _refresh_status(self, item: dict[str, Any]) -> None:
        conversation_id = item.get("conversation_id")
        if not conversation_id or item["status"] in {"proposed", "dismissed", "expired"}:
            return
        run = self.active_run(conversation_id)
        if run is not None:
            live = "waiting" if run.status == "waiting" else "running"
            item["run_id"] = run.run_id
            item["waiting_for"] = run.waiting_for
            if item["status"] != live:
                self.store.update(item["session_id"], status=live)
                item["status"] = live
        elif item["status"] in ACTIVE:
            # The run ended while nobody listened (e.g. a service restart).
            self.store.update(item["session_id"], status="idle")
            item["status"] = "idle"

    def resolve(self, target: str, *, caller_conversation: str | None = None) -> dict[str, Any] | None:
        target = str(target or "").strip()
        if not target:
            return None
        if target in {"parent", "上级", "主会话"} and caller_conversation:
            mine = self.store.by_conversation(caller_conversation)
            if mine and mine.get("parent_conversation_id"):
                return {"session_id": "parent", "conversation_id": mine["parent_conversation_id"],
                        "title": "主会话", "name": "parent", "status": "parent"}
            return None
        record = self.store.get(target) or self.store.by_conversation(target)
        if record is None and caller_conversation:
            for item in self.store.list(caller_conversation):
                if item["name"] == target or item["title"] == target:
                    return item
        return record

    # -- lifecycle -------------------------------------------------------------

    async def propose(self, *, parent_conversation_id: str, title: str, prompt: str,
                      background: str = "", context: str = "fresh", use_worktree: bool = False,
                      name: str = "", initiation: str = "own_initiative", parent_run_id: str | None = None,
                      notify_parent: bool = True) -> dict[str, Any]:
        record = self.store.create(
            parent_conversation_id=parent_conversation_id, parent_run_id=parent_run_id,
            title=title, prompt=prompt, background=background, context=context,
            use_worktree=use_worktree, name=name or title, initiation=initiation,
            notify_parent=notify_parent, status="proposed",
        )
        await self._announce_parent(record, "proposed")
        return record

    async def start(self, session_id: str) -> dict[str, Any]:
        async with self._lock:
            record = self.store.get(session_id)
            if record is None:
                raise KeyError(session_id)
            if record["status"] != "proposed":
                return record
            self.store.update(session_id, status="starting")
        try:
            return await self._launch(session_id)
        except Exception as exc:
            log.exception("sessions.start_failed", session_id=session_id)
            failed = self.store.update(session_id, status="failed", error=str(exc)[:1000])
            await self._announce_parent(failed or record, "failed")
            raise

    async def create_and_start(self, **fields: Any) -> dict[str, Any]:
        fields["initiation"] = fields.get("initiation") or "user_asked"
        record = self.store.create(**{**fields, "status": "starting",
                                      "name": fields.get("name") or fields.get("title")})
        try:
            return await self._launch(record["session_id"])
        except Exception as exc:
            log.exception("sessions.start_failed", session_id=record["session_id"])
            self.store.update(record["session_id"], status="failed", error=str(exc)[:1000])
            raise

    async def dismiss(self, session_id: str, reason: str = "") -> dict[str, Any]:
        record = self.store.get(session_id)
        if record is None:
            raise KeyError(session_id)
        if record["status"] != "proposed":
            return record
        updated = self.store.update(session_id, status="dismissed", error=reason[:500] or None) or record
        await self._announce_parent(updated, "dismissed")
        return updated

    async def stop(self, session_id: str) -> dict[str, Any]:
        record = self.store.get(session_id) or self.store.by_conversation(session_id)
        if record is None:
            raise KeyError(session_id)
        if record["status"] == "proposed":
            return await self.dismiss(record["session_id"], "stopped before start")
        run = self.active_run(record.get("conversation_id") or "")
        if run is not None:
            # A session the user (or its parent) stopped does not report back
            # and wake anyone (CCD: stopped sessions send no note).
            self.store.update(record["session_id"],
                              hub_runs=[rid for rid in record["hub_runs"] if rid != run.run_id])
            await self._cancel_run(run)
        return self.store.update(record["session_id"], status="stopped") or record

    async def _cancel_run(self, run: Any) -> None:
        manager = self._manager()
        run.cancel_event.set()
        if run.trust_future is not None and not run.trust_future.done():
            run.trust_future.set_result(False)
        elif run.task is not None and not run.task.done():
            run.task.cancel()
        if run.task is not None:
            await asyncio.gather(run.task, return_exceptions=True)
        if not any(event.get("event") in TERMINAL_EVENTS for event in run.events):
            run.status = "cancelled"
            await manager.send_run(run, run.next_envelope("run.cancelled", {}), "")

    async def _launch(self, session_id: str) -> dict[str, Any]:
        record = self.store.get(session_id)
        assert record is not None
        memory = self._memory()
        parent_id = record.get("parent_conversation_id")
        parent = await memory.get_conversation(parent_id) if parent_id else None
        conversation_id: str
        if record["context"] == "fork" and parent:
            conversation_id = await self._fork_transcript(parent_id, record["title"])
        else:
            conversation_id = await memory.create_conversation(record["title"])
        # The child inherits the parent's place and permissions; it can never
        # be given more than the session that started it.
        inherited: dict[str, Any] = {"title": record["title"], "source": "session"}
        if parent:
            for key in ("workspace", "permission_mode", "allowed_paths", "executor", "extra_roots"):
                if parent.get(key) not in (None, "", []):
                    inherited[key] = parent[key]
        await memory.update_conversation(conversation_id, **inherited)
        self.store.update(session_id, conversation_id=conversation_id)
        content = self._first_message(record, parent)
        worktree = None
        workspace = (parent or {}).get("worktree_path") or (parent or {}).get("workspace")
        if record["use_worktree"] and workspace and not str(workspace).startswith("ssh://"):
            worktree = {"name": record["name"]}
            if (parent or {}).get("worktree_branch"):
                worktree["base_branch"] = parent["worktree_branch"]
        run_id = await self._start_run(conversation_id, content, session_id=session_id,
                                       worktree=worktree,
                                       workspace=workspace if worktree else None)
        child = await memory.get_conversation(conversation_id) or {}
        updated = self.store.update(
            session_id, status="running", last_run_id=run_id,
            worktree_path=child.get("worktree_path"), worktree_branch=child.get("worktree_branch"),
        ) or record
        await self._announce_parent(updated, "started")
        return updated

    async def _fork_transcript(self, parent_id: str, title: str) -> str:
        from atlas.config import DATA_ROOT
        from atlas.engine.session_sync import (
            atlas_turn_ordinal,
            fork_session_through_turn,
            read_session_all_messages,
        )

        memory = self._memory()
        messages = await asyncio.to_thread(read_session_all_messages, DATA_ROOT / "engine", parent_id)
        result = await memory.fork_conversation_metadata(parent_id, title=title)
        if result is None:
            raise RuntimeError("主会话不存在，没法分叉上下文")
        child_id = str(result["id"])
        if messages:
            turns = atlas_turn_ordinal(messages, str(messages[-1]["id"]), through_target=True)
            if turns:
                try:
                    await asyncio.to_thread(
                        fork_session_through_turn, DATA_ROOT / "engine", parent_id, child_id,
                        turns, branch_message_id=str(messages[-1]["id"]),
                    )
                except Exception:
                    await memory.delete_conversation(child_id)
                    raise
        return child_id

    @staticmethod
    def _first_message(record: dict[str, Any], parent: dict[str, Any] | None) -> str:
        parts = [record["prompt"].strip()]
        if record.get("background", "").strip():
            parts.append("背景（来自开启你的那个会话）：\n" + record["background"].strip())
        parent_title = (parent or {}).get("title") or "另一个会话"
        parts.append(
            f"（你是会话「{parent_title}」开出来的独立会话「{record['title']}」，句柄 {record['name']}。"
            "只做上面交给你的事，无关问题列成后续事项，不要顺手修。"
            "你每次停下来时，最后一条回复会自动回报给开启你的会话，所以把做了什么、结果在哪、还剩什么放在最后一条回复的开头。"
            "真被卡住、只有那边能回答时，用 session_send 发给 parent 一个简短问题，然后结束这一轮。）"
        )
        return "\n\n".join(part for part in parts if part)

    async def _start_run(self, conversation_id: str, content: str, *, session_id: str | None,
                         worktree: dict[str, Any] | None = None, workspace: str | None = None,
                         extra: dict[str, Any] | None = None) -> str:
        from atlas.api.run_drive import _handle_run_start

        manager = self._manager()
        run_id = str(uuid.uuid4())
        conn_id = f"session:{run_id}"
        sink = _CaptureSocket()
        manager.connections[conn_id] = sink
        data: dict[str, Any] = {"type": "run.start", "run_id": run_id,
                                "conversation_id": conversation_id, "content": content, **(extra or {})}
        if worktree:
            data["worktree"] = worktree
        if workspace:
            data["workspace"] = workspace
        try:
            await _handle_run_start(conn_id, data, manager)
        except Exception:
            manager.connections.pop(conn_id, None)
            raise
        if run_id not in manager.runs:
            manager.connections.pop(conn_id, None)
            detail = ((sink.first or {}).get("data") or {}).get("detail") or "运行没有启动"
            raise RuntimeError(str(detail))
        manager.conn_runs.setdefault(conn_id, run_id)
        self.hub_run_ids.add(run_id)
        owner = session_id or (self.store.by_conversation(conversation_id) or {}).get("session_id")
        if owner:
            # Turns the hub starts report upward when they settle; turns the
            # user drives in that session only update its status.
            self.store.add_hub_run(owner, run_id)
        return run_id

    # -- messages ------------------------------------------------------------

    async def send(self, target: str, text: str, *, from_conversation: str | None = None,
                   from_label: str = "") -> dict[str, Any]:
        record = self.resolve(target, caller_conversation=from_conversation)
        if record is None:
            raise KeyError(target)
        conversation_id = record.get("conversation_id")
        if not conversation_id:
            raise ValueError("这个会话还没开始（只是提议），先开始它再发消息")
        sender = from_label
        if not sender and from_conversation:
            mine = self.store.by_conversation(from_conversation)
            sender = f"会话「{mine['title']}」" if mine else "主会话"
        body = f"来自{sender or '另一个会话'}的消息：\n{text.strip()}"
        run = self.active_run(conversation_id)
        if run is not None:
            run.steer_queue.put_nowait({"content": body, "event_id": "session-msg:" + uuid.uuid4().hex[:12],
                                        "immediate": False})
            return {"status": "steered", "session_id": record["session_id"], "run_id": run.run_id}
        session_id = record["session_id"] if record["session_id"] != "parent" else None
        run_id = await self._start_run(conversation_id, body, session_id=session_id)
        if session_id:
            self.store.update(session_id, status="running")
        return {"status": "started", "session_id": record["session_id"], "run_id": run_id}

    # -- reporting -----------------------------------------------------------

    async def _on_run_terminal(self, run: Any, envelope: dict[str, Any]) -> None:
        try:
            await self._handle_terminal(run, envelope)
        except Exception:
            log.exception("sessions.terminal_handler_failed", run_id=getattr(run, "run_id", ""))

    async def _handle_terminal(self, run: Any, envelope: dict[str, Any]) -> None:
        manager = self._manager()
        for conn_id in [conn for conn, active in manager.conn_runs.items()
                        if active == run.run_id and conn.startswith("session:")]:
            manager.connections.pop(conn_id, None)
            manager.conn_runs.pop(conn_id, None)
        await self._redeliver_leftovers(run)
        record = self.store.by_conversation(run.conversation_id)
        if record is None:
            return
        event = envelope.get("event")
        status = {"run.completed": "idle", "run.failed": "failed", "run.cancelled": "stopped"}[event]
        report = self._report_text(run, envelope)
        stats = self._stats(run)
        hub_started = run.run_id in record["hub_runs"]
        updated = self.store.update(
            record["session_id"], status=status, last_status=event, last_report=report[:_REPORT_CHARS],
            stats=stats, last_run_id=run.run_id, unseen_report=True,
        ) or record
        if (event == "run.cancelled" or not hub_started or not updated.get("notify_parent")
                or not updated.get("parent_conversation_id")):
            # Cancelled = someone pressed stop; that is not a report to deliver.
            return
        await self._deliver_report(updated, event, report, stats)

    async def _redeliver_leftovers(self, run: Any) -> None:
        """Reports/messages steered into a run that ended before reading them
        are not lost: they start the conversation's next turn instead."""
        leftovers: list[str] = []
        kept: list[dict[str, Any]] = []
        queue = getattr(run, "steer_queue", None)
        while queue is not None and not queue.empty():
            item = queue.get_nowait()
            if str(item.get("event_id", "")).startswith(("session-report:", "session-msg:")):
                leftovers.append(str(item.get("content") or ""))
            else:
                kept.append(item)
        for item in kept:
            queue.put_nowait(item)
        if leftovers and run.status != "cancelled":
            with suppress(Exception):
                await self._start_run(run.conversation_id, "\n\n".join(leftovers), session_id=None)

    @staticmethod
    def _report_text(run: Any, envelope: dict[str, Any]) -> str:
        for item in reversed(run.events):
            if item.get("event") == "message.completed":
                text = str((item.get("data") or {}).get("content") or "").strip()
                if text:
                    return text
        detail = (envelope.get("data") or {}).get("detail")
        if detail:
            return f"（没有回复正文）{detail}"
        chunks = [str((item.get("data") or {}).get("content") or "")
                  for item in run.events if item.get("event") == "message.delta"]
        return "".join(chunks).strip() or "（这一轮没有回复正文）"

    @staticmethod
    def _stats(run: Any) -> dict[str, Any]:
        started = getattr(run, "started_at", "") or ""
        try:
            duration = (datetime.now(UTC) - datetime.fromisoformat(started)).total_seconds()
        except ValueError:
            duration = None
        usage = list(getattr(run, "usage", []) or [])

        def total(*keys: str) -> int:
            value = 0
            for row in usage:
                for key in keys:
                    if isinstance(row.get(key), (int, float)):
                        value += int(row[key])
                        break
            return value

        return {"duration_s": round(duration, 1) if duration is not None else None,
                "input_tokens": total("input_tokens", "prompt_tokens"),
                "output_tokens": total("output_tokens", "completion_tokens")}

    @staticmethod
    def _stats_line(stats: dict[str, Any]) -> str:
        duration = stats.get("duration_s")
        took = f"{int(duration // 60)} 分 {int(duration % 60)} 秒" if isinstance(duration, (int, float)) else "未知"
        tokens = (stats.get("input_tokens") or 0) + (stats.get("output_tokens") or 0)
        token_text = f"{tokens}（入 {stats.get('input_tokens') or 0} / 出 {stats.get('output_tokens') or 0}）" if tokens else "未知"
        return f"用时 {took} · tokens {token_text}"

    async def _deliver_report(self, record: dict[str, Any], event: str, report: str,
                              stats: dict[str, Any]) -> None:
        outcome = {"run.completed": "停下来了（这一轮结束）", "run.failed": "失败了",
                   "run.cancelled": "被停止了"}[event]
        excerpt = report if len(report) <= 1500 else report[:1500] + "…"
        text = (
            "<side-session-event>\n"
            f"你开的独立会话「{record['title']}」（句柄 {record['name']}，id {record['session_id']}）{outcome}。\n"
            f"它的回报：\n{excerpt}\n"
            f"{self._stats_line(stats)}\n"
            "这是它自己的报告：如果它说改了代码或文件，转告用户「已完成」前用一两步看一眼改动（diff 或关键文件）；"
            "只是答复或调研结果就直接转述，不要为核对去翻日志、数据库或别的目录。"
            "用户要的下一步若因此解锁就接着做；没有就用一两句话向用户汇报，然后结束这一轮。不要开用户没要求的新工作。\n"
            "</side-session-event>"
        )
        parent_id = record["parent_conversation_id"]
        parent_run = self.active_run(parent_id)
        await self._announce_parent(record, "report", run=parent_run, report=excerpt)
        if parent_run is not None:
            parent_run.steer_queue.put_nowait({"content": text, "event_id": "session-report:" + uuid.uuid4().hex[:12],
                                               "immediate": False})
            self.store.update(record["session_id"], unseen_report=False)
            return
        if any(self.active_run(item["conversation_id"]) is not None
               for item in self.store.list(parent_id) if item.get("conversation_id")
               and item["session_id"] != record["session_id"]):
            # Siblings still working: wake the parent once they have all settled.
            return
        now = time.monotonic()
        recent = [stamp for stamp in self._wakes.get(parent_id, []) if now - stamp < _WAKE_WINDOW_S]
        if len(recent) >= _WAKE_LIMIT:
            log.info("sessions.wake_suppressed", parent=parent_id)
            return
        recent.append(now)
        self._wakes[parent_id] = recent
        pending = [item for item in self.store.list(parent_id)
                   if item.get("unseen_report") and item["session_id"] != record["session_id"]]
        if pending:
            text += "\n" + "\n".join(
                f"<side-session-event>\n会话「{item['title']}」（{item['name']}）先前也停下了，回报：\n"
                f"{(item.get('last_report') or '')[:800]}\n</side-session-event>" for item in pending)
        try:
            await self._start_run(parent_id, text, session_id=None)
        except Exception:
            log.exception("sessions.wake_failed", parent=parent_id)
            return
        for item in [record, *pending]:
            self.store.update(item["session_id"], unseen_report=False)

    async def _announce_parent(self, record: dict[str, Any], kind: str, *, run: Any = None,
                               report: str = "") -> None:
        """Push a ``session.event`` into the parent's live run so its card updates."""
        parent_id = record.get("parent_conversation_id")
        if not parent_id:
            return
        target = run or self.active_run(parent_id)
        if target is None:
            return
        payload = {"kind": kind, "session": public(record)}
        if report:
            payload["report"] = report
        with suppress(Exception):
            await self._manager().send_run(target, target.next_envelope("session.event", payload), "")


def public(record: dict[str, Any]) -> dict[str, Any]:
    return {key: record.get(key) for key in (
        "session_id", "name", "title", "prompt", "context", "initiation", "status",
        "parent_conversation_id", "conversation_id", "use_worktree", "worktree_path",
        "worktree_branch", "last_report", "last_status", "stats", "error", "created_at",
        "updated_at", "expires_at", "run_id", "waiting_for",
    )}


_hub: SessionHub | None = None


def get_session_hub() -> SessionHub:
    global _hub
    if _hub is None:
        from atlas.config import get_config

        _hub = SessionHub(SessionStore(get_config().db_path.parent / "linked_sessions.db"))
    _hub.attach()
    return _hub
