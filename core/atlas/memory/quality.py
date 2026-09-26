"""Small deterministic quality checks for stored facts and ranked recall."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta, timezone
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


def evaluate_knowledge_retrieval(
    cases: Sequence[Mapping[str, Any]], *, limit: int = 1,
) -> dict[str, int | float | bool]:
    """Measure ranked knowledge-view retrieval, no-memory precision, and evidence."""
    if limit < 0:
        raise ValueError("limit must be non-negative")

    relevant = 0
    hits = 0
    misses = 0
    false_positives = 0
    retrieved_count = 0
    evidence_complete = 0
    for case in cases:
        expected = case.get("expected_key")
        retrieved = list(case.get("retrieved", ()))[:limit]
        retrieved_count += len(retrieved)
        evidence_complete += sum(
            isinstance(item.get("evidence"), Sequence)
            and not isinstance(item.get("evidence"), (str, bytes))
            and bool(item.get("evidence"))
            for item in retrieved
        )
        if expected is None:
            if retrieved:
                false_positives += 1
            continue

        relevant += 1
        if any(item.get("key") == expected for item in retrieved):
            hits += 1
        else:
            misses += 1

    evidence_coverage = evidence_complete / retrieved_count if retrieved_count else 1.0
    passed = misses == 0 and false_positives == 0 and evidence_complete == retrieved_count
    return {
        "case_count": len(cases),
        "relevant_case_count": relevant,
        f"hits_at_{limit}": hits,
        "misses": misses,
        "false_positive_cases": false_positives,
        "retrieved_item_count": retrieved_count,
        "evidence_complete_items": evidence_complete,
        f"recall_at_{limit}": hits / relevant if relevant else 1.0,
        "evidence_coverage": evidence_coverage,
        "passed": passed,
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


def evaluate_knowledge_health(
    activations: Sequence[Mapping[str, Any]],
    *,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """Summarize verified use and outcome feedback for approved advisory activations."""
    now = as_of or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    now = now.astimezone(UTC)

    results: list[dict[str, Any]] = []
    for activation in activations:
        proposal = activation.get("proposal", {})
        approvals = activation.get("approval_history", ())
        if not (
            activation.get("activation_status") == "active"
            and activation.get("advisory_only") is True
            and proposal.get("status") == "approved"
            and proposal.get("advisory_only") is True
            and approvals
            and approvals[-1].get("decision") == "approved"
        ):
            continue

        knowledge_id = str(proposal.get("area", ""))
        verifications = list(activation.get("verifications", ()))
        verified_count = sum(item.get("status") == "verified" for item in verifications)
        unverified_count = sum(item.get("status") == "unverified" for item in verifications)
        usage_events = [
            item for item in activation.get("usage_events", ())
            if item.get("knowledge_id") == knowledge_id
        ]
        usage_by_id = {str(item.get("id")): item for item in usage_events}
        feedback_events = [
            item for item in activation.get("feedback_events", ())
            if item.get("knowledge_id") == knowledge_id
            and str(item.get("usage_event_id")) in usage_by_id
            and item.get("source_outcome_id")
                == usage_by_id[str(item.get("usage_event_id"))].get("source_outcome_id")
        ]
        helpful_count = sum(item.get("signal") == "helpful" for item in feedback_events)
        failed_count = sum(item.get("signal") == "failed" for item in feedback_events)

        if unverified_count:
            decision = "review_unverified_usage"
            recommendation = (
                "Review unverified usage claims before relying on this advisory knowledge."
            )
        elif failed_count >= 2:
            decision = "human_review_repeated_failures"
            recommendation = (
                "Repeated failed outcomes warrant human review before future reliance."
            )
        elif failed_count:
            decision = "monitor_after_failure"
            recommendation = "Monitor the next validated outcome after this failed use."
        elif usage_events and not feedback_events:
            decision = "collect_outcome_feedback"
            recommendation = "Collect validated outcome feedback for recorded uses."
        elif helpful_count:
            decision = "continue_advisory_monitoring"
            recommendation = "Continue advisory use with outcome monitoring."
        else:
            decision = "verify_before_reliance"
            recommendation = "Verify a claimed use and collect its outcome before relying on it."

        proposal_id = str(activation.get("proposal_id") or proposal.get("id", ""))
        source_candidate_ids = sorted(set(map(str, proposal.get("source_candidate_ids", ()))))
        source_report_ids = sorted(set(map(str, proposal.get("source_report_ids", ()))))
        evidence_refs = set(map(str, proposal.get("evidence_refs", ())))
        evidence_refs.update(
            f"verification:{item['id']}" for item in verifications if item.get("id")
        )
        evidence_refs.update(
            f"usage:{item['id']}" for item in usage_events if item.get("id") is not None
        )
        evidence_refs.update(
            f"feedback:{item['id']}" for item in feedback_events if item.get("id") is not None
        )
        evidence_refs.update(f"candidate:{item}" for item in source_candidate_ids)
        evidence_refs.update(f"report:{item}" for item in source_report_ids)
        evidence_refs.add(f"knowledge:{knowledge_id}")
        results.append({
            "activation_id": str(activation["id"]),
            "proposal_id": proposal_id,
            "knowledge_id": knowledge_id,
            "source_candidate_ids": source_candidate_ids,
            "source_report_ids": source_report_ids,
            "evidence_refs": sorted(evidence_refs),
            "activation_history": sorted(
                (dict(event) for event in activation.get("history", ())),
                key=lambda event: (str(event.get("event", "")),
                                   str(event.get("created_at", ""))),
            ),
            "approval_history": [dict(event) for event in approvals],
            "verification_evidence": [
                dict(item) for item in sorted(
                    verifications, key=lambda item: str(item.get("id", "")),
                )
            ],
            "verification_history": [
                {
                    "verification_id": str(item.get("id", "")),
                    "status": item.get("status"),
                    "history": sorted(
                        (dict(event) for event in item.get("history", ())),
                        key=lambda event: (str(event.get("event", "")),
                                           str(event.get("created_at", ""))),
                    ),
                }
                for item in sorted(verifications, key=lambda item: str(item.get("id", "")))
            ],
            "usage_evidence": sorted(
                (dict(item) for item in usage_events), key=lambda item: str(item.get("id", "")),
            ),
            "feedback_evidence": sorted(
                (dict(item) for item in feedback_events),
                key=lambda item: str(item.get("id", "")),
            ),
            "verification_count": len(verifications),
            "verified_count": verified_count,
            "unverified_count": unverified_count,
            "usage_count": len(usage_events),
            "helpful_count": helpful_count,
            "failed_count": failed_count,
            "decision": decision,
            "recommendation": recommendation,
            "advisory_only": True,
        })

    results.sort(key=lambda item: (item["activation_id"], item["proposal_id"]))
    return {
        "evaluated_at": now.isoformat(),
        "advisory_only": True,
        "activation_count": len(results),
        "review_count": sum(
            item["decision"] in {
                "review_unverified_usage", "human_review_repeated_failures",
            }
            for item in results
        ),
        "activations": results,
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


def evaluate_knowledge_maturity(
    memories: Sequence[Mapping[str, Any]], *, as_of: datetime | None = None,
) -> dict[str, Any]:
    """Report deterministic maturity signals for active memories without changing them."""
    criteria = {
        "developing": {
            "min_age_days": 30, "max_change_count": 1,
            "min_usage_count": 3, "min_positive_signal_count": 2,
        },
        "established": {
            "min_age_days": 90, "max_change_count": 0,
            "min_usage_count": 10, "min_positive_signal_count": 5,
        },
        "mature": {
            "min_age_days": 180, "max_change_count": 0,
            "min_usage_count": 25, "min_positive_signal_count": 10,
        },
        "review_required": "one or more negative review signals",
        "evidence_required": "valid confidence and complete source attribution",
    }
    now = as_of or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    now = now.astimezone(UTC)

    results: list[dict[str, Any]] = []
    recommendations: list[dict[str, Any]] = []
    for memory in sorted(memories, key=lambda item: str(item["key"])):
        key = str(memory["key"])
        updated_at = datetime.fromisoformat(str(memory["updated_at"]))
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)
        age_days = max(0, (now - updated_at.astimezone(UTC)).days)
        confidence = memory.get("confidence")
        confidence_complete = (
            isinstance(confidence, Real)
            and not isinstance(confidence, bool)
            and math.isfinite(confidence)
            and 0.0 <= confidence <= 1.0
        )
        source_conversation_id = memory.get("source_conversation_id")
        source_message_id = memory.get("source_message_id")
        provenance_complete = (
            isinstance(source_conversation_id, str)
            and bool(source_conversation_id.strip())
            and isinstance(source_message_id, str)
            and bool(source_message_id.strip())
        )
        counts = {
            name: int(memory.get(f"{name}_count", 0))
            for name in (
                "used", "not_used", "helpful", "unhelpful", "correction",
                "rejected", "useful", "not_useful", "uncertain",
            )
        }
        usage_count = counts["used"] + counts["not_used"]
        positive_count = counts["helpful"] + counts["useful"]
        review_count = (
            counts["unhelpful"] + counts["correction"] + counts["rejected"]
            + counts["not_useful"]
        )
        change_count = int(memory.get("change_count", 0))
        stability = (
            "stable" if age_days >= 30 and change_count == 0
            else "changed" if change_count
            else "unproven"
        )
        evidence_refs = sorted(set(memory.get("evidence_refs", ())))

        if review_count:
            level = "review_required"
            action = "human_review"
            reason = "Review signals exist; a person should assess the active memory."
        elif not confidence_complete or not provenance_complete:
            level = "nascent"
            action = "complete_evidence"
            reason = "Confidence or source attribution is incomplete."
        elif (
            age_days >= criteria["mature"]["min_age_days"]
            and change_count <= criteria["mature"]["max_change_count"]
            and usage_count >= criteria["mature"]["min_usage_count"]
            and positive_count >= criteria["mature"]["min_positive_signal_count"]
        ):
            level = "mature"
            action = None
            reason = "Long-lived, stable memory has repeated positive use evidence."
        elif (
            age_days >= criteria["established"]["min_age_days"]
            and change_count <= criteria["established"]["max_change_count"]
            and usage_count >= criteria["established"]["min_usage_count"]
            and positive_count >= criteria["established"]["min_positive_signal_count"]
        ):
            level = "established"
            action = "continue_observation"
            reason = "Stable memory has repeated use and positive feedback."
        elif (
            age_days >= criteria["developing"]["min_age_days"]
            and change_count <= criteria["developing"]["max_change_count"]
            and usage_count >= criteria["developing"]["min_usage_count"]
            and positive_count >= criteria["developing"]["min_positive_signal_count"]
        ):
            level = "developing"
            action = "continue_observation"
            reason = "Initial stability, use, and positive feedback evidence is present."
        else:
            level = "nascent"
            action = "collect_evidence"
            reason = "More time, usage, or feedback evidence is needed."

        evidence = {
            "confidence_complete": confidence_complete,
            "provenance_complete": provenance_complete,
            "usage_count": usage_count,
            "positive_signal_count": positive_count,
            "review_signal_count": review_count,
            "stability": {
                "status": stability,
                "change_count": change_count,
                "age_days": age_days,
            },
            "references": evidence_refs or [f"fact:{key}"],
        }
        results.append({
            "key": key,
            "memory_type": memory.get("memory_type", "fact"),
            "level": level,
            "evidence": evidence,
        })
        if action:
            recommendations.append({
                "key": key,
                "action": action,
                "reason": reason,
                "evidence_refs": evidence["references"],
            })

    level_counts = {
        level: sum(item["level"] == level for item in results)
        for level in ("nascent", "developing", "established", "mature", "review_required")
    }
    return {
        "evaluated_at": now.isoformat(),
        "criteria": criteria,
        "memory_count": len(results),
        "level_counts": level_counts,
        "recommendation_count": len(recommendations),
        "memories": results,
        "recommendations": recommendations,
    }


def evaluate_knowledge_self_steering(
    maturity_report: Mapping[str, Any],
    approved_knowledge_evaluations: Sequence[Mapping[str, Any]],
    *,
    maturity_report_id: str | None = None,
) -> dict[str, Any]:
    """Create deterministic, evidence-linked guidance without changing knowledge."""
    suggestions: list[dict[str, Any]] = []
    for item in maturity_report.get("memories", ()):
        key = str(item["key"])
        level = item.get("level")
        evidence = item.get("evidence", {})
        if level == "review_required":
            action = "review_fact"
            priority = 100 + int(evidence.get("review_signal_count", 0))
            reason = "Review signals exist; a person should verify this active fact."
        elif level == "nascent":
            if not evidence.get("confidence_complete") or not evidence.get("provenance_complete"):
                action = "complete_fact_evidence"
                priority = 80
                reason = (
                    "Confidence or source attribution is incomplete; collect verified evidence."
                )
            else:
                action = "reinforce_fact_evidence"
                priority = 40
                reason = "More stable usage and outcome feedback is needed to assess this fact."
        elif level in {"developing", "established"}:
            action = "continue_fact_observation"
            priority = 20
            reason = "Continue observing validated use and feedback before relying on this fact."
        else:
            continue
        refs = list(evidence.get("references", ()))
        if not refs:
            refs = [f"fact:{key}"]
        suggestions.append({
            "area": key,
            "source_type": "fact",
            "action": action,
            "priority": priority,
            "reason": reason,
            "evidence_refs": sorted(set(refs)),
            "signals": {"maturity_level": level, **{
                name: evidence.get(name) for name in (
                    "confidence_complete", "provenance_complete", "usage_count",
                    "positive_signal_count", "review_signal_count",
                )
            }},
        })

    for item in approved_knowledge_evaluations:
        knowledge_id = str(item["knowledge_id"])
        failed = int(item.get("failed_count", 0))
        helpful = int(item.get("helpful_count", 0))
        decision = item.get("decision")
        if failed >= 2:
            action, priority = "review_approved_knowledge", 100 + failed
            reason = (
                "Repeated unsuccessful applications warrant human review of this approved guidance."
            )
        elif failed == 1:
            action, priority = "monitor_approved_knowledge", 70
            reason = "One unsuccessful application is recorded; monitor another validated outcome."
        elif helpful:
            action, priority = "reinforce_approved_knowledge", 40
            reason = "Helpful applications support continued use with outcome monitoring."
        else:
            action, priority = "collect_knowledge_outcomes", 20
            reason = (
                "No validated application feedback is available; collect outcomes before steering."
            )
        refs = {f"knowledge:{knowledge_id}"}
        if item.get("source_outcome_id"):
            refs.add(f"outcome:{item['source_outcome_id']}")
        for evidence in item.get("evidence", ()):
            refs.update((
                f"usage:{evidence['usage_event_id']}",
                f"feedback:{evidence['id']}",
                f"outcome:{evidence['source_outcome_id']}",
                f"outcome:{evidence['execution_outcome_id']}",
            ))
        suggestions.append({
            "area": knowledge_id,
            "source_type": "approved_goal_knowledge",
            "action": action,
            "priority": priority,
            "reason": reason,
            "evidence_refs": sorted(refs),
            "signals": {
                "decision": decision,
                "helpful_count": helpful,
                "failed_count": failed,
            },
        })

    suggestions.sort(key=lambda item: (-item["priority"], item["area"], item["action"]))
    return {
        "evaluated_at": maturity_report.get("evaluated_at"),
        "maturity_report_id": maturity_report_id,
        "fact_count": len(maturity_report.get("memories", ())),
        "approved_knowledge_count": len(approved_knowledge_evaluations),
        "suggestion_count": len(suggestions),
        "suggestions": suggestions,
    }


def evaluate_knowledge_optimization_candidates(
    approved_reports: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Derive deterministic, evidence-linked advisory candidates from approved reports."""
    candidates: list[dict[str, Any]] = []
    for report in approved_reports:
        report_id = str(report["id"])
        payload = report.get("report", {})
        for suggestion in payload.get("suggestions", ()):
            refs = sorted({str(ref) for ref in suggestion.get("evidence_refs", ()) if ref})
            if not refs:
                continue
            source_type = suggestion.get("source_type")
            action = suggestion.get("action")
            # Only low-risk observation and evidence collection actions become candidates.
            if action not in {
                "complete_fact_evidence", "reinforce_fact_evidence",
                "continue_fact_observation", "monitor_approved_knowledge",
                "reinforce_approved_knowledge", "collect_knowledge_outcomes",
            }:
                continue
            candidate = {
                "source_report_id": report_id,
                "area": str(suggestion.get("area", "")),
                "source_type": source_type,
                "action": action,
                "priority": int(suggestion.get("priority", 0)),
                "reason": str(suggestion.get("reason", "")),
                "evidence_refs": refs,
                "signals": dict(suggestion.get("signals", {})),
                "risk": "low",
                "advisory_only": True,
            }
            identity = json.dumps(
                candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            )
            candidate["id"] = "knowledge-optimization:" + hashlib.sha256(
                identity.encode("utf-8")
            ).hexdigest()
            candidates.append(candidate)
    candidates.sort(key=lambda item: (
        -item["priority"], item["source_report_id"], item["area"], item["id"],
    ))
    return candidates


