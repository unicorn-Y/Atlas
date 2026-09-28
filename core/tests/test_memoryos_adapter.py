"""MemoryOSAdapter coverage: identity, commitments, project state, decisions."""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas.memory import MemoryStore
from atlas.memory.memoryos_adapter import MemoryOSAdapter


@pytest.fixture
async def adapter(tmp_path: Path) -> MemoryOSAdapter:
    store = MemoryStore(db_path=tmp_path / "memory.db")
    await store.init()
    yield MemoryOSAdapter(store)
    await store.close()


async def test_identity_roundtrip_and_listing(adapter: MemoryOSAdapter) -> None:
    await adapter.set_identity("preferred_name", "Atlas 用户")
    await adapter.set_identity("timezone", "Asia/Shanghai")

    assert await adapter.get_identity("preferred_name") == "Atlas 用户"
    names = {fact["key"] for fact in await adapter.list_identity()}
    assert names == {"identity:preferred_name", "identity:timezone"}


async def test_commitment_lifecycle_requires_user_evidence(
    adapter: MemoryOSAdapter,
) -> None:
    conversation = await adapter.store.create_conversation("commitments")
    await adapter.add_commitment(
        "weekly-report", "每周五发周报", source_conversation_id=conversation,
    )
    active = await adapter.active_commitments()
    assert len(active) == 1
    assert active[0]["commitment_status"] == "active"

    non_user_message = await adapter.store.save_message(
        conversation, "assistant", "好的",
    )
    assert await adapter.fulfill_commitment("weekly-report", non_user_message) is False

    user_message = await adapter.store.save_message(conversation, "user", "周报制度取消")
    assert await adapter.cancel_commitment("weekly-report", user_message) is True
    assert await adapter.active_commitments() == []

    history = await adapter.commitment_history("weekly-report")
    assert history and history[-1]["status"] == "cancelled"


async def test_project_state_and_decisions(adapter: MemoryOSAdapter) -> None:
    await adapter.set_project_state("atlas-project", "wave1 merged; hub shipped")
    assert await adapter.get_project_state("atlas-project") == "wave1 merged; hub shipped"

    await adapter.record_decision(
        "adopt DBOS SQLite", rationale="no Postgres needed", project_id="atlas-project",
    )
    await adapter.record_decision("unrelated", project_id="voice-project")
    decisions = await adapter.project_decisions("atlas-project")
    assert len(decisions) == 1
    assert decisions[0]["summary"] == "adopt DBOS SQLite"
    assert decisions[0]["rationale"] == "no Postgres needed"


async def test_session_search_passthrough(adapter: MemoryOSAdapter) -> None:
    conversation = await adapter.store.create_conversation("recall")
    await adapter.store.save_message(conversation, "user", "dbos durable 波次已经合并")
    hits = await adapter.session_search("dbos durable")
    assert hits and "dbos" in hits[0]["content"].lower()
    assert await adapter.session_search("   ") == []
