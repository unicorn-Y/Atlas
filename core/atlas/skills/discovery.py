"""Deterministic, read-only discovery over the canonical Skill Registry."""

from __future__ import annotations

import re
from typing import Any

from atlas.skills.registry import SkillRegistry

_TOKEN_RE = re.compile(r"[\w-]+", re.UNICODE)
_FIELD_WEIGHTS = {
    "name": 100,
    "aliases": 90,
    "keywords": 80,
    "tags": 70,
    "capabilities": 60,
    "tools": 55,
    "category": 45,
    "description": 30,
    "examples": 25,
    "use_cases": 25,
    "requirements": 10,
}


def _tokens(value: str) -> list[str]:
    return [token.casefold() for token in _TOKEN_RE.findall(value)]


def _flatten(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for key, child in value.items() for item in ([str(key)] + _flatten(child))]
    if isinstance(value, list):
        return [item for child in value for item in _flatten(child)]
    return []


def _score(skill: dict[str, Any], query: str) -> dict[str, Any]:
    query_tokens = _tokens(query)
    if not query_tokens:
        return {"relevance_score": 0, "matched_fields": [], "match_reasons": []}

    fields = {
        "name": [skill["name"]],
        "aliases": skill.get("aliases", []),
        "keywords": skill.get("keywords", []),
        "tags": skill.get("tags", []),
        "capabilities": skill.get("capabilities", []),
        "tools": skill.get("tools", []),
        "category": [skill.get("category", "")],
        "description": [skill["description"]],
        "examples": skill.get("examples", []),
        "use_cases": skill.get("use_cases", []),
        "requirements": _flatten(skill.get("requirements", [])),
    }
    normalized_query = " ".join(query_tokens)
    exact_name = " ".join(_tokens(skill["name"])) == normalized_query
    score = 1000 if exact_name else 0
    matched: list[str] = []
    reasons: list[str] = []
    for field, values in fields.items():
        searchable = [(value.casefold(), set(_tokens(value))) for value in values if value]
        hits = [
            token for token in query_tokens
            if any(token in text or token in words for text, words in searchable)
        ]
        if hits:
            matched.append(field)
            score += _FIELD_WEIGHTS[field] * len(set(hits))
            reasons.append(f"Matched {field}: {', '.join(dict.fromkeys(hits))}")
    if exact_name:
        reasons.insert(0, "Exact skill name match")
    return {"relevance_score": score, "matched_fields": matched, "match_reasons": reasons}


class SkillDiscovery:
    """Searches Registry records without changing their status or permissions."""

    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry

    def discover(
        self,
        *,
        query: str = "",
        name: str | None = None,
        capability: str | None = None,
        tool: str | None = None,
        status: str = "active",
        source: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        if not isinstance(query, str):
            raise ValueError("query must be a string")
        filter_values = (
            ("name", name), ("capability", capability), ("tool", tool), ("source", source),
        )
        for label, value in filter_values:
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{label} must be a string")
        if status not in {"active", "disabled", "invalid", "rejected", "all"}:
            raise ValueError("status must be active, disabled, invalid, rejected, or all")
        if not isinstance(limit, int) or not isinstance(offset, int):
            raise ValueError("limit and offset must be integers")
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("limit must be 1-100 and offset must be non-negative")

        registry_status = None if status in {"invalid", "rejected", "all"} else status
        skills = self.registry.list(status=registry_status)
        candidates = []
        for skill in skills:
            if status in {"invalid", "rejected"} and skill.get("validation_status") != status:
                continue
            if status == "all" and skill.get("validation_status") != "valid":
                continue
            if name and skill["name"].casefold() != name.casefold():
                continue
            capabilities = {item.casefold() for item in skill.get("capabilities", [])}
            if capability and capability.casefold() not in capabilities:
                continue
            if tool and tool.casefold() not in {item.casefold() for item in skill.get("tools", [])}:
                continue
            if source and skill.get("source", "").casefold() != source.casefold():
                continue
            ranked = {**skill, **_score(skill, query)}
            if query.strip() and not ranked["matched_fields"]:
                continue
            candidates.append(ranked)

        candidates.sort(key=lambda item: (-item["relevance_score"], item["name"], item["version"]))
        total = len(candidates)
        return {
            "count": total,
            "limit": limit,
            "offset": offset,
            "results": candidates[offset:offset + limit],
        }
