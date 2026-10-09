"""Drive durable Observer batches after their source captures receive HTTP ACKs."""

from __future__ import annotations

from collections import Counter
from typing import Any

import structlog

log = structlog.get_logger()


class MemoryObserverDrain:
    """Capture-tick worker logic; task scheduling remains owned by server lifespan."""

    def __init__(self, observer: Any, facade: Any, *,
                 intent_bridge: Any = None, automation_engine: Any = None) -> None:
        self.observer = observer
        self.facade = facade
        self.end_sessions: set[str] = set()
        self.active_session: str | None = None
        # F3-B2：统一意图（带时间条件）→ 既有 AutomationEngine 的真实建任务链路。
        # 可选注入 —— 未注入时行为与从前完全一致（评测/既有调用方零影响）。
        self.intent_bridge = intent_bridge
        self.automation_engine = automation_engine

    def note_session_started(self, session_id: str) -> None:
        session = str(session_id or "").strip()
        if not session:
            return
        if self.active_session and self.active_session != session:
            self.end_session(self.active_session)
        self.active_session = session

    def end_session(self, session_id: str) -> None:
        session = str(session_id or "").strip()
        if not session:
            return
        # Persist before this signal can be delayed behind any in-flight model call.
        self.observer.mark_session_ended(session)
        self.end_sessions.add(session)

    def end_active_session(self) -> None:
        if self.active_session:
            self.end_session(self.active_session)

    async def drain_once(self) -> None:
        """Resume ACKED source work; only release a batch on a complete HTTP ACK."""
        sessions = set(self.observer.pending_sessions())
        sessions.update(self.end_sessions)
        for session_id in sorted(sessions):
            ended = session_id in self.end_sessions
            stage = "resume"
            processed_any = False
            try:
                context = self.facade.default_context(runtime_session_id=session_id)
                batch = await self.observer.resume(
                    session_id, context=context, session_ended=ended,
                )
                if ended:
                    self.end_sessions.discard(session_id)
                while batch is not None:
                    stage = "observe_http_ack"
                    if batch.payload is not None:
                        ack = await self.facade.observe_batch(batch.payload)
                        expected = len(batch.payload.get("observations") or [])
                        receipts = ack.get("receipts") if isinstance(ack, dict) else None
                        expected_sources = Counter(
                            str(item.get("source_event_id") or "")
                            for item in batch.payload.get("observations") or []
                            if isinstance(item, dict)
                        )
                        receipt_sources = Counter(
                            str(item.get("source_event_id") or "")
                            for item in receipts or [] if isinstance(item, dict)
                        )
                        if (
                            not isinstance(ack, dict)
                            or int(ack.get("accepted", -1)) != expected
                            or not isinstance(receipts, list)
                            or len(receipts) != expected
                            or not expected_sources
                            or "" in expected_sources
                            or receipt_sources != expected_sources
                        ):
                            raise RuntimeError(
                                "MemoryOS observe response receipts did not match every derived source_event_id"
                            )
                    processed_any = True
                    stage = "observer_outbox_ack"
                    batch = await self.observer.ack_batch(batch.batch_id)
                # 只有本轮真落了新观察才查意图 —— 空 tick 不产生额外记忆读开销。
                if self.intent_bridge is not None and processed_any:
                    stage = "intent_bridge_persist"
                    await self._persist_intents(session_id)
            except Exception as exc:  # noqa: BLE001 — keep pending batch for the next capture tick
                log.exception(
                    "memory.observer_drain_failed", session_id=session_id,
                    stage=stage, error=str(exc),
                )

    async def _persist_intents(self, session_id: str) -> None:
        """ACK 后把带时间条件的 ACTIVE 统一意图投影成真实 Automation（F3-B2）。

        只处理**时间 cue** 意图（``due_at``/time cue）—— 事件 cue 意图的事件分发
        点未统一，桥侧会拒绝并如实返回 ``event_cue_not_wired``（不假装成功）。
        幂等：automation_id = ``um-intent-<intent_id>`` + 同正文同时间去重，同一
        意图重放不产生第二条记录。
        """
        try:
            listing = await self.facade.list_records(facet="INTENT", status="ACTIVE")
        except Exception as exc:  # noqa: BLE001 — 记忆读不可用不阻塞采集 ACK
            log.warning("memory.intent_bridge_list_failed", session_id=session_id,
                        error=str(exc))
            return
        items = listing.get("items") if isinstance(listing, dict) else None
        for intent in items or []:
            if not isinstance(intent, dict):
                continue
            try:
                result = await self.intent_bridge.persist_automation_for_intent(
                    intent, engine=self.automation_engine)
            except Exception as exc:  # noqa: BLE001 — 单条失败不阻塞其余意图
                log.warning("memory.intent_bridge_persist_failed",
                            session_id=session_id,
                            intent_id=intent.get("intent_id"), error=str(exc))
                continue
            if result.get("created"):
                log.info("memory.intent_bridge_automation_created",
                         session_id=session_id, intent_id=result.get("intent_id"),
                         automation_id=result.get("automation_id"))
