"""MemoryOS front-door adapter.

One stable memory interface for Atlas consumers (agent, hub, endpoints). The
homegrown :class:`~atlas.memory.MemoryStore` is the current backing
implementation and stays fully in charge of storage; a future external
MemoryOS implementation would replace only this file's internals, not its
callers.

unified-memory (T01.2, authority-map 1.0): 生产当前无人构造本 Adapter；统一记忆
优先路径经 :class:`~atlas.memory.unified_facade.UnifiedMemoryFacade` 与
``MemoryStore(..., unified=facade)`` 委托点生效 —— MEMORY_AUTHORITY 写方法在
unified 存在时不再本地落库，而走 /v1/unified/observe|corrections（见
``core/atlas/memory/__init__.py`` 逐方法注释）。本文件保持既有组合语义不变，
不强行为统一记忆重写（T01.3 组合接线时再统一入口）。

First-class sections: identity, commitments, project state, decisions, and
raw session recall.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from atlas.memory import MemoryStore


class MemoryOSAdapter:
    """Compose MemoryStore primitives into the Atlas memory contract."""

    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    # ----- identity -----

    async def set_identity(self, key: str, value: str, confidence: float = 1.0) -> None:
        await self.store.set_fact(
            f"identity:{key}", value, category="identity", confidence=confidence,
            memory_type="identity",
        )

    async def get_identity(self, key: str) -> str | None:
        return await self.store.get_fact(f"identity:{key}")

    async def list_identity(self) -> list[dict[str, Any]]:
        return [
            fact for fact in await self.store.list_facts()
            if fact.get("memory_type") == "identity"
        ]

    # ----- commitments -----

    async def add_commitment(
        self, key: str, value: str, source_conversation_id: str | None = None,
    ) -> None:
        await self.store.set_fact(
            f"commitment:{key}", value, category="commitments",
            source_conversation_id=source_conversation_id, memory_type="commitment",
        )

    async def fulfill_commitment(self, key: str, source_message_id: str) -> bool:
        return await self.store.set_commitment_status(
            f"commitment:{key}", "fulfilled", source_message_id,
        )

    async def cancel_commitment(self, key: str, source_message_id: str) -> bool:
        return await self.store.set_commitment_status(
            f"commitment:{key}", "cancelled", source_message_id,
        )

    async def active_commitments(self) -> list[dict[str, Any]]:
        return [
            fact for fact in await self.store.list_facts()
            if fact.get("memory_type") == "commitment"
            and fact.get("commitment_status") == "active"
        ]

    async def commitment_history(self, key: str) -> list[dict[str, Any]]:
        return await self.store.list_commitment_history(f"commitment:{key}")

    # ----- project state -----

    async def set_project_state(self, project_id: str, state: str) -> None:
        await self.store.set_fact(
            f"project-state:{project_id}", state, category="project-state",
        )

    async def get_project_state(self, project_id: str) -> str | None:
        return await self.store.get_fact(f"project-state:{project_id}")

    # ----- decisions -----

    async def record_decision(
        self,
        summary: str,
        rationale: str = "",
        project_id: str | None = None,
        source_conversation_id: str | None = None,
    ) -> str:
        decision_id = str(uuid.uuid4())
        payload = json.dumps({
            "decision_id": decision_id,
            "project_id": project_id,
            "summary": summary,
            "rationale": rationale,
        }, ensure_ascii=False)
        await self.store.set_fact(
            f"decision:{decision_id}", payload, category="decisions",
            source_conversation_id=source_conversation_id,
        )
        return decision_id

    async def project_decisions(self, project_id: str) -> list[dict[str, Any]]:
        decisions = []
        for fact in await self.store.list_facts(category="decisions"):
            try:
                payload = json.loads(fact.get("value") or "{}")
            except (TypeError, ValueError):
                continue
            if isinstance(payload, dict) and payload.get("project_id") == project_id:
                decisions.append(payload)
        return decisions

    # ----- raw recall -----

    async def session_search(
        self, query: str, limit: int = 8, context: int = 2,
        conversation_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        return await self.store.session_search(
            query, limit=limit, context=context, conversation_ids=conversation_ids,
        )
