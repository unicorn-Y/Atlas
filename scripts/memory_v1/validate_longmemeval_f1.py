#!/usr/bin/env python3
"""Validate the fixed LongMemEval subset against the pinned full S artifact.

This reads the locked source only. It never emits dialogue text or gold answers,
and it does not call any model or service.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

CANONICAL_SHA256 = "08d8dad4be43ee2049a22ff5674eb86725d0ce5ff434cde2627e5e8e7e117894"
CANONICAL_CATEGORIES = (
    "single-session-user",
    "single-session-assistant",
    "single-session-preference",
    "multi-session",
    "temporal-reasoning",
    "knowledge-update",
)
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SUBSET = ROOT / "docs/plan/MEMORY-V1/eval/longmemeval_subset.json"
DEFAULT_OUTPUT = ROOT / "docs/plan/MEMORY-V1/eval/F1-D-source-validation.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _session_turns(session: Any) -> list[dict[str, Any]]:
    # Canonical LongMemEval_S stores each history as an array of turns; the
    # IDs and dates are parallel arrays on the question row.
    if not isinstance(session, list):
        return []
    return [turn for turn in session if isinstance(turn, dict)]


def validate(dataset_path: Path, subset_path: Path) -> dict[str, Any]:
    dataset_hash = sha256(dataset_path)
    if dataset_hash != CANONICAL_SHA256:
        raise ValueError(
            f"canonical LongMemEval_S SHA256 mismatch: expected {CANONICAL_SHA256}, got {dataset_hash}"
        )
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    subset = json.loads(subset_path.read_text(encoding="utf-8"))
    if not isinstance(dataset, list) or not isinstance(subset.get("questions"), list):
        raise ValueError("source must be an array and subset must contain a questions array")

    subset_rows = subset["questions"]
    fixed_ids = [str(item.get("question_id") or "") for item in subset_rows]
    if len(fixed_ids) != 120 or len(set(fixed_ids)) != 120:
        raise ValueError(f"fixed subset must contain 120 unique IDs, got {len(fixed_ids)} rows / {len(set(fixed_ids))} IDs")
    if subset.get("categories") != list(CANONICAL_CATEGORIES):
        raise ValueError("fixed subset category ordering differs from the pinned six-category contract")
    subset_counts = Counter(str(item.get("question_type") or "") for item in subset_rows)
    if subset_counts != Counter({category: 20 for category in CANONICAL_CATEGORIES}):
        raise ValueError(f"fixed subset category balance mismatch: {dict(subset_counts)}")

    by_id: dict[str, dict[str, Any]] = {}
    for row in dataset:
        if isinstance(row, dict) and row.get("question_id") is not None:
            by_id[str(row["question_id"])] = row
    missing = [qid for qid in fixed_ids if qid not in by_id]
    if missing:
        raise ValueError(f"{len(missing)} fixed question IDs absent from canonical S: {missing[:10]}")

    per_category: dict[str, dict[str, int]] = defaultdict(
        lambda: {"questions": 0, "sessions": 0, "turns": 0, "content_chars": 0}
    )
    session_counts: list[int] = []
    turns_total = 0
    chars_total = 0
    oracle_count_mismatches = 0
    duplicate_session_id_occurrences = 0
    question_stats: list[dict[str, Any]] = []
    turn_roles: Counter[str] = Counter()
    non_string_content_turns = 0
    date_formats: Counter[str] = Counter()
    metadata_mismatches: dict[str, list[str]] = defaultdict(list)
    missing_sessions: list[str] = []
    for item in subset_rows:
        qid = str(item["question_id"])
        source = by_id[qid]
        for field in ("question_type", "question", "question_date", "answer_session_ids", "answer"):
            left = tuple(item.get(field) or ()) if field == "answer_session_ids" else item.get(field)
            right = tuple(source.get(field) or ()) if field == "answer_session_ids" else source.get(field)
            if left != right:
                metadata_mismatches[field].append(qid)
        sessions = source.get("haystack_sessions")
        if not isinstance(sessions, list):
            missing_sessions.append(qid)
            continue
        source_session_ids = source.get("haystack_session_ids")
        source_dates = source.get("haystack_dates")
        if not isinstance(source_session_ids, list) or len(source_session_ids) != len(sessions):
            raise ValueError(f"canonical S session IDs do not align with histories for {qid}")
        if not isinstance(source_dates, list) or len(source_dates) != len(sessions):
            raise ValueError(f"canonical S session dates do not align with histories for {qid}")
        for value in source_dates:
            date_text = str(value or "")
            if re.match(r"^\d{4}/\d{1,2}/\d{1,2}\s+\([A-Za-z]{3}\)\s+\d{1,2}:\d{2}$", date_text):
                date_formats["YYYY/M/D (Ddd) HH:MM"] += 1
            elif re.match(r"^\d{4}-\d{2}-\d{2}T", date_text):
                date_formats["ISO datetime"] += 1
            else:
                date_formats["other"] += 1
        session_counts.append(len(sessions))
        if int(item.get("haystack_session_count") or 0) != len(sessions):
            oracle_count_mismatches += 1
        category = str(source.get("question_type") or "")
        per_category[category]["questions"] += 1
        per_category[category]["sessions"] += len(sessions)
        q_turns = 0
        q_chars = 0
        q_content_tokens_low = 0
        q_content_tokens_high = 0
        q_observer_calls_low = 0
        q_observer_calls_high = 0
        session_ids = {str(value) for value in source_session_ids if str(value)}
        if any(not str(value).strip() for value in source_session_ids):
            raise ValueError(f"canonical S has an empty session ID for {qid}")
        duplicate_session_id_occurrences += len(source_session_ids) - len(session_ids)
        for session in sessions:
            session_chars = 0
            for turn in _session_turns(session):
                q_turns += 1
                turn_roles[str(turn.get("role") or "<missing>").lower()] += 1
                content = turn.get("content")
                if isinstance(content, str):
                    q_chars += len(content)
                    session_chars += len(content)
                else:
                    non_string_content_turns += 1
            if session_chars:
                tokens_low = max(1, (session_chars + 4) // 5)
                tokens_high = max(1, (session_chars * 2 + 6) // 7)  # ceil(chars / 3.5)
                q_content_tokens_low += tokens_low
                q_content_tokens_high += tokens_high
                q_observer_calls_low += max(1, (tokens_low + 9_999) // 10_000)
                q_observer_calls_high += max(1, (tokens_high + 9_999) // 10_000)
        if not sessions or q_turns == 0:
            missing_sessions.append(qid)
        per_category[category]["turns"] += q_turns
        per_category[category]["content_chars"] += q_chars
        turns_total += q_turns
        chars_total += q_chars
        question_stats.append({
            "question_id": qid,
            "question_type": category,
            "sessions": len(sessions),
            "turns": q_turns,
            "content_chars": q_chars,
            "content_tokens_char_div_5": q_content_tokens_low,
            "content_tokens_char_div_3_5": q_content_tokens_high,
            "observer_calls_char_div_5": q_observer_calls_low,
            "observer_calls_char_div_3_5": q_observer_calls_high,
        })
    critical_mismatches = {
        key: value for key, value in metadata_mismatches.items()
        if key in {"question_type", "question"}
    }
    if critical_mismatches:
        raise ValueError(f"fixed question category/text differs from canonical S: {critical_mismatches}")
    if missing_sessions:
        raise ValueError(f"missing or empty full-S session history for {len(missing_sessions)} IDs: {missing_sessions[:10]}")

    return {
        "status": "PASSED",
        "source": {
            "path": str(dataset_path.resolve()),
            "bytes": dataset_path.stat().st_size,
            "sha256": dataset_hash,
            "expected_sha256": CANONICAL_SHA256,
            "records": len(dataset),
        },
        "subset": {
            "path": str(subset_path.resolve()),
            "sha256": sha256(subset_path),
            "declared_source_file_used": subset.get("metadata", {}).get("source_file_used"),
            "declared_source_sha256": subset.get("metadata", {}).get("source_file_sha256"),
            "fixed_ids": len(fixed_ids),
            "unique_ids": len(set(fixed_ids)),
            "question_text_and_category_match_canonical": True,
            "gold_answer_matches_canonical": not metadata_mismatches.get("answer"),
            "canonical_metadata_mismatch_counts": {
                key: len(value) for key, value in metadata_mismatches.items()
            },
            "canonical_metadata_mismatch_sample_ids": {
                key: value[:5] for key, value in metadata_mismatches.items()
            },
            "uses_full_haystack_sessions": True,
            "oracle_session_count_differs_for_questions": oracle_count_mismatches,
        },
        "categories": {
            category: dict(per_category[category])
            for category in CANONICAL_CATEGORIES
        },
        "history_stats": {
            "total_sessions": sum(session_counts),
            "total_turns": turns_total,
            "total_content_chars": chars_total,
            "duplicate_session_id_occurrences": duplicate_session_id_occurrences,
            "sessions_per_question_min": min(session_counts),
            "sessions_per_question_median": sorted(session_counts)[len(session_counts) // 2],
            "sessions_per_question_max": max(session_counts),
            "estimated_content_tokens_char_div_5": sum(q["content_tokens_char_div_5"] for q in question_stats),
            "estimated_content_tokens_char_div_3_5": sum(q["content_tokens_char_div_3_5"] for q in question_stats),
            "estimated_observer_calls_char_div_5": sum(q["observer_calls_char_div_5"] for q in question_stats),
            "estimated_observer_calls_char_div_3_5": sum(q["observer_calls_char_div_3_5"] for q in question_stats),
            "turn_roles": dict(turn_roles),
            "non_string_content_turns": non_string_content_turns,
            "session_date_formats": dict(date_formats),
        },
        "question_stats": question_stats,
        "method": (
            "Every fixed ID is resolved to its canonical LongMemEval_S row; question metadata is compared; "
            "the runner input source is haystack_sessions, not oracle-shortened evidence sessions."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Isolated pinned LongMemEval_S artifact")
    parser.add_argument("--subset", type=Path, default=DEFAULT_SUBSET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = validate(args.source, args.subset)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    print(f"report={args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
