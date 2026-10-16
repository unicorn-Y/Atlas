"""Hybrid keyword/vector ranking with temporal decay and MMR diversity."""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any

from .index import tokenize

_DATED = re.compile(r"^(?:日记|经历)/\d{4}-\d{2}-\d{2}\.md$")


def temporal_decay(
    path: str, at: str | datetime, now: datetime, half_life_days: float = 30.0
) -> float:
    if not _DATED.match(path.replace("\\", "/")):
        return 1.0
    try:
        stamp = at if isinstance(at, datetime) else datetime.fromisoformat(str(at))
        if stamp.tzinfo is None and now.tzinfo is not None:
            stamp = stamp.replace(tzinfo=now.tzinfo)
        age = max(0.0, (now - stamp).total_seconds() / 86400)
        return math.exp(-(math.log(2) / half_life_days) * age)
    except (TypeError, ValueError, OverflowError):
        try:
            day = datetime.fromisoformat(path.split("/")[-1][:-3]).date()
            age = max(0, (now.date() - day).days)
            return 0.5 ** (age / half_life_days)
        except ValueError:
            return 1.0


def merge_scores(
    keyword: list[dict[str, Any]],
    vector: list[dict[str, Any]],
    *,
    now: datetime,
    limit: int,
    vector_weight: float = 0.7,
    text_weight: float = 0.3,
    mmr_lambda: float = 0.7,
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    max_keyword = max((float(row.get("score", 0)) for row in keyword), default=0) or 1.0
    for row in keyword:
        item = {
            **row,
            "text_score": min(1.0, max(0.0, float(row.get("score", 0)) / max_keyword)),
            "vector_score": 0.0,
        }
        by_id[str(row["id"])] = item
    for row in vector:
        item = by_id.setdefault(str(row["id"]), {**row, "text_score": 0.0, "vector_score": 0.0})
        item["vector_score"] = max(0.0, min(1.0, float(row.get("vector_score", 0))))
        for key in ("path", "kind", "bucket", "text", "src", "at", "ref", "until", "quote"):
            if key in row:
                item[key] = row[key]
    merged = []
    for row in by_id.values():
        raw_score = vector_weight * row["vector_score"] + text_weight * row["text_score"]
        decay = temporal_decay(row.get("path", ""), row.get("at", ""), now)
        row["score"] = raw_score * decay
        row["rank_reasons"] = {
            "keyword_score": round(float(row["text_score"]), 4),
            "vector_score": round(float(row["vector_score"]), 4),
            "temporal_decay": round(decay, 4),
            "fusion": {"keyword_weight": text_weight, "vector_weight": vector_weight},
        }
        merged.append(row)
    merged.sort(key=lambda row: row["score"], reverse=True)
    if len(merged) <= limit:
        return merged
    return mmr_select(merged, limit=limit, lambda_=mmr_lambda)


def _similarity(left: str, right: str) -> float:
    a, b = tokenize(left), tokenize(right)
    return len(a & b) / len(a | b) if a or b else float(left.casefold() == right.casefold())


def mmr_select(
    rows: list[dict[str, Any]], *, limit: int, lambda_: float = 0.7
) -> list[dict[str, Any]]:
    remaining = [(row, tokenize(str(row.get("text", "")))) for row in rows]
    if not remaining or limit <= 0:
        return []
    low, high = (
        min(float(row.get("score", 0)) for row, _tokens in remaining),
        max(float(row.get("score", 0)) for row, _tokens in remaining),
    )
    relevance = [
        1.0 if high == low else (float(row.get("score", 0)) - low) / (high - low)
        for row, _tokens in remaining
    ]
    max_similarity = [0.0] * len(remaining)
    selected: list[dict[str, Any]] = []
    while remaining and len(selected) < limit:
        best_index = max(
            range(len(remaining)),
            key=lambda index: (
                lambda_ * relevance[index] - (1 - lambda_) * max_similarity[index],
                float(remaining[index][0].get("score", 0)),
            ),
        )
        row, tokens = remaining.pop(best_index)
        relevance.pop(best_index)
        max_similarity.pop(best_index)
        selected.append(row)
        text = str(row.get("text", "")).casefold()
        for index, (other, other_tokens) in enumerate(remaining):
            similarity = (
                len(tokens & other_tokens) / len(tokens | other_tokens)
                if tokens or other_tokens
                else float(text == str(other.get("text", "")).casefold())
            )
            max_similarity[index] = max(max_similarity[index], similarity)
    return selected


__all__ = ["merge_scores", "mmr_select", "temporal_decay"]
