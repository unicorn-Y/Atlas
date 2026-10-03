"""W7 Skill Workshop — governed skill-change proposals (``atlas.skills.proposals``).

Concept port of OpenClaw's skill-workshop proposal flow (see
``docs/research/2026-10-03-persistent-atlas/lanes/r8-skills-workshop.md``):

- An agent (or operator) drafts a **proposal**: a structured diff
  (``{"writes": {path: content}, "deletes": [path]}``) against a target skill,
  with ``origin`` provenance (``{agent_id, session_key, run_id, message_id}``),
  ``goal``/``evidence`` context and ``source_kind="agent_learned"``.
- ``approve`` re-validates the optimistic lock (``base_revision`` — the content
  hash of the live skill at draft time), applies the diff through the ONE
  Registry save path (``SkillMarket.register_local`` with
  ``origin_kind="agent_learned"``), captures a rollback snapshot first and
  appends to an append-only event ledger. A drifted base marks the proposal
  ``stale`` and refuses to apply (HTTP 409 semantics).
- ``rollback`` restores the snapshot captured at apply time (previous files +
  previous origin kind); rolling back a ``create`` restores absence.

Storage follows the Registry's own form — **SQLite, same database file**:
tables live next to ``skill_registry`` inside ``registry.path`` (single-store
red line; no second registry, no JSON sidecar). ``registry.py`` itself is not
modified: this module creates its tables with ``CREATE TABLE IF NOT EXISTS``.

Single-process assumption: the base-revision check and the file write are two
steps; concurrent approval of the same proposal is guarded by the status
transition, not by a held write lock.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from atlas.skills.acquisition import NAME_RE, _parse_manifest, payload_sha256

log = structlog.get_logger()

#: Proposal lifecycle states (frozen by the lane contract).
PROPOSAL_STATUSES = ("pending", "applied", "rejected", "stale")
#: Allowed explicit transitions (rollback keeps ``applied`` + ``rolled_back_at``).
_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"applied", "rejected", "stale"},
    "stale": {"rejected"},
    "applied": set(),
    "rejected": set(),
}
#: Event ledger vocabulary (append-only, CHECK-constrained).
EVENT_TYPES = ("created", "revised", "applied", "rejected", "stale", "rolled_back")

#: origin_kind written on apply; whitelisted by the market (ORIGIN_KINDS).
APPLY_ORIGIN_KIND = "agent_learned"
#: Prior rows under these origin kinds (or at the same install path) are
#: dropped before a proposal write, mirroring save_local_skill_bundle's rule.
MANAGED_DROP_KINDS = {"agent_learned"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS skill_proposals (
    proposal_id TEXT PRIMARY KEY,
    skill_name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('create', 'update')),
    status TEXT NOT NULL CHECK (status IN ('pending', 'applied', 'rejected', 'stale')),
    base_revision TEXT NOT NULL,
    revision_hash TEXT NOT NULL,
    proposed_diff TEXT NOT NULL,
    origin_json TEXT,
    source_kind TEXT NOT NULL DEFAULT 'agent_learned',
    goal TEXT NOT NULL DEFAULT '',
    evidence TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT 'agent',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    decided_at TEXT,
    reviewer_note TEXT,
    rolled_back_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_skill_proposals_skill
    ON skill_proposals(skill_name, status);
CREATE TABLE IF NOT EXISTS skill_proposal_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    proposal_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    event TEXT NOT NULL CHECK (event IN (
        'created', 'revised', 'applied', 'rejected', 'stale', 'rolled_back')),
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_skill_proposal_events_proposal
    ON skill_proposal_events(proposal_id, sequence);
CREATE TRIGGER IF NOT EXISTS skill_proposal_events_no_update
BEFORE UPDATE ON skill_proposal_events BEGIN
    SELECT RAISE(ABORT, 'proposal events are append-only');
END;
CREATE TRIGGER IF NOT EXISTS skill_proposal_events_no_delete
BEFORE DELETE ON skill_proposal_events BEGIN
    SELECT RAISE(ABORT, 'proposal events are append-only');
END;
CREATE TABLE IF NOT EXISTS skill_proposal_rollbacks (
    proposal_id TEXT PRIMARY KEY,
    written_at TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    version TEXT,
    action TEXT NOT NULL CHECK (action IN ('create', 'update')),
    previous_files TEXT NOT NULL,
    previous_content_hash TEXT,
    previous_origin_kind TEXT,
    previous_source TEXT,
    restore_path TEXT
);
"""


