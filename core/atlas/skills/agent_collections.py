"""W7 per-agent skill collections (``atlas.skills.agent_collections``).

Skills have exactly ONE entity — the ``skill_registry(name, version)`` row plus
one payload on disk. What an agent "has" is only **relation rows** here, never a
copied skill: ``agent_skills(agent_id, skill_name, enabled, relation)`` with
``relation ∈ {default_enabled, learned, suggested, adopted}`` (r8 §5.1 table 5;
r8 §5.3 "实体不复制 N 份").

``effective_skills`` semantics (frozen by the lane contract):

1. A row with ``enabled=1``  → effective for this agent (per-agent opt-in wins
   over a globally disabled lifecycle state — e.g. the owning agent keeps its
   ``learned`` skill even if an operator later disables it globally).
2. A row with ``enabled=0``  → NOT effective, even when globally active
   (per-agent opt-out wins over the global enable).
3. No row                    → follows the global registry status
   (``active`` = effective).

``learned`` rows are created with ``enabled=1`` when a proposal is applied (see
``SkillProposalStore.approve``), which is the "learned 默认启用" rule. The same
SQLite file as the Registry is used (single store; ``registry.py`` untouched).
Usage telemetry (``skill_usage``) accumulates per ``(skill_name, agent_id)``
plus an aggregate row under ``agent_id='*'``.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from atlas.skills.acquisition import NAME_RE

log = structlog.get_logger()

#: Relation vocabulary (r8 §5.1).
RELATIONS = ("default_enabled", "learned", "suggested", "adopted")
#: Aggregate telemetry row (all agents).
AGGREGATE_AGENT = "*"

SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_skills (
    agent_id TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    enabled INTEGER NOT NULL,
    relation TEXT NOT NULL CHECK (relation IN (
        'default_enabled', 'learned', 'suggested', 'adopted')),
    note TEXT,
    enabled_at TEXT,
    disabled_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (agent_id, skill_name)
);
CREATE INDEX IF NOT EXISTS idx_agent_skills_agent ON agent_skills(agent_id);
CREATE TABLE IF NOT EXISTS skill_usage (
    skill_name TEXT NOT NULL,
    agent_id TEXT NOT NULL DEFAULT '*',
    version TEXT,
    use_count INTEGER NOT NULL DEFAULT 0,
    last_used_at TEXT,
    first_seen_at TEXT NOT NULL,
    PRIMARY KEY (skill_name, agent_id)
);
"""


