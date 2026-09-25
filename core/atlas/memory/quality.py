"""Small deterministic quality checks for stored facts and ranked recall."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from numbers import Real
from typing import Any


def evaluate_memory_quality(
    facts: Sequence[Mapping[str, Any]],
) -> dict[str, int | bool]:
    """Count invalid confidence/provenance while allowing intentionally local facts."""
    invalid_confidence = 0
    invalid_provenance = 0
    unattributed = 0

    for fact in facts:
        confidence = fact.get("confidence")
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, Real)
            or not math.isfinite(confidence)
            or not 0.0 <= confidence <= 1.0
        ):
            invalid_confidence += 1

        conversation_id = fact.get("source_conversation_id")
        message_id = fact.get("source_message_id")
        has_conversation = isinstance(conversation_id, str) and bool(conversation_id.strip())
        has_message = isinstance(message_id, str) and bool(message_id.strip())
        if (conversation_id is not None and not has_conversation) or (
            message_id is not None and not has_message
        ) or (has_message and not has_conversation):
            invalid_provenance += 1
        elif not has_conversation and not has_message:
            unattributed += 1

    fact_count = len(facts)
    return {
        "fact_count": fact_count,
        "invalid_confidence_count": invalid_confidence,
        "invalid_provenance_count": invalid_provenance,
        "unattributed_count": unattributed,
        "passed": invalid_confidence == 0 and invalid_provenance == 0,
    }


def evaluate_recall(
    cases: Sequence[Mapping[str, Any]], *, limit: int = 3,
) -> dict[str, int | float]:
    """Measure golden-case hit rate at ``limit`` and no-memory false positives."""
    if limit < 0:
        raise ValueError("limit must be non-negative")

    relevant = 0
    hits = 0
    misses = 0
    false_positives = 0
    for case in cases:
        expected = case.get("expected_key")
        recalled = case.get("recalled_keys", ())
        top_keys = list(recalled)[:limit]
        if expected is None:
            if top_keys:
                false_positives += 1
            continue

        relevant += 1
        if expected in top_keys:
            hits += 1
        else:
            misses += 1

    return {
        "case_count": len(cases),
        "relevant_case_count": relevant,
        f"hits_at_{limit}": hits,
        "misses": misses,
        "false_positive_cases": false_positives,
        f"recall_at_{limit}": hits / relevant if relevant else 1.0,
    }