class ProposalError(RuntimeError):
    """Proposal flow failure carrying an HTTP status for the router."""

    def __init__(
        self, message: str, *, code: str = "proposal_error",
        status_code: int = 422, details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}


class ProposalNotFound(ProposalError):
    def __init__(self, proposal_id: str) -> None:
        super().__init__(
            f"未找到技能提案：{proposal_id}", code="proposal_not_found", status_code=404,
        )


class ProposalConflict(ProposalError):
    """Optimistic-lock or state-machine conflict (HTTP 409)."""

    def __init__(self, message: str, *, code: str = "proposal_conflict",
                 details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code=code, status_code=409, details=details)


class ProposalStale(ProposalConflict):
    """base_revision no longer matches the live skill; the proposal went stale."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="proposal_stale", details=details)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _canonical_name(name: str) -> str:
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise ProposalError(
            f"技能名「{name}」不符合 Atlas 规范（只能用小写字母、数字和连字符）。",
            code="invalid_name",
        )
    return name


def files_revision(files: dict[str, str]) -> str:
    """Content revision hash over a whole files mapping (sorted, canonical JSON)."""
    return hashlib.sha256(
        json.dumps({str(k): str(v) for k, v in sorted(files.items())},
                   ensure_ascii=False, sort_keys=True).encode("utf-8"),
    ).hexdigest()


#: Revision of an absent skill (create proposals lock against this).
EMPTY_REVISION = files_revision({})


def diff_revision(skill_name: str, kind: str, diff: dict[str, Any]) -> str:
    """Draft revision hash (OpenClaw ``hashSkillProposalRevision`` analog).

    Covers the target identity plus every write/delete so any draft edit —
    and only a draft edit — changes the hash used as the optimistic lock.
    """
    return hashlib.sha256(
        json.dumps({
            "skill_name": skill_name,
            "kind": kind,
            "writes": {str(k): str(v) for k, v in sorted(diff.get("writes", {}).items())},
            "deletes": sorted(str(p) for p in diff.get("deletes", [])),
        }, ensure_ascii=False, sort_keys=True).encode("utf-8"),
    ).hexdigest()


def normalize_diff(
    *,
    files: dict[str, str] | None = None,
    writes: dict[str, str] | None = None,
    deletes: list[str] | None = None,
) -> dict[str, Any]:
    """Normalize ``files`` shorthand and/or explicit writes/deletes into one diff."""
    merged_writes: dict[str, str] = {}
    for source in (files, writes):
        if source is None:
            continue
        if not isinstance(source, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in source.items()
        ):
            raise ProposalError(
                "files/writes 必须是 {相对路径: 文本内容} 的对象。", code="invalid_diff")
        merged_writes.update(source)
    clean_deletes: list[str] = []
    if deletes is not None:
        if not isinstance(deletes, list) or not all(isinstance(p, str) for p in deletes):
            raise ProposalError("deletes 必须是相对路径字符串列表。", code="invalid_diff")
        clean_deletes = list(dict.fromkeys(deletes))
    overlap = sorted(set(merged_writes) & set(clean_deletes))
    if overlap:
        raise ProposalError(
            f"同一路径不能同时出现在 writes 和 deletes：{overlap}", code="invalid_diff")
    if not merged_writes and not clean_deletes:
        raise ProposalError("提案 diff 不能为空。", code="invalid_diff")
    return {"writes": merged_writes, "deletes": clean_deletes}


def merge_diff(base: dict[str, str], diff: dict[str, Any]) -> dict[str, str]:
    """Overlay a diff onto base files: writes replace, deletes remove."""
    merged = dict(base)
    for path, content in (diff.get("writes") or {}).items():
        merged[path] = content
    for path in diff.get("deletes") or []:
        merged.pop(path, None)
    return merged


class SkillProposalStore:
    """Proposal store + approval flow over the ONE Registry SQLite database."""

    def __init__(
        self, registry: Any, *, market: Any | None = None, collections: Any | None = None,
    ) -> None:
        self.registry = registry
        self.market = market
        self.collections = collections
        with closing(self._connect()) as db, db:
            db.executescript(SCHEMA)

    # ------------------------------------------------------------------
    # Storage plumbing (same file as the Registry — single store)
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.registry.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "proposal_id": row["proposal_id"],
            "skill_name": row["skill_name"],
            "kind": row["kind"],
            "status": row["status"],
            "base_revision": row["base_revision"],
            "revision_hash": row["revision_hash"],
            "proposed_diff": json.loads(row["proposed_diff"]),
            "origin": json.loads(row["origin_json"]) if row["origin_json"] else {},
            "source_kind": row["source_kind"],
            "goal": row["goal"],
            "evidence": row["evidence"],
            "created_by": row["created_by"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "decided_at": row["decided_at"],
            "reviewer_note": row["reviewer_note"],
            "rolled_back_at": row["rolled_back_at"],
        }

    # ------------------------------------------------------------------
    # Live skill state (read through the Registry, files from install path)
    # ------------------------------------------------------------------

    def _market(self) -> Any:
        if self.market is None:
            raise ProposalError(
                "提案存储未接线技能市场（market），无法读写技能文件。",
                code="market_unwired", status_code=503,
            )
        return self.market

    def _live_state(self, skill_name: str) -> tuple[dict[str, str], dict[str, Any] | None]:
        """(files, record) of the live skill — files read from provenance path."""
        rows = [item for item in self.registry.list() if item["name"] == skill_name]
        if not rows:
            return {}, None
        rows.sort(key=lambda item: (item["status"] != "active", item.get("updated_at", "")))
        record = rows[-1]
        installed_path = (record.get("provenance") or {}).get("installed_path")
        files: dict[str, str] = {}
        if installed_path:
            root = Path(installed_path)
            if root.is_dir():
                for item in sorted(root.rglob("*")):
                    if item.is_file() and not item.is_symlink():
                        try:
                            files[item.relative_to(root).as_posix()] = item.read_text(
                                encoding="utf-8")
                        except (OSError, UnicodeError):
                            continue
        return files, record

    def _destination(self, skill_name: str) -> Path:
        market = self._market()
        return market._destination("user", skill_name)

    # ------------------------------------------------------------------
    # Registry save path (market primitives; no second registry)
    # ------------------------------------------------------------------

    def _write_registered(
        self, skill_name: str, files: dict[str, str], *, origin_kind: str,
        source: str = "agent", reason: str,
    ) -> dict[str, Any]:
        """Stage payload to the user-scope dir and register via ``register_local``."""
        market = self._market()
        name = _canonical_name(skill_name)
        try:
            manifest, _dependencies = _parse_manifest(files["SKILL.md"], name)
        except (KeyError, ValueError) as exc:
            raise ProposalError(
                f"技能「{name}」合并后的 SKILL.md 不符合 Atlas 规范：{exc}",
                code="invalid_manifest",
            ) from exc
        version = manifest["version"]
        digest = payload_sha256(files)
        dest = self._destination(name)
        resolved = {str(dest), str(dest.resolve())}
        for row in self.registry.list():
            if row["name"] != name:
                continue
            provenance = row.get("provenance") or {}
            managed = provenance.get("origin_kind") in MANAGED_DROP_KINDS or (
                provenance.get("installed_path") in resolved
            )
            if managed and (row["version"] != version
                            or provenance.get("computed_sha256") != digest):
                self.registry.remove(name, row["version"])
        market._write_payload(dest, files)
        market.register_local(
            name, path=dest, origin_kind=origin_kind, source=source, reason=reason)
        market._rescan()
        return {"name": name, "version": version, "path": str(dest), "hash": digest}

    def _remove_registered(self, skill_name: str) -> dict[str, Any]:
        """Restore absence: drop managed rows + the managed payload directory."""
        market = self._market()
        name = _canonical_name(skill_name)
        dest = self._destination(name)
        resolved = {str(dest), str(dest.resolve())}
        removed: list[str] = []
        for row in self.registry.list():
            if row["name"] != name:
                continue
            provenance = row.get("provenance") or {}
            if provenance.get("origin_kind") in MANAGED_DROP_KINDS or (
                provenance.get("installed_path") in resolved
            ):
                self.registry.remove(name, row["version"])
                removed.append(row["version"])
        if dest.is_dir():
            try:
                inside = dest.resolve().is_relative_to(
                    Path(market.user_skills_dir).resolve())
            except OSError:
                inside = False
            if inside:
                shutil.rmtree(dest, ignore_errors=True)
        market._rescan()
        return {"removed_versions": removed, "path": str(dest)}

    # ------------------------------------------------------------------
    # Event ledger (append-only, trigger-enforced)
    # ------------------------------------------------------------------

    def _record_event(
        self, db: sqlite3.Connection, proposal_id: str, event: str, payload: dict[str, Any],
    ) -> None:
        db.execute(
            "INSERT INTO skill_proposal_events (event_id, proposal_id, ts, event, payload) "
            "VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), proposal_id, _now(), event,
             json.dumps(payload, ensure_ascii=False, sort_keys=True)),
        )

    def events(self, proposal_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT * FROM skill_proposal_events WHERE proposal_id=? "
                "ORDER BY sequence", (proposal_id,),
            ).fetchall()
        return [
            {**dict(row), "payload": json.loads(row["payload"])} for row in rows
        ]

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get(self, proposal_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT * FROM skill_proposals WHERE proposal_id=?", (proposal_id,),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def list(
        self, *, status: str | None = None, skill_name: str | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM skill_proposals"
        clauses: list[str] = []
        values: list[str] = []
        if status is not None:
            clauses.append("status=?")
            values.append(status)
        if skill_name is not None:
            clauses.append("skill_name=?")
            values.append(skill_name)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC, proposal_id DESC"
        with closing(self._connect()) as db:
            rows = db.execute(query, tuple(values)).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def _require(self, proposal_id: str) -> dict[str, Any]:
        record = self.get(proposal_id)
        if record is None:
            raise ProposalNotFound(proposal_id)
        return record

    # ------------------------------------------------------------------
    # Create / revise
    # ------------------------------------------------------------------

    def create_proposal(
        self, skill_name: str, *,
        files: dict[str, str] | None = None,
        writes: dict[str, str] | None = None,
        deletes: list[str] | None = None,
        kind: str | None = None,
        base_revision: str | None = None,
        origin: dict[str, Any] | None = None,
        goal: str = "",
        evidence: str = "",
        created_by: str = "agent",
    ) -> dict[str, Any]:
        """Draft a proposal (``/learn`` semantics: an existing pending draft for
        the same skill is revised in place, never duplicated nor auto-applied)."""
        name = _canonical_name(skill_name)
        diff = normalize_diff(files=files, writes=writes, deletes=deletes)
        live_files, record = self._live_state(name)
        detected_kind = "update" if record is not None else "create"
        if kind is None:
            kind = detected_kind
        elif kind not in ("create", "update"):
            raise ProposalError("kind 只支持 create / update。", code="invalid_kind")
        elif kind != detected_kind:
            raise ProposalError(
                f"kind={kind} 与当前状态不符（技能{'已' if detected_kind == 'update' else '未'}安装）。",
                code="kind_mismatch",
            )
        if base_revision is None:
            base_revision = files_revision(live_files)
        pending = [
            item for item in self.list(status="pending", skill_name=name)
        ]
        if pending:
            return self.revise_proposal(
                pending[0]["proposal_id"], files=files, writes=writes, deletes=deletes,
                expected_revision=None, goal=goal or None, evidence=evidence or None,
                note="superseded by a new draft for the same skill",
            )
        proposal_id = f"prop-{uuid.uuid4().hex}"
        now = _now()
        revision_hash = diff_revision(name, kind, diff)
        origin_json = json.dumps(origin or {}, ensure_ascii=False, sort_keys=True) \
            if origin else None
        with closing(self._connect()) as db, db:
            db.execute(
                "INSERT INTO skill_proposals (proposal_id, skill_name, kind, status, "
                "base_revision, revision_hash, proposed_diff, origin_json, source_kind, "
                "goal, evidence, created_by, created_at, updated_at) "
                "VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, 'agent_learned', ?, ?, ?, ?, ?)",
                (proposal_id, name, kind, base_revision, revision_hash,
                 json.dumps(diff, ensure_ascii=False, sort_keys=True), origin_json,
                 str(goal), str(evidence), str(created_by), now, now),
            )
            self._record_event(db, proposal_id, "created", {
                "skill_name": name, "kind": kind, "revision_hash": revision_hash,
                "base_revision": base_revision, "origin": origin or {},
                "created_by": created_by,
            })
        log.info("skills.proposal_created", proposal_id=proposal_id, skill=name, kind=kind)
        return self.get(proposal_id)  # type: ignore[return-value]

    def revise_proposal(
        self, proposal_id: str, *,
        files: dict[str, str] | None = None,
        writes: dict[str, str] | None = None,
        deletes: list[str] | None = None,
        expected_revision: str | None = None,
        goal: str | None = None,
        evidence: str | None = None,
        note: str = "",
    ) -> dict[str, Any]:
        """Replace the draft diff of a pending proposal (draft optimistic lock)."""
        record = self._require(proposal_id)
        if record["status"] != "pending":
            raise ProposalConflict(
                f"提案当前状态为 {record['status']}，只有 pending 提案可以修订。",
                details={"proposal_id": proposal_id, "status": record["status"]})
        if expected_revision is not None and expected_revision != record["revision_hash"]:
            raise ProposalConflict(
                "draft revision hash 不匹配（expected_revision），请重新读取提案后再修订。",
                code="revision_conflict",
                details={"expected": expected_revision, "current": record["revision_hash"]},
            )
        diff = normalize_diff(files=files, writes=writes, deletes=deletes)
        revision_hash = diff_revision(record["skill_name"], record["kind"], diff)
        now = _now()
        with closing(self._connect()) as db, db:
            db.execute(
                "UPDATE skill_proposals SET proposed_diff=?, revision_hash=?, "
                "goal=COALESCE(?, goal), evidence=COALESCE(?, evidence), "
                "updated_at=? WHERE proposal_id=? AND status='pending'",
                (json.dumps(diff, ensure_ascii=False, sort_keys=True), revision_hash,
                 goal, evidence, now, proposal_id),
            )
            self._record_event(db, proposal_id, "revised", {
                "revision_hash": revision_hash, "note": note,
            })
        updated = self.get(proposal_id)
        assert updated is not None
        return updated

    # ------------------------------------------------------------------
    # Decide: approve / reject / mark_stale
    # ------------------------------------------------------------------

    def approve(
        self, proposal_id: str, *, expected_revision: str | None = None,
        reviewer_note: str = "", actor: str = "user",
    ) -> dict[str, Any]:
        """Apply a pending proposal through the Registry save path.

        Re-checks ``base_revision`` against the live skill first: a drifted base
        marks the proposal ``stale`` and raises ``ProposalStale`` (409 semantics).
        Captures a rollback snapshot before the first byte is written.
        """
        record = self._require(proposal_id)
        if record["status"] != "pending":
            raise ProposalConflict(
                f"提案当前状态为 {record['status']}，只有 pending 提案可以批准。",
                details={"proposal_id": proposal_id, "status": record["status"]})
        if expected_revision is not None and expected_revision != record["revision_hash"]:
            raise ProposalConflict(
                "draft revision hash 不匹配（expected_revision），提案可能已被修订。",
                code="revision_conflict",
                details={"expected": expected_revision, "current": record["revision_hash"]},
            )
        name = record["skill_name"]
        live_files, live_record = self._live_state(name)
        if files_revision(live_files) != record["base_revision"]:
            self.mark_stale(proposal_id, reason="base_revision no longer matches the live skill",
                            actor=actor)
            raise ProposalStale(
                f"技能「{name}」在提案创建后已发生变化（base_revision 过期），提案已标记为 stale。",
                details={"proposal_id": proposal_id, "skill_name": name,
                         "base_revision": record["base_revision"]},
            )
        merged = merge_diff(live_files, record["proposed_diff"])
        previous_provenance = (live_record or {}).get("provenance") or {}
        written_at = _now()
        result = self._write_registered(
            name, merged, origin_kind=APPLY_ORIGIN_KIND,
            reason=f"skill proposal {proposal_id} approved by {actor}",
        )
        with closing(self._connect()) as db, db:
            db.execute(
                "UPDATE skill_proposals SET status='applied', decided_at=?, "
                "reviewer_note=?, updated_at=? WHERE proposal_id=? AND status='pending'",
                (written_at, reviewer_note or None, _now(), proposal_id),
            )
            db.execute(
                "INSERT INTO skill_proposal_rollbacks (proposal_id, written_at, skill_name, "
                "version, action, previous_files, previous_content_hash, "
                "previous_origin_kind, previous_source, restore_path) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (proposal_id, written_at, name,
                 (live_record or {}).get("version"), record["kind"],
                 json.dumps(live_files, ensure_ascii=False, sort_keys=True),
                 files_revision(live_files) if live_record else None,
                 previous_provenance.get("origin_kind"),
                 previous_provenance.get("provider"),
                 (previous_provenance.get("installed_path") or result["path"])),
            )
            self._record_event(db, proposal_id, "applied", {
                "actor": actor, "reviewer_note": reviewer_note,
                "version": result["version"], "content_hash": result["hash"],
                "path": result["path"], "origin_kind": APPLY_ORIGIN_KIND,
            })
        # learned 集合默认启用：应用来源 agent 的关系行（实体仍在 Registry，仅加关系）。
        origin = record.get("origin") or {}
        agent_id = str(origin.get("agent_id") or "").strip()
        if self.collections is not None and agent_id:
            try:
                self.collections.set_agent_skill(
                    agent_id, name, enabled=True, relation="learned",
                    note=f"applied via proposal {proposal_id}")
            except Exception as exc:  # pragma: no cover - relation write is best-effort
                log.warning("skills.proposal_learned_relation_failed",
                            proposal_id=proposal_id, error=str(exc))
        log.info("skills.proposal_applied", proposal_id=proposal_id, skill=name,
                 version=result["version"])
        updated = self.get(proposal_id)
        assert updated is not None
        return {**updated, "applied": result}

    def reject(
        self, proposal_id: str, *, reason: str = "", actor: str = "user",
        expected_revision: str | None = None,
    ) -> dict[str, Any]:
        """Reject a pending (or already stale) proposal; the draft is kept."""
        record = self._require(proposal_id)
        if record["status"] not in ("pending", "stale"):
            raise ProposalConflict(
                f"提案当前状态为 {record['status']}，不能拒绝。",
                details={"proposal_id": proposal_id, "status": record["status"]})
        if expected_revision is not None and expected_revision != record["revision_hash"]:
            raise ProposalConflict(
                "draft revision hash 不匹配（expected_revision）。",
                code="revision_conflict",
                details={"expected": expected_revision, "current": record["revision_hash"]},
            )
        now = _now()
        with closing(self._connect()) as db, db:
            db.execute(
                "UPDATE skill_proposals SET status='rejected', decided_at=?, "
                "reviewer_note=?, updated_at=? WHERE proposal_id=? AND status IN "
                "('pending','stale')",
                (now, reason or None, now, proposal_id),
            )
            self._record_event(db, proposal_id, "rejected", {
                "actor": actor, "reason": reason,
            })
        log.info("skills.proposal_rejected", proposal_id=proposal_id)
        updated = self.get(proposal_id)
        assert updated is not None
        return updated

    def mark_stale(
        self, proposal_id: str, *, reason: str = "", actor: str = "system",
    ) -> dict[str, Any]:
        """Flag a pending proposal stale (drift detected or manual)."""
        record = self._require(proposal_id)
        if record["status"] != "pending":
            raise ProposalConflict(
                f"提案当前状态为 {record['status']}，只有 pending 提案可以标记 stale。",
                details={"proposal_id": proposal_id, "status": record["status"]})
        now = _now()
        with closing(self._connect()) as db, db:
            db.execute(
                "UPDATE skill_proposals SET status='stale', decided_at=?, reviewer_note=?, "
                "updated_at=? WHERE proposal_id=? AND status='pending'",
                (now, reason or None, now, proposal_id),
            )
            self._record_event(db, proposal_id, "stale", {
                "actor": actor, "reason": reason,
            })
        updated = self.get(proposal_id)
        assert updated is not None
        return updated

    # ------------------------------------------------------------------
    # Rollback
    # ------------------------------------------------------------------

    def rollback(self, proposal_id: str, *, actor: str = "user") -> dict[str, Any]:
        """Restore the pre-apply snapshot (update → previous payload, create → absence)."""
        record = self._require(proposal_id)
        if record["status"] != "applied":
            raise ProposalConflict(
                f"提案当前状态为 {record['status']}，只有 applied 提案可以回滚。",
                details={"proposal_id": proposal_id, "status": record["status"]})
        if record["rolled_back_at"]:
            raise ProposalConflict(
                "该提案已经回滚过，不能重复回滚。",
                details={"proposal_id": proposal_id, "rolled_back_at": record["rolled_back_at"]},
            )
        with closing(self._connect()) as db:
            snap = db.execute(
                "SELECT * FROM skill_proposal_rollbacks WHERE proposal_id=?",
                (proposal_id,),
            ).fetchone()
        if snap is None:  # pragma: no cover - every apply writes a snapshot
            raise ProposalError("回滚快照缺失，无法恢复。", code="rollback_snapshot_missing",
                                status_code=409)
        name = snap["skill_name"]
        previous_files = json.loads(snap["previous_files"])
        if previous_files:
            result = self._write_registered(
                name, previous_files,
                origin_kind=snap["previous_origin_kind"] or APPLY_ORIGIN_KIND,
                source=snap["previous_source"] or "agent",
                reason=f"rollback of proposal {proposal_id} by {actor}",
            )
        else:
            result = self._remove_registered(name)
        now = _now()
        with closing(self._connect()) as db, db:
            db.execute(
                "UPDATE skill_proposals SET rolled_back_at=?, updated_at=? "
                "WHERE proposal_id=? AND rolled_back_at IS NULL",
                (now, now, proposal_id),
            )
            self._record_event(db, proposal_id, "rolled_back", {
                "actor": actor, "action": snap["action"],
                "restored_version": result.get("version"),
                "restored_hash": result.get("hash"),
                "removed_versions": result.get("removed_versions"),
            })
        log.info("skills.proposal_rolled_back", proposal_id=proposal_id, skill=name)
        updated = self.get(proposal_id)
        assert updated is not None
        return {**updated, "restored": result}


def default_proposal_store(
    registry: Any, *, market: Any | None = None, collections: Any | None = None,
) -> SkillProposalStore:
    return SkillProposalStore(registry, market=market, collections=collections)
