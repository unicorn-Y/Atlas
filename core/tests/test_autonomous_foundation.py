"""Persistence and integrity regressions for autonomous knowledge foundations."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest

from atlas.memory import MemoryStore


@pytest.mark.asyncio
async def test_autonomous_provenance_and_audit_survive_reopen(tmp_path):
    db_path = tmp_path / "autonomous-foundation.db"
    store = MemoryStore(db_path=db_path)
    await store.init()

    try:
        cursor = await store._db.execute("PRAGMA foreign_keys")
        assert (await cursor.fetchone())[0] == 1

        with pytest.raises(sqlite3.IntegrityError):
            await store._db.execute(
                "INSERT INTO memory_knowledge_health_report_reviews "
                "(report_id, decision, reviewed_at) VALUES (?, ?, ?)",
                ("missing-report", "approved", "2026-09-27T00:00:00+00:00"),
            )

        await store.set_fact("project_stack", "Python")
        original_fact = await store.get_fact("project_stack")
        outcome_id = await store.record_goal_outcome(
            goal_id="foundation-goal",
            goal="Review filesystem migration provenance",
            status="completed",
            evaluation={"satisfied": True, "evidence": "Migration verified."},
            steps=[{
                "id": "verify-source", "title": "Verify source manifest",
                "status": "completed", "evidence": "Manifest checksum matched.",
            }],
            source_conversation_id="foundation-conversation",
            source_run_id="foundation-run",
        )
        assert await store.review_goal_experience(outcome_id, approved=True)
        [knowledge] = await store.retrieve_approved_goal_knowledge("filesystem migration")
        report = await store.create_knowledge_health_report(
            as_of=datetime(2026, 9, 27, tzinfo=UTC),
        )
        assert await store.review_knowledge_health_report(report["id"], approved=True)
        assert not await store.review_knowledge_health_report(report["id"], approved=False)
    finally:
        await store.close()

    reopened = MemoryStore(db_path=db_path)
    await reopened.init()
    try:
        cursor = await reopened._db.execute("PRAGMA foreign_keys")
        assert (await cursor.fetchone())[0] == 1

        [persisted_knowledge] = await reopened.retrieve_approved_goal_knowledge(
            "filesystem migration",
        )
        assert persisted_knowledge["id"] == knowledge["id"]
        assert persisted_knowledge["source_outcome_id"] == outcome_id
        assert persisted_knowledge["source_conversation_id"] == "foundation-conversation"
        assert persisted_knowledge["source_run_id"] == "foundation-run"
        assert persisted_knowledge["evidence"][0]["evidence"] == "Manifest checksum matched."

        [persisted_report] = await reopened.list_knowledge_health_reports()
        assert persisted_report["id"] == report["id"]
        assert persisted_report["status"] == "approved"
        assert len(persisted_report["review_history"]) == 1
        assert persisted_report["review_history"][0]["decision"] == "approved"
        assert await reopened.get_fact("project_stack") == original_fact
    finally:
        await reopened.close()
