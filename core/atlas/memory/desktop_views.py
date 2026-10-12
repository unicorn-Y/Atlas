"""Desktop projections of authoritative UnifiedRecord responses."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def _text(value: Any) -> str:
    return value if isinstance(value, str) else str(value or "")


def _milliseconds(value: Any) -> int | None:
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp() * 1000)
    except (ValueError, TypeError, OverflowError):
        return None


async def records(facade: Any, limit: int, *, facets: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    refs: set[str] = set()
    for facet in facets or (None,):
        cursor = None
        seen: set[str] = set()
        count = 0
        while count < limit:
            page = await facade.list_records(facet=facet, cursor=cursor, limit=min(200, limit - count))
            items = page.get("items") or []
            count += len(items)
            for row in items:
                ref = row.get("record_ref")
                if ref not in refs:
                    rows.append(row)
                    refs.add(ref)
            cursor = page.get("next_cursor")
            if not cursor:
                break
            if cursor in seen:
                raise ValueError("统一记忆分页游标重复，无法完整读取。")
            seen.add(cursor)
    rows.sort(key=lambda row: row.get("recorded_at") or "", reverse=True)
    return rows[:limit]


def facts(rows: list[dict[str, Any]], history: bool) -> dict[str, Any]:
    result = []
    for row in rows:
        if row.get("facet") not in {"FACT", "PREFERENCE", "STATE", "HABIT", "RELATION"}:
            continue
        lifecycle = row.get("lifecycle", "ACTIVE")
        if not history and lifecycle != "ACTIVE":
            continue
        content = row.get("content") or {}
        # Legacy operational reflections share FACT's storage projection, but
        # are not personal facts and must not appear in "About you".
        if str(content.get("legacy_ref") or "").startswith("legacy:agent_reflections:"):
            continue
        valid_time = row.get("valid_time") or {}
        result.append({
            "id": row["record_ref"],
            "factKey": _text(content.get("key") or row["record_ref"]),
            "value": _text(content.get("value") or content.get("summary") or content.get("text")),
            "text": _text(content.get("text") or content.get("value") or content.get("summary") or content.get("title")),
            "status": str(lifecycle).lower(),
            "evidenceQuote": _text(content.get("evidence_quote")),
            "createdAt": _milliseconds(row.get("recorded_at")),
            "updatedAt": _milliseconds(row.get("recorded_at")),
            "forgetAfter": _milliseconds(valid_time.get("valid_to")),
            "record_revision": row.get("record_revision"),
        })
    return {"facts": result, "source": "unified-memory", "can_delete": False}


def library(rows: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    result = []
    for row in rows:
        facet, ref = row.get("facet"), str(row.get("record_ref") or "")
        matches = (facet == "SKILL" if kind == "skills" else
                   ref.startswith("strategy:") if kind == "policies" else facet == "KNOWLEDGE")
        if not matches:
            continue
        content = row.get("content") or {}
        title = _text(content.get("title") or content.get("name") or content.get("key") or ref)
        detail = _text(content.get("text") or content.get("summary") or content.get("value") or content.get("procedure"))
        result.append({"id": ref, "name": title, "title": title,
                       "invocationGuide": detail, "trigger": detail, "body": detail,
                       "status": str(row.get("lifecycle") or "ACTIVE").lower(),
                       "updatedAt": row.get("recorded_at")})
    key = {"skills": "skills", "policies": "policies", "world_model": "worldModels"}[kind]
    return {key: result, "source": "unified-memory", "can_delete": False}
