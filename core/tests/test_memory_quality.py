"""Measured quality gates and golden recall cases for MemoryStore."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from atlas.memory import MemoryStore
from atlas.memory.quality import evaluate_memory_quality, evaluate_recall


@pytest.fixture
async def store(tmp_path: Path) -> MemoryStore:
    memory = MemoryStore(db_path=tmp_path / "quality.db")
    await memory.init()
    yield memory
    await memory.close()


def test_memory_quality_reports_confidence_and_provenance_counts() -> None:
    report = evaluate_memory_quality([
        {
            "confidence": 0.9,
            "source_conversation_id": "conversation-1",
            "source_message_id": "message-1",
        },
        {
            "confidence": 1.0,
            "source_conversation_id": None,
            "source_message_id": None,
        },
        {
            "confidence": 1.2,
            "source_conversation_id": None,
            "source_message_id": "message-without-conversation",
        },
    ])

    assert report == {
        "fact_count": 3,
        "invalid_confidence_count": 1,
        "invalid_provenance_count": 1,
        "unattributed_count": 1,
        "passed": False,
    }


@pytest.mark.parametrize(
    ("facts", "passed"),
    [
        ([], True),
        ([{"confidence": 0.0, "source_conversation_id": "c1"}], True),
        ([{"confidence": float("nan"), "source_conversation_id": "c1"}], False),
        ([{"confidence": -0.1, "source_conversation_id": "c1"}], False),
    ],
)
def test_memory_quality_confidence_boundaries(
    facts: list[dict[str, object]], passed: bool
) -> None:
    assert evaluate_memory_quality(facts)["passed"] is passed


async def test_golden_recall_cases_produce_numeric_metrics(store: MemoryStore) -> None:
    facts = [
        ("user_timezone", "Asia/Hong_Kong", "personal"),
        ("user_language", "English", "personal"),
        ("project_stack", "FastAPI", "project"),
        ("preferred_editor", "VS Code", "preference"),
    ]
    for key, value, category in facts:
        await store.set_fact(key, value, category, confidence=0.9)

    cases = [
        ("What timezone do I use?", "user_timezone"),
        ("What language do I use?", "user_language"),
        ("What stack does our project use?", "project_stack"),
        ("Which editor do I prefer?", "preferred_editor"),
        ("What is my phone number?", None),
    ]
    results = []
    for query, expected_key in cases:
        recalled = await store.get_agent_context(query, limit=3)
        results.append({
            "expected_key": expected_key,
            "recalled_keys": [fact["key"] for fact in recalled],
        })

    report = evaluate_recall(results)
    assert report == {
        "case_count": 5,
        "relevant_case_count": 4,
        "hits_at_3": 4,
        "misses": 0,
        "false_positive_cases": 0,
        "recall_at_3": 1.0,
    }


async def test_candidate_approval_preserves_quality_provenance(store: MemoryStore) -> None:
    conversation_id = await store.create_conversation()
    message_id = await store.save_message(
        conversation_id, "user", "My timezone is Asia/Hong_Kong."
    )
    [candidate] = await store.extract_conversation_candidates(conversation_id)
    assert candidate["source_conversation_id"] == conversation_id
    assert candidate["source_message_id"] == message_id
    assert await store.promote_memory_candidate(candidate["id"])

    facts = await store.list_facts()
    assert evaluate_memory_quality(facts) == {
        "fact_count": 1,
        "invalid_confidence_count": 0,
        "invalid_provenance_count": 0,
        "unattributed_count": 0,
        "passed": True,
    }
    assert facts[0]["confidence"] == 0.9
    assert facts[0]["source_conversation_id"] == conversation_id
    assert facts[0]["source_message_id"] == message_id


async def test_memory_health_aggregates_signals_and_only_flags_for_review(
    store: MemoryStore,
) -> None:
    as_of = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)
    await store.set_fact("healthy_memory", "current value")
    await store.set_fact("stale_memory", "old value")
    await store.set_fact("poor_memory", "needs review")
    assert store._db is not None
    await store._db.execute(
        "UPDATE facts SET updated_at = ? WHERE key = ?",
        ("2026-09-01 00:00:00", "healthy_memory"),
    )
    await store._db.execute(
        "UPDATE facts SET updated_at = ? WHERE key = ?",
        ("2025-01-01 00:00:00", "stale_memory"),
    )
    await store._db.commit()

    await store.record_memory_usage("healthy_memory", "helpful")
    await store.record_memory_usage("healthy_memory", "helpful")
    await store._db.execute(
        "UPDATE memory_usage_events SET recorded_at = '2026-06-01 00:00:00' "
        "WHERE id = (SELECT MIN(id) FROM memory_usage_events WHERE memory_key = ?)",
        ("healthy_memory",),
    )
    await store._db.commit()
    await store.record_memory_usage("poor_memory", "unhelpful")
    await store.record_memory_evaluation("poor_memory", "not_useful")

    report = await store.get_memory_health(
        stale_after_days=180, window_days=90, as_of=as_of,
    )
    assert report["memory_count"] == 3
    assert report["review_count"] == 2
    by_key = {memory["key"]: memory for memory in report["memories"]}
    assert by_key["healthy_memory"]["status"] == "healthy"
    assert by_key["healthy_memory"]["counts"]["helpful"] == 2
    assert by_key["healthy_memory"]["recent_signal_count"] == 1
    assert by_key["healthy_memory"]["health_score"] == 100
    assert by_key["stale_memory"]["review_reasons"] == ["stale"]
    assert by_key["poor_memory"]["review_reasons"] == [
        "marked_unhelpful", "rated_not_useful",
    ]
    assert by_key["poor_memory"]["health_score"] == 0
    assert await store.get_fact("poor_memory") == "needs review"


def test_memory_health_rejects_negative_windows() -> None:
    from atlas.memory.quality import evaluate_memory_health

    with pytest.raises(ValueError, match="non-negative"):
        evaluate_memory_health([], stale_after_days=-1)
