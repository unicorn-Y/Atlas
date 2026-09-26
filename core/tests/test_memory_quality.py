"""Measured quality gates and golden recall cases for MemoryStore."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timezone
from pathlib import Path

import pytest

from atlas.memory import MemoryStore
from atlas.memory.quality import (
    evaluate_knowledge_consolidation_proposals,
    evaluate_knowledge_health,
    evaluate_knowledge_maturity,
    evaluate_knowledge_optimization_candidate,
    evaluate_knowledge_optimization_candidates,
    evaluate_knowledge_retrieval,
    evaluate_knowledge_self_steering,
    evaluate_memory_optimization,
    evaluate_memory_quality,
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


def test_knowledge_health_is_deterministic_and_keeps_advice_evidence_linked() -> None:
    activation = {
        "id": "activation:proposal-1",
        "proposal_id": "proposal-1",
        "advisory_only": True,
        "activation_status": "active",
        "approval_history": [{"decision": "approved"}],
        "proposal": {
            "id": "proposal-1",
            "area": "knowledge-1",
            "status": "approved",
            "advisory_only": True,
            "source_candidate_ids": ["candidate-1"],
            "source_report_ids": ["report-1"],
            "evidence_refs": ["knowledge:knowledge-1", "usage:4", "feedback:5"],
            "candidate_snapshots": [{"candidate_id": "candidate-1"}],
        },
        "verifications": [
            {"id": "verification-1", "status": "verified", "history": [
                {"event": "verification_recorded"},
            ]},
            {"id": "verification-2", "status": "unverified", "history": [
                {"event": "verification_recorded"},
            ]},
        ],
        "usage_events": [{
            "id": 4,
            "knowledge_id": "knowledge-1",
            "source_outcome_id": "source-1",
            "conversation_id": "conversation-1",
            "source_run_id": "run-1",
        }],
        "feedback_events": [{
            "id": 5,
            "usage_event_id": 4,
            "knowledge_id": "knowledge-1",
            "source_outcome_id": "source-1",
            "execution_outcome_id": "execution-1",
            "signal": "failed",
        }],
    }
    pending = {**activation, "id": "activation:pending", "activation_status": "pending"}
    expected = {
        "evaluated_at": "2026-09-26T00:00:00+00:00",
        "advisory_only": True,
        "activation_count": 1,
        "review_count": 1,
        "activations": [{
            "activation_id": "activation:proposal-1",
            "proposal_id": "proposal-1",
            "knowledge_id": "knowledge-1",
            "source_candidate_ids": ["candidate-1"],
            "source_report_ids": ["report-1"],
            "evidence_refs": [
                "candidate:candidate-1", "feedback:5", "knowledge:knowledge-1",
                "report:report-1", "usage:4", "verification:verification-1",
                "verification:verification-2",
            ],
            "activation_history": [],
            "approval_history": [{"decision": "approved"}],
            "verification_evidence": [
                {"id": "verification-1", "status": "verified", "history": [
                    {"event": "verification_recorded"},
                ]},
                {"id": "verification-2", "status": "unverified", "history": [
                    {"event": "verification_recorded"},
                ]},
            ],
            "verification_history": [
                {"verification_id": "verification-1", "status": "verified", "history": [
                    {"event": "verification_recorded"},
                ]},
                {"verification_id": "verification-2", "status": "unverified", "history": [
                    {"event": "verification_recorded"},
                ]},
            ],
            "usage_evidence": [{
                "id": 4,
                "knowledge_id": "knowledge-1",
                "source_outcome_id": "source-1",
                "conversation_id": "conversation-1",
                "source_run_id": "run-1",
            }],
            "feedback_evidence": [{
                "id": 5,
                "usage_event_id": 4,
                "knowledge_id": "knowledge-1",
                "source_outcome_id": "source-1",
                "execution_outcome_id": "execution-1",
                "signal": "failed",
            }],
            "verification_count": 2,
            "verified_count": 1,
            "unverified_count": 1,
            "usage_count": 1,
            "helpful_count": 0,
            "failed_count": 1,
            "decision": "review_unverified_usage",
            "recommendation": (
                "Review unverified usage claims before relying on this advisory knowledge."
            ),
            "advisory_only": True,
        }],
    }
    assert evaluate_knowledge_health(
        [pending, activation], as_of=datetime(2026, 9, 26, tzinfo=UTC),
    ) == expected
    assert evaluate_knowledge_health(
        [activation, pending], as_of=datetime(2026, 9, 26, tzinfo=UTC),
    ) == expected


@pytest.mark.asyncio
async def test_knowledge_health_persists_verified_usage_and_feedback_snapshot(
    store: MemoryStore,
) -> None:
    source_outcome_id = await store.record_goal_outcome(
        goal_id="health-source",
        goal="Review filesystem migration risks",
        status="completed",
        evaluation={"satisfied": True},
        steps=[{"id": "inspect", "title": "Inspect", "evidence": "Manifest reviewed."}],
        source_conversation_id="health-source-conversation",
        source_run_id="health-source-run",
    )
    assert await store.review_goal_experience(source_outcome_id, approved=True)
    [knowledge] = await store.retrieve_approved_goal_knowledge("filesystem migration")
    usage_id = await store.record_goal_knowledge_usage(
        knowledge["id"], "execution", "health-execution-conversation", "health-execution-run",
    )
    await store.record_goal_outcome(
        goal_id="health-execution",
        goal="Review filesystem migration risks",
        status="completed",
        evaluation={"satisfied": True},
        steps=[],
        source_conversation_id="health-execution-conversation",
        source_run_id="health-execution-run",
    )
    [feedback] = await store.list_goal_knowledge_feedback(knowledge["id"])

    proposal = {
        "id": "proposal:knowledge-health",
        "area": knowledge["id"],
        "status": "approved",
        "advisory_only": True,
        "source_candidate_ids": ["candidate:health"],
        "source_report_ids": ["report:health"],
        "evidence_refs": [f"knowledge:{knowledge['id']}", f"usage:{usage_id}",
                          f"feedback:{feedback['id']}"],
        "candidate_snapshots": [{
            "candidate_id": "candidate:health",
            "evidence_refs": ["evidence:health"],
        }],
    }
    reviewed_at = "2026-09-26T00:00:00+00:00"
    await store._db.execute(
        "INSERT INTO memory_consolidation_proposals "
        "(id, proposal_json, status, reviewed_at, created_at) VALUES (?, ?, 'approved', ?, ?)",
        (proposal["id"], json.dumps(proposal), reviewed_at, reviewed_at),
    )
    await store._db.execute(
        "INSERT INTO memory_consolidation_proposal_reviews "
        "(proposal_id, decision, reviewed_at) VALUES (?, 'approved', ?)",
        (proposal["id"], reviewed_at),
    )
    await store._db.commit()
    activation = await store.activate_knowledge_consolidation_proposal(proposal["id"])
    assert activation is not None
    verification = await store.verify_knowledge_activation_usage(
        activation["id"], candidate_id="candidate:health",
        evidence_refs=["evidence:health"], usage_id=str(usage_id),
    )
    assert verification is not None and verification["status"] == "verified"

    as_of = datetime(2026, 9, 26, tzinfo=UTC)
    report = await store.get_knowledge_health(as_of=as_of)
    [item] = report["activations"]
    assert report["advisory_only"] is True
    assert item["decision"] == "continue_advisory_monitoring"
    assert item["helpful_count"] == 1
    assert item["failed_count"] == 0
    assert item["verification_history"][0]["verification_id"] == verification["id"]
    assert item["feedback_evidence"][0]["id"] == feedback["id"]
    assert f"usage:{usage_id}" in item["evidence_refs"]

    first = await store.create_knowledge_health_report(as_of=as_of)
    second = await store.create_knowledge_health_report(as_of=as_of)
    assert first == second
    [stored] = await store.list_knowledge_health_reports()
    assert stored == first
    assert await store.retrieve_approved_goal_knowledge("filesystem migration") == [knowledge]


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


def test_knowledge_self_steering_is_deterministic_and_preserves_evidence_sources() -> None:
    maturity = {
        "evaluated_at": "2026-09-26T00:00:00+00:00",
        "memories": [{
            "key": "project_stack", "level": "review_required",
            "evidence": {
                "references": ["fact:project_stack", "feedback:7"],
                "review_signal_count": 2, "usage_count": 3,
                "positive_signal_count": 1,
            },
        }],
    }
    approved_evaluations = [{
        "knowledge_id": "goal-knowledge:outcome-1",
        "source_outcome_id": "outcome-1", "decision": "review_recommended_after_repeated_failures",
        "helpful_count": 0, "failed_count": 2,
        "evidence": [{
            "id": 9, "usage_event_id": 4, "source_outcome_id": "outcome-1",
            "execution_outcome_id": "outcome-2",
        }],
    }]

    report = evaluate_knowledge_self_steering(
        maturity, approved_evaluations, maturity_report_id="maturity-1",
    )

    assert report == evaluate_knowledge_self_steering(
        maturity, approved_evaluations, maturity_report_id="maturity-1",
    )
    assert report["suggestion_count"] == 2
    fact, knowledge = sorted(
        report["suggestions"], key=lambda item: item["source_type"] != "fact",
    )
    assert fact["action"] == "review_fact"
    assert fact["evidence_refs"] == ["fact:project_stack", "feedback:7"]
    assert knowledge["action"] == "review_approved_knowledge"
    assert knowledge["evidence_refs"] == [
        "feedback:9", "knowledge:goal-knowledge:outcome-1",
        "outcome:outcome-1", "outcome:outcome-2", "usage:4",
    ]


def test_knowledge_optimization_candidates_are_deterministic_and_require_evidence() -> None:
    reports = [{
        "id": "steering-report-1",
        "report": {"suggestions": [{
            "area": "project_stack", "source_type": "fact",
            "action": "continue_fact_observation", "priority": 20,
            "reason": "Collect additional evidence.",
            "evidence_refs": ["fact:project_stack", "usage:2"],
            "signals": {"maturity_level": "developing"},
        }, {
            "area": "risky", "source_type": "fact", "action": "review_fact",
            "priority": 100, "evidence_refs": ["fact:risky"],
        }]},
    }]
    candidates = evaluate_knowledge_optimization_candidates(reports)
    assert candidates == evaluate_knowledge_optimization_candidates(reports)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["id"].startswith("knowledge-optimization:")
    assert candidate["risk"] == "low"
    assert candidate["advisory_only"] is True
    assert candidate["evidence_refs"] == ["fact:project_stack", "usage:2"]
    assert evaluate_knowledge_optimization_candidate(candidate) == {
        "candidate_id": candidate["id"], "eligible": True,
        "decision": "eligible_low_risk_advisory",
        "evidence_refs": ["fact:project_stack", "usage:2"],
    }


async def test_self_steering_uses_approved_knowledge_only_and_leaves_facts_unchanged(
    store: MemoryStore,
) -> None:
    await store.set_fact("project_stack", "Python")
    approved_outcome_id = await store.record_goal_outcome(
        goal_id="review-stack", goal="Review project stack", status="completed",
        evaluation={"satisfied": True, "evidence": "Stack recorded."}, steps=[],
        source_conversation_id="approved-conversation", source_run_id="approved-run",
    )
    pending_outcome_id = await store.record_goal_outcome(
        goal_id="pending-stack", goal="Review pending stack", status="completed",
        evaluation={"satisfied": True, "evidence": "Pending stack recorded."}, steps=[],
        source_conversation_id="pending-conversation", source_run_id="pending-run",
    )
    rejected_outcome_id = await store.record_goal_outcome(
        goal_id="rejected-stack", goal="Review rejected stack", status="completed",
        evaluation={"satisfied": True, "evidence": "Rejected stack recorded."}, steps=[],
        source_conversation_id="rejected-conversation", source_run_id="rejected-run",
    )
    assert await store.review_goal_experience(approved_outcome_id, approved=True)
    assert await store.review_goal_experience(rejected_outcome_id, approved=False)
    original_fact = await store.get_fact("project_stack")

    snapshot = await store.create_knowledge_self_steering_report()
    suggestions = snapshot["report"]["suggestions"]
    knowledge_suggestions = [
        item for item in suggestions
        if item["source_type"] == "approved_goal_knowledge"
    ]

    assert snapshot["report"]["approved_knowledge_count"] == 1
    assert len(knowledge_suggestions) == 1
    assert f"outcome:{approved_outcome_id}" in knowledge_suggestions[0]["evidence_refs"]
    assert all(pending_outcome_id not in ref for ref in knowledge_suggestions[0]["evidence_refs"])
    assert snapshot["report"]["maturity_report_id"]
    assert await store.get_fact("project_stack") == original_fact
    assert len(await store.list_knowledge_self_steering_reports()) == 1
    assert len(await store.list_knowledge_maturity_reports()) == 1
    pending_outcomes = await store.list_goal_outcomes(experience_status="pending")
    assert pending_outcomes[0]["id"] == pending_outcome_id
    rejected_outcomes = await store.list_goal_outcomes(experience_status="rejected")
    assert rejected_outcomes[0]["id"] == rejected_outcome_id


async def test_optimization_candidates_require_approved_report_and_audit_review(
    store: MemoryStore,
) -> None:
    await store.set_fact("project_stack", "Python")
    original_fact = await store.get_fact("project_stack")
    snapshot = await store.create_knowledge_self_steering_report()

    assert snapshot["status"] == "pending"
    assert await store.create_knowledge_optimization_candidates() == []
    assert await store.review_knowledge_self_steering_report(snapshot["id"], approved=True)
    assert not await store.review_knowledge_self_steering_report(snapshot["id"], approved=False)

    first = await store.create_knowledge_optimization_candidates()
    second = await store.create_knowledge_optimization_candidates()
    assert first == second
    assert first and first[0]["source_report_id"] == snapshot["id"]
    candidate = first[0]
    assert candidate["evaluation"]["eligible"]
    assert candidate["evidence_refs"]
    assert await store.review_knowledge_optimization_candidate(candidate["id"], approved=True)
    assert not await store.review_knowledge_optimization_candidate(
        candidate["id"], approved=False
    )

    [reviewed] = await store.list_knowledge_optimization_candidates(status="approved")
    assert reviewed["status"] == "approved"
    assert reviewed["review_history"] == [{
        "decision": "approved", "reviewed_at": reviewed["reviewed_at"],
    }]
    [approved_report] = await store.list_knowledge_self_steering_reports()
    assert approved_report["status"] == "approved"
    assert approved_report["reviewed_at"]
    assert await store.get_fact("project_stack") == original_fact

    rejected_report = await store.create_knowledge_self_steering_report()
    assert await store.review_knowledge_self_steering_report(
        rejected_report["id"], approved=False
    )
    assert not await store.review_knowledge_self_steering_report(
        rejected_report["id"], approved=True
    )
    assert all(
        item["source_report_id"] != rejected_report["id"]
        for item in await store.create_knowledge_optimization_candidates()
    )

    another_report = await store.create_knowledge_self_steering_report()
    assert await store.review_knowledge_self_steering_report(
        another_report["id"], approved=True
    )
    [pending_candidate] = [
        item for item in await store.create_knowledge_optimization_candidates()
        if item["source_report_id"] == another_report["id"]
    ]
    assert await store.review_knowledge_optimization_candidate(
        pending_candidate["id"], approved=False
    )
    [rejected_candidate] = await store.list_knowledge_optimization_candidates(
        status="rejected"
    )
    assert rejected_candidate["review_history"][0]["decision"] == "rejected"


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


async def test_activation_usage_verification_checks_provenance_and_persists_audit(
    store: MemoryStore,
) -> None:
    candidate_id = "candidate-verified"
    proposal_id = "proposal-verified"
    activation_id = f"activation:{proposal_id}"
    activation = {
        "id": activation_id,
        "proposal_id": proposal_id,
        "advisory_only": True,
        "activation_status": "active",
        "proposal": {
            "id": proposal_id,
            "status": "approved",
            "advisory_only": True,
            "source_candidate_ids": [candidate_id],
            "candidate_snapshots": [{
                "candidate_id": candidate_id,
                "source_report_id": "report-verified",
                "evidence_refs": ["evidence:approved-source"],
            }],
        },
        "approval_history": [{"decision": "approved", "reviewed_at": "2026-09-26T00:00:00Z"}],
    }
    await store._db.execute(
        "INSERT INTO memory_consolidation_proposals "
        "(id, proposal_json, status, reviewed_at, created_at) "
        "VALUES (?, ?, 'approved', '2026-09-26T00:00:00Z', '2026-09-26T00:00:00Z')",
        (proposal_id, json.dumps(activation["proposal"])),
    )
    await store._db.execute(
        "INSERT INTO memory_knowledge_activations (id, proposal_id, activation_json, created_at) "
        "VALUES (?, ?, ?, '2026-09-26T00:00:00Z')",
        (activation_id, proposal_id, json.dumps(activation)),
    )
    await store._db.commit()

    original_fact = await store.get_fact("project_stack")
    verified = await store.verify_knowledge_activation_usage(
        activation_id,
        candidate_id=candidate_id,
        evidence_refs=["evidence:approved-source"],
        usage_id="run-42",
    )
    unsupported = await store.verify_knowledge_activation_usage(
        activation_id,
        candidate_id=candidate_id,
        evidence_refs=["evidence:invented"],
        usage_id="run-43",
    )
    history = await store.list_knowledge_verifications(activation_id=activation_id)

    assert await store.verify_knowledge_activation_usage(
        "activation:missing",
        candidate_id=candidate_id,
        evidence_refs=["evidence:approved-source"],
    ) is None
    assert verified["status"] == "verified"
    assert verified["checks"] == {
        "activation_active": True,
        "candidate_in_provenance": True,
        "evidence_supported": True,
    }
    assert verified["advisory_only"] is True
    assert unsupported["status"] == "unverified"
    assert unsupported["checks"]["evidence_supported"] is False
    assert [item["id"] for item in history] == [unsupported["id"], verified["id"]]
    assert await store.list_knowledge_verifications(activation_id="missing") == []
    assert await store.get_fact("project_stack") == original_fact

    database_path = store._db_path
    await store.close()
    reopened = MemoryStore(db_path=database_path)
    await reopened.init()
    try:
        persisted = await reopened.list_knowledge_verifications(activation_id=activation_id)
        assert persisted == history
    finally:
        await reopened.close()


def test_consolidation_proposals_are_deterministic_and_keep_only_approved_provenance() -> None:
    candidates = [
        {
            "id": "candidate-b", "status": "approved", "advisory_only": True,
            "source_report_id": "report-b", "area": "fact_evidence",
            "source_type": "fact", "action": "complete_fact_evidence",
            "priority": 3, "reason": "collect a second source", "evidence_refs": ["evidence-2"],
        },
        {
            "id": "candidate-a", "status": "approved", "advisory_only": True,
            "source_report_id": "report-a", "area": "fact_evidence",
            "source_type": "fact", "action": "complete_fact_evidence",
            "priority": 2, "reason": "collect a first source", "evidence_refs": ["evidence-1"],
        },
        {
            "id": "candidate-pending", "status": "pending", "advisory_only": True,
            "source_report_id": "report-pending", "area": "fact_evidence",
            "source_type": "fact", "action": "complete_fact_evidence",
            "priority": 9, "evidence_refs": ["evidence-pending"],
        },
        {
            "id": "candidate-rejected", "status": "rejected", "advisory_only": True,
            "source_report_id": "report-rejected", "area": "fact_evidence",
            "source_type": "fact", "action": "complete_fact_evidence",
            "priority": 10, "evidence_refs": ["evidence-rejected"],
        },
    ]

    proposals = evaluate_knowledge_consolidation_proposals(candidates)

    assert proposals == evaluate_knowledge_consolidation_proposals(list(reversed(candidates)))
    [proposal] = proposals
    assert proposal["advisory_only"] is True
    assert proposal["source_candidate_ids"] == ["candidate-a", "candidate-b"]
    assert proposal["source_report_ids"] == ["report-a", "report-b"]
    assert proposal["evidence_refs"] == ["evidence-1", "evidence-2"]
