"""Measured quality gates and golden recall cases for MemoryStore."""

from __future__ import annotations

from datetime import UTC, datetime, timezone
from pathlib import Path

import pytest

from atlas.memory import MemoryStore
from atlas.memory.quality import (
    evaluate_knowledge_maturity,
    evaluate_memory_quality,
    evaluate_memory_optimization,
    evaluate_knowledge_retrieval,
    evaluate_recall,
)


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


async def test_knowledge_retrieval_golden_cases_measure_ranking_and_evidence(
    store: MemoryStore,
) -> None:
    for key, value, category in [
        ("project_language", "Python", "project"),
        ("project_framework", "FastAPI", "project"),
        ("user_language", "Python", "personal"),
        ("user_timezone", "Asia/Hong_Kong", "personal"),
    ]:
        await store.set_fact(key, value, category)

    cases = []
    for query, expected_key in [
        ("project language Python", "user_knowledge_project"),
        ("personal language timezone", "user_knowledge_personal"),
        ("What is my phone number?", None),
    ]:
        cases.append({
            "expected_key": expected_key,
            "retrieved": await store.retrieve_user_knowledge(query, limit=1),
        })

    report = evaluate_knowledge_retrieval(cases, limit=1)
    assert report == {
        "case_count": 3,
        "relevant_case_count": 2,
        "hits_at_1": 2,
        "misses": 0,
        "false_positive_cases": 0,
        "retrieved_item_count": 2,
        "evidence_complete_items": 2,
        "recall_at_1": 1.0,
        "evidence_coverage": 1.0,
        "passed": True,
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


def test_memory_optimization_ranks_explainable_recommendations_deterministically() -> None:
    from atlas.memory.quality import evaluate_memory_health

    health = evaluate_memory_health([
        {
            "key": "retrieval_gap", "memory_type": "fact",
            "updated_at": "2026-09-25T00:00:00+00:00",
            "used_count": 1, "not_used_count": 4, "helpful_count": 1,
        },
        {
            "key": "rejected_memory", "memory_type": "fact",
            "updated_at": "2026-09-25T00:00:00+00:00",
            "rejected_count": 1,
        },
    ], as_of=datetime(2026, 9, 26, tzinfo=timezone.utc))

    report = evaluate_memory_optimization(health)

    assert report["metrics"] == {
        "memory_count": 2,
        "retrieval_observation_count": 5,
        "retrieval_effectiveness": 0.2,
        "quality_observation_count": 2,
        "usefulness_rate": 0.5,
    }
    assert [item["key"] for item in report["recommendations"]] == [
        "rejected_memory", "retrieval_gap",
    ]
    assert report["recommendations"][0] == {
        "key": "rejected_memory",
        "action": "human_review",
        "priority": 110,
        "reason": "1 related candidate was rejected; review the stored memory before changing it.",
        "evidence": {"rejected_count": 1, "correction_count": 0},
    }
    assert evaluate_memory_optimization(health) == report


def test_knowledge_maturity_is_deterministic_and_explains_every_recommendation() -> None:
    as_of = datetime(2026, 9, 26, tzinfo=UTC)
    memories = [
        {
            "key": "mature_fact", "memory_type": "fact", "confidence": 0.9,
            "source_conversation_id": "conversation-1", "source_message_id": "message-1",
            "updated_at": "2026-03-01T00:00:00+00:00", "change_count": 0,
            "used_count": 25, "useful_count": 10, "evidence_refs": ["fact:mature_fact", "usage:1"],
        },
        {
            "key": "review_fact", "memory_type": "fact", "confidence": 0.9,
            "source_conversation_id": "conversation-2", "source_message_id": "message-2",
            "updated_at": "2026-09-01T00:00:00+00:00", "change_count": 1,
            "correction_count": 1, "evidence_refs": ["fact:review_fact", "feedback:2"],
        },
    ]

    report = evaluate_knowledge_maturity(memories, as_of=as_of)

    assert report == evaluate_knowledge_maturity(memories, as_of=as_of)
    assert report["level_counts"] == {
        "nascent": 0, "developing": 0, "established": 0, "mature": 1,
        "review_required": 1,
    }
    assert report["criteria"]["mature"]["min_usage_count"] == 25
    assert [item["level"] for item in report["memories"]] == ["mature", "review_required"]
    assert report["recommendations"] == [{
        "key": "review_fact", "action": "human_review",
        "reason": "Review signals exist; a person should assess the active memory.",
        "evidence_refs": ["fact:review_fact", "feedback:2"],
    }]


async def test_maturity_report_tracks_approved_fact_evidence_without_mutation(
    store: MemoryStore,
) -> None:
    conversation_id = await store.create_conversation()
    await store.save_message(conversation_id, "user", "I prefer concise answers.")
    [candidate] = await store.extract_conversation_candidates(conversation_id)
    assert await store.promote_memory_candidate(candidate["id"])
    for _ in range(25):
        await store.record_memory_usage(candidate["key"], "used")
    for _ in range(10):
        await store.record_memory_evaluation(candidate["key"], "useful")
    await store._db.execute(
        "UPDATE facts SET created_at='2026-03-01T00:00:00+00:00', "
        "updated_at='2026-03-01T00:00:00+00:00' WHERE key=?", (candidate["key"],),
    )
    await store._db.commit()
    original_value = await store.get_fact(candidate["key"])

    snapshot = await store.create_knowledge_maturity_report(
        as_of=datetime(2026, 9, 26, tzinfo=UTC)
    )

    entry = snapshot["report"]["memories"][0]
    assert entry["level"] == "mature"
    assert entry["evidence"]["usage_count"] == 25
    assert entry["evidence"]["positive_signal_count"] == 10
    assert "usage:1" in entry["evidence"]["references"]
    assert "evaluation:1" in entry["evidence"]["references"]
    assert await store.get_fact(candidate["key"]) == original_value
    assert (await store.list_memory_candidates(status="approved"))[0]["id"] == candidate["id"]
    assert (await store.list_knowledge_maturity_reports())[0]["report"] == snapshot["report"]


async def test_optimization_reports_preserve_recommendation_audit_history(
    store: MemoryStore,
) -> None:
    database_path = store._db_path
    await store.set_fact("user_preference", "concise answers")
    conversation_id = await store.create_conversation()
    await store.save_message(
        conversation_id, "user", "I prefer concise answers."
    )
    [candidate] = await store.extract_conversation_candidates(conversation_id)
    assert await store.reject_memory_candidate(candidate["id"])

    first = await store.create_memory_optimization_report(
        as_of=datetime(2026, 9, 26, tzinfo=timezone.utc)
    )
    second = await store.create_memory_optimization_report(
        as_of=datetime(2026, 9, 27, tzinfo=timezone.utc)
    )
    history = await store.list_memory_optimization_reports()

    assert len(history) == 2
    assert [entry["id"] for entry in history] == [second["id"], first["id"]]
    assert history[1]["report"] == first["report"]
    assert history[0]["report"]["recommendations"][0]["action"] == "human_review"
    assert history[0]["report"]["recommendations"][0]["key"] == "user_preference"
    assert await store.get_fact("user_preference") == "concise answers"
    assert (await store.list_memory_candidates(status="rejected"))[0]["id"] == candidate["id"]

    await store.close()
    reopened = MemoryStore(db_path=database_path)
    await reopened.init()
    try:
        persisted = await reopened.list_memory_optimization_reports()
        assert [entry["id"] for entry in persisted] == [second["id"], first["id"]]
        assert persisted[0]["report"] == second["report"]
        assert await reopened.get_fact("user_preference") == "concise answers"
        assert (await reopened.list_memory_candidates(status="rejected"))[0]["id"] == candidate["id"]
    finally:
        await reopened.close()