class CollectionError(ValueError):
    """Invalid relation / identity input (HTTP 422 semantics)."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _canonical_name(name: str) -> str:
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise CollectionError(
            f"技能名「{name}」不符合 Atlas 规范（只能用小写字母、数字和连字符）。")
    return name


class AgentSkillCollections:
    """agent↔skill relation rows + usage telemetry over the Registry database."""

    def __init__(self, registry: Any) -> None:
        self.registry = registry
        with closing(self._connect()) as db, db:
            db.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.registry.path)
        db.row_factory = sqlite3.Row
        return db

    # ------------------------------------------------------------------
    # Relation rows
    # ------------------------------------------------------------------

    def set_agent_skill(
        self, agent_id: str, skill_name: str, *, enabled: bool,
        relation: str = "adopted", note: str | None = None,
    ) -> dict[str, Any]:
        """Upsert one relation row (the skill entity itself is never copied)."""
        if not isinstance(agent_id, str) or not agent_id.strip():
            raise CollectionError("agent_id 不能为空。")
        if relation not in RELATIONS:
            raise CollectionError(
                f"relation 只支持 {'、'.join(RELATIONS)}。")
        name = _canonical_name(skill_name)
        agent_id = agent_id.strip()
        now = _now()
        with closing(self._connect()) as db, db:
            db.execute(
                "INSERT INTO agent_skills (agent_id, skill_name, enabled, relation, note, "
                "enabled_at, disabled_at, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(agent_id, skill_name) DO UPDATE SET "
                "enabled=excluded.enabled, relation=excluded.relation, "
                "note=COALESCE(excluded.note, agent_skills.note), "
                "enabled_at=CASE WHEN excluded.enabled=1 THEN excluded.updated_at "
                "ELSE agent_skills.enabled_at END, "
                "disabled_at=CASE WHEN excluded.enabled=0 THEN excluded.updated_at "
                "ELSE agent_skills.disabled_at END, "
                "updated_at=excluded.updated_at",
                (agent_id, name, 1 if enabled else 0, relation, note,
                 now if enabled else None, None if enabled else now, now, now),
            )
        log.info("skills.agent_skill_set", agent_id=agent_id, skill=name,
                 enabled=enabled, relation=relation)
        row = self.get_agent_skill(agent_id, name)
        assert row is not None
        return row

    def get_agent_skill(self, agent_id: str, skill_name: str) -> dict[str, Any] | None:
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT * FROM agent_skills WHERE agent_id=? AND skill_name=?",
                (agent_id, skill_name),
            ).fetchone()
        return self._relation_dict(row) if row else None

    def list_agent_skills(self, agent_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT * FROM agent_skills WHERE agent_id=? "
                "ORDER BY skill_name COLLATE BINARY", (agent_id,),
            ).fetchall()
        return [self._relation_dict(row) for row in rows]

    def remove_agent_skill(self, agent_id: str, skill_name: str) -> bool:
        with closing(self._connect()) as db, db:
            cursor = db.execute(
                "DELETE FROM agent_skills WHERE agent_id=? AND skill_name=?",
                (agent_id, skill_name),
            )
            return cursor.rowcount > 0

    @staticmethod
    def _relation_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "agent_id": row["agent_id"],
            "skill_name": row["skill_name"],
            "enabled": bool(row["enabled"]),
            "relation": row["relation"],
            "note": row["note"],
            "enabled_at": row["enabled_at"],
            "disabled_at": row["disabled_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    # ------------------------------------------------------------------
    # Effective view (per-agent projection of the ONE registry)
    # ------------------------------------------------------------------

    def effective_skills(self, agent_id: str) -> list[dict[str, Any]]:
        """Skills this agent will actually see, with the deciding rule per row.

        See the module docstring for the frozen semantics. ``decision`` records
        why: ``per_agent`` (a relation row decided) or ``global`` (no row — the
        registry status decided).
        """
        by_name = {row["skill_name"]: row for row in self.list_agent_skills(agent_id)}
        latest: dict[str, dict[str, Any]] = {}
        active: set[str] = set()
        for record in self.registry.list():
            existing = latest.get(record["name"])
            if existing is None or record.get("updated_at", "") >= existing.get(
                    "updated_at", ""):
                latest[record["name"]] = record
            if record["status"] == "active":
                active.add(record["name"])
        names = sorted(set(by_name) | set(latest))
        effective: list[dict[str, Any]] = []
        for name in names:
            row = by_name.get(name)
            record = latest.get(name)
            if row is not None:
                is_effective = bool(row["enabled"])
                decision = "per_agent"
            else:
                is_effective = name in active
                decision = "global"
            effective.append({
                "skill_name": name,
                "relation": row["relation"] if row else None,
                "enabled": bool(row["enabled"]) if row else None,
                "effective": is_effective,
                "decision": decision,
                "version": (record or {}).get("version"),
                "description": (record or {}).get("description", ""),
            })
        return effective

    def default_enabled_skills(self) -> list[str]:
        """Skill names marked ``default_enabled`` on any agent (factory defaults)."""
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT DISTINCT skill_name FROM agent_skills WHERE relation='default_enabled' "
                "ORDER BY skill_name COLLATE BINARY",
            ).fetchall()
        return [row["skill_name"] for row in rows]

    # ------------------------------------------------------------------
    # Usage telemetry
    # ------------------------------------------------------------------

    def record_usage(
        self, skill_name: str, agent_id: str = AGGREGATE_AGENT,
        version: str | None = None,
    ) -> dict[str, Any]:
        """Accumulate one use on the per-agent row AND the aggregate ``'*'`` row."""
        name = _canonical_name(skill_name)
        agent = (agent_id or AGGREGATE_AGENT).strip() or AGGREGATE_AGENT
        now = _now()
        with closing(self._connect()) as db, db:
            for target in dict.fromkeys((agent, AGGREGATE_AGENT)):
                db.execute(
                    "INSERT INTO skill_usage (skill_name, agent_id, version, use_count, "
                    "last_used_at, first_seen_at) VALUES (?, ?, ?, 1, ?, ?) "
                    "ON CONFLICT(skill_name, agent_id) DO UPDATE SET "
                    "use_count=use_count+1, version=COALESCE(excluded.version, version), "
                    "last_used_at=excluded.last_used_at",
                    (name, target, version, now, now),
                )
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT * FROM skill_usage WHERE skill_name=? AND agent_id=?",
                (name, agent),
            ).fetchone()
        return dict(row) if row else {}

    def usage_stats(self, skill_name: str) -> dict[str, Any]:
        """Total + per-agent usage for one skill (aggregate row excluded from agents)."""
        name = _canonical_name(skill_name)
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT * FROM skill_usage WHERE skill_name=? ORDER BY use_count DESC, "
                "agent_id COLLATE BINARY", (name,),
            ).fetchall()
        per_agent: list[dict[str, Any]] = []
        aggregate: dict[str, Any] | None = None
        for row in rows:
            item = {
                "agent_id": row["agent_id"], "version": row["version"],
                "use_count": row["use_count"], "last_used_at": row["last_used_at"],
                "first_seen_at": row["first_seen_at"],
            }
            if row["agent_id"] == AGGREGATE_AGENT:
                aggregate = item
            else:
                per_agent.append(item)
        total = sum(item["use_count"] for item in per_agent)
        candidates = list(per_agent) + ([aggregate] if aggregate else [])
        last_used = max(
            (str(item["last_used_at"] or "") for item in candidates), default="",
        )
        return {
            "skill_name": name,
            "total_use_count": aggregate["use_count"] if aggregate else total,
            "last_used_at": last_used or None,
            "agents": per_agent,
            "distinct_agents": len(per_agent),
        }


def _registry_path() -> Path | None:
    """Locate the skill registry DB the same way ``server.py`` builds it.

    Honours an explicit override first so tests and alternate profiles never
    write to the real registry.
    """
    override = os.environ.get("ATLAS_SKILL_REGISTRY_DB", "").strip()
    if override:
        return Path(override)
    from atlas.config import get_config

    return get_config().db_path.parent / "skill-registry.db"


def record_skill_use(skill_name: str, agent_id: str = AGGREGATE_AGENT) -> None:
    """Count one real skill activation, best effort.

    Called from the ``use_skill`` tool, which is the only place a skill body is
    actually handed to the model — so the count means "loaded into a turn",
    not "appeared in the index". Never raises: telemetry must not be able to
    fail a turn, and a missing or locked registry DB just means no count.
    """
    try:
        path = _registry_path()
        if path is None or not path.exists():
            return
        from atlas.skills.registry import SkillRegistry

        AgentSkillCollections(SkillRegistry(path)).record_usage(skill_name, agent_id)
    except Exception as exc:  # noqa: BLE001 - telemetry is never load-bearing
        log.debug("skills.usage_record_failed", skill=skill_name,
                  error=str(exc), error_type=type(exc).__name__)
