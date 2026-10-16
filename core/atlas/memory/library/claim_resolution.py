"""Deterministic claim precedence over Markdown-backed metadata."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

_SOURCE_RANK = {
    "legacy_unknown": 0,
    "model_inference": 1,
    "tool_observation": 2,
    "user_assertion": 3,
}


def _metadata(entry: Any) -> Mapping[str, Any]:
    if isinstance(entry, Mapping):
        return entry
    meta = getattr(entry, "meta", None)
    if callable(meta):
        return meta()
    if isinstance(meta, Mapping):
        return meta
    extra = getattr(entry, "extra_meta", None)
    return extra if isinstance(extra, Mapping) else {}


def _get(entry: Any, key: str, default: Any = None) -> Any:
    meta = _metadata(entry)
    if key in meta:
        return meta[key]
    return getattr(entry, key, default)


def _date(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _ids(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, (list, tuple, set)):
        return sorted({item for item in value if isinstance(item, str) and item})
    return []


def is_current_claim(entry: Any, now: datetime | str | None = None) -> bool:
    """Return whether an entry is marked current and is within its valid-time window.

    A caller rebuilding from Markdown should pass the persisted Entry. M4 marks
    superseded/retracted history on that entry; this predicate also understands
    the relation ids emitted by older pages when M4 has not yet normalized them.
    """
    meta = _metadata(entry)
    if meta.get("superseded") is True or meta.get("retracted") is True:
        return False
    if meta.get("superseded_by") or meta.get("retracted_by"):
        return False

    moment = _date(now) if isinstance(now, str) else now
    if moment is None:
        moment = datetime.now(UTC)
    elif moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    else:
        moment = moment.astimezone(UTC)

    start = _date(_get(entry, "valid_from"))
    end = _date(_get(entry, "valid_to"))
    return not ((start is not None and moment < start) or (end is not None and moment >= end))


def resolve_claim_conflict(existing: Any, proposed: Any) -> dict[str, Any]:
    """Choose a claim and describe Markdown metadata M4 should apply.

    The function is pure: it does not write Markdown, touch the store, or open
    SessionDB. A proposed user assertion that explicitly links a correction or
    retraction is treated as the user's correction before ordinary ranking.
    """
    old_level = _get(existing, "source_level", "legacy_unknown")
    new_level = _get(proposed, "source_level", "legacy_unknown")
    old_rank = _SOURCE_RANK.get(old_level, 0)
    new_rank = _SOURCE_RANK.get(new_level, 0)
    explicit_correction = (
        new_level == "user_assertion"
        and bool(_ids(_get(proposed, "supersedes")) or _ids(_get(proposed, "retracts")))
    )

    if explicit_correction:
        proposed_wins, reason = True, "user_correction"
    elif new_rank != old_rank:
        proposed_wins, reason = new_rank > old_rank, "source_level"
    else:
        old_time = _date(_get(existing, "recorded_at"))
        new_time = _date(_get(proposed, "recorded_at"))
        # Missing or invalid record times do not displace a known existing claim.
        proposed_wins = new_time is not None and (old_time is None or new_time > old_time)
        reason = "recorded_at" if old_time or new_time else "undated_existing_wins"

    winner, loser = (proposed, existing) if proposed_wins else (existing, proposed)
    loser_id = _get(loser, "id", "") or ""
    supersedes = _ids(_get(proposed, "supersedes")) if proposed_wins else []
    if proposed_wins and loser_id and loser_id not in supersedes:
        supersedes.append(loser_id)
    retracts = _ids(_get(proposed, "retracts")) if proposed_wins else []
    winner_id = _get(winner, "id", "") or ""
    losing_claim_retracted = loser_id in retracts
    return {
        "winner": winner,
        "winner_id": winner_id,
        "superseded": [loser_id] if loser_id else [],
        "retracted": retracts,
        "reason": reason,
        "explanation": {
            "existing_source_level": old_level,
            "proposed_source_level": new_level,
            "existing_recorded_at": _get(existing, "recorded_at"),
            "proposed_recorded_at": _get(proposed, "recorded_at"),
            "explicit_user_correction": explicit_correction,
        },
        "suggested_metadata": {
            "superseded_by": [winner_id] if loser_id and winner_id else [],
            "retracted_by": [winner_id] if losing_claim_retracted and winner_id else [],
        },
        "winner_metadata": {
            "supersedes": supersedes,
            "retracts": retracts,
        },
    }
