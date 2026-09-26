"""Small deterministic quality checks for stored facts and ranked recall."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
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


def evaluate_memory_health(
    memories: Sequence[Mapping[str, Any]],
    *,
    stale_after_days: int = 180,
    window_days: int = 90,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """Score stored signal summaries and flag memories that need human review.

    This is an advisory report only. It never edits, promotes, or removes a memory.
    """
    if stale_after_days < 0 or window_days < 0:
        raise ValueError("Memory health windows must be non-negative")
    now = as_of or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    stale_before = now - timedelta(days=stale_after_days)

    results: list[dict[str, Any]] = []
    for memory in memories:
        counts = {
            name: int(memory.get(f"{name}_count", 0))
            for name in (
                "used", "not_used", "helpful", "unhelpful", "correction",
                "rejected", "useful", "not_useful", "uncertain",
            )
        }
        positive = counts["helpful"] + counts["useful"]
        negative = (
            counts["unhelpful"] + counts["not_useful"]
            + counts["correction"] + counts["rejected"]
        )
        evidence_count = positive + negative
        score = round(100 * positive / evidence_count) if evidence_count else None

        updated_at = datetime.fromisoformat(str(memory["updated_at"]))
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        is_stale = updated_at.astimezone(timezone.utc) <= stale_before
        reasons: list[str] = []
        if is_stale:
            reasons.append("stale")
        for count_name, reason in (
            ("correction", "corrected_by_user"),
            ("rejected", "related_candidate_rejected"),
            ("unhelpful", "marked_unhelpful"),
            ("not_useful", "rated_not_useful"),
        ):
            if counts[count_name]:
                reasons.append(reason)

        results.append({
            "key": memory["key"],
            "memory_type": memory["memory_type"],
            "updated_at": memory["updated_at"],
            "age_days": max(0, (now - updated_at.astimezone(timezone.utc)).days),
            "counts": counts,
            "recent_signal_count": int(memory.get("recent_signal_count", 0)),
            "positive_signal_count": positive,
            "negative_signal_count": negative,
            "health_score": score,
            "status": "review" if reasons else "healthy",
            "review_reasons": reasons,
        })

    results.sort(key=lambda item: item["key"])
    return {
        "evaluated_at": now.isoformat(),
        "stale_after_days": stale_after_days,
        "window_days": window_days,
        "memory_count": len(results),
        "review_count": sum(item["status"] == "review" for item in results),
        "memories": results,
    }


def evaluate_memory_optimization(
    health_report: Mapping[str, Any],
) -> dict[str, Any]:
    """Turn measured retrieval and feedback signals into ranked advisory actions."""
    memories = list(health_report.get("memories", ()))
    retrieval_observations = sum(
        int(memory["counts"].get("used", 0))
        + int(memory["counts"].get("not_used", 0))
        for memory in memories
    )
    positive = sum(int(memory.get("positive_signal_count", 0)) for memory in memories)
    negative = sum(int(memory.get("negative_signal_count", 0)) for memory in memories)
    quality_observations = positive + negative
    metrics = {
        "memory_count": len(memories),
        "retrieval_observation_count": retrieval_observations,
        "retrieval_effectiveness": round(
            sum(int(memory["counts"].get("used", 0)) for memory in memories)
            / retrieval_observations, 4,
        ) if retrieval_observations else None,
        "quality_observation_count": quality_observations,
        "usefulness_rate": round(positive / quality_observations, 4)
        if quality_observations else None,
    }

    recommendations: list[dict[str, Any]] = []
    for memory in memories:
        counts = memory["counts"]
        corrections = int(counts.get("correction", 0))
        rejected = int(counts.get("rejected", 0))
        unhelpful = int(counts.get("unhelpful", 0))
        not_useful = int(counts.get("not_useful", 0))
        used = int(counts.get("used", 0))
        not_used = int(counts.get("not_used", 0))
        memory_quality_observations = (
            int(memory.get("positive_signal_count", 0))
            + int(memory.get("negative_signal_count", 0))
        )
        if corrections or rejected:
            if corrections and rejected:
                reason = (
                    f"{corrections} correction and {rejected} rejection signal(s) were recorded; "
                    "review the stored memory before changing it."
                )
            elif rejected:
                reason = (
                    f"{rejected} related candidate was rejected; review the stored memory "
                    "before changing it."
                )
            else:
                reason = (
                    f"{corrections} correction signal(s) were recorded; review the stored "
                    "memory before changing it."
                )
            recommendations.append({
                "key": memory["key"],
                "action": "human_review",
                "priority": 100 + 10 * (corrections + rejected),
                "reason": reason,
                "evidence": {
                    "rejected_count": rejected,
                    "correction_count": corrections,
                },
            })
        elif unhelpful or not_useful:
            recommendations.append({
                "key": memory["key"],
                "action": "review_usefulness",
                "priority": 70 + 5 * (unhelpful + not_useful),
                "reason": (
                    f"{unhelpful + not_useful} negative usefulness signal(s) were recorded; "
                    "ask for human review before changing this memory."
                ),
                "evidence": {
                    "unhelpful_count": unhelpful,
                    "not_useful_count": not_useful,
                },
            })
        elif not_used > used:
            recommendations.append({
                "key": memory["key"],
                "action": "improve_retrieval",
                "priority": 50 + not_used - used,
                "reason": (
                    f"The memory was not used in {not_used} of {used + not_used} "
                    "recorded retrievals; review its retrieval cues."
                ),
                "evidence": {"used_count": used, "not_used_count": not_used},
            })
        elif "stale" in memory.get("review_reasons", ()):
            recommendations.append({
                "key": memory["key"],
                "action": "verify_freshness",
                "priority": 30,
                "reason": (
                    f"The memory is {memory['age_days']} days old; verify its freshness "
                    "with the user before changing it."
                ),
                "evidence": {"age_days": memory["age_days"]},
            })
        elif not memory_quality_observations:
            recommendations.append({
                "key": memory["key"],
                "action": "collect_feedback",
                "priority": 10,
                "reason": "No usefulness feedback is recorded; collect an outcome before optimizing.",
                "evidence": {"quality_observation_count": memory_quality_observations},
            })

    recommendations.sort(key=lambda item: (-item["priority"], item["key"]))
    return {
        "evaluated_at": health_report.get("evaluated_at"),
        "metrics": metrics,
        "recommendation_count": len(recommendations),
        "recommendations": recommendations,
    }
