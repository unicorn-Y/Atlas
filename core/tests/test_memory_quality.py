"""Measured quality gates and golden recall cases for MemoryStore."""

from __future__ import annotations

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