def evaluate_knowledge_optimization_candidate(
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a stable safety and provenance evaluation without mutating knowledge."""
    valid_actions = {
        "complete_fact_evidence", "reinforce_fact_evidence",
        "continue_fact_observation", "monitor_approved_knowledge",
        "reinforce_approved_knowledge", "collect_knowledge_outcomes",
    }
    refs = sorted({str(ref) for ref in candidate.get("evidence_refs", ()) if ref})
    eligible = (
        candidate.get("action") in valid_actions
        and candidate.get("risk") == "low"
        and candidate.get("advisory_only") is True
        and bool(candidate.get("source_report_id"))
        and bool(refs)
    )
    return {
        "candidate_id": candidate.get("id"),
        "eligible": eligible,
        "decision": (
            "eligible_low_risk_advisory" if eligible
            else "ineligible_missing_safety_or_evidence"
        ),
        "evidence_refs": refs,
    }


def evaluate_knowledge_consolidation_proposals(
    approved_candidates: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Group explicitly approved optimization candidates into advisory proposals."""
    groups: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    for candidate in approved_candidates:
        if (
            candidate.get("status") != "approved"
            or candidate.get("advisory_only") is not True
            or not candidate.get("id")
            or not candidate.get("source_report_id")
        ):
            continue
        refs = sorted({str(ref) for ref in candidate.get("evidence_refs", ()) if ref})
        if not refs:
            continue
        key = (
            str(candidate.get("area", "")),
            str(candidate.get("source_type", "")),
            str(candidate.get("action", "")),
        )
        groups.setdefault(key, []).append(candidate)

    proposals = []
    for (area, source_type, action), candidates in sorted(groups.items()):
        source_candidates = sorted(candidates, key=lambda item: str(item["id"]))
        proposal = {
            "proposal_type": "approved_optimization_consolidation",
            "area": area,
            "source_type": source_type,
            "action": action,
            "priority": max(int(candidate.get("priority", 0)) for candidate in candidates),
            "source_candidate_ids": [str(item["id"]) for item in source_candidates],
            "source_report_ids": sorted({str(item["source_report_id"]) for item in candidates}),
            "evidence_refs": sorted({
                str(ref) for item in candidates for ref in item.get("evidence_refs", ()) if ref
            }),
            "candidate_snapshots": [
                {
                    "candidate_id": str(item["id"]),
                    "source_report_id": str(item["source_report_id"]),
                    "reason": str(item.get("reason", "")),
                    "evidence_refs": sorted({
                        str(ref) for ref in item.get("evidence_refs", ()) if ref
                    }),
                }
                for item in source_candidates
            ],
            "advisory_only": True,
        }
        identity = json.dumps(
            proposal, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        proposal["id"] = "knowledge-consolidation:" + hashlib.sha256(
            identity.encode("utf-8")
        ).hexdigest()
        proposals.append(proposal)
    return proposals
