"""Persistent metadata registry for descriptive Atlas skills.

The required metadata fields are ``name``, ``version``, and ``description``.
Optional fields are ``capabilities``, ``tools``, ``requirements``, ``examples``,
``aliases``, ``tags``, ``category``, ``keywords``, and ``use_cases``;
the latter fields default to empty lists (``requirements`` also accepts an object).
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_NAME_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_VERSION_RE = re.compile(
    r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?\Z"
)
_SECRET_KEY_PARTS = ("api_key", "apikey", "token", "password", "secret", "credential")
_SECRET_VALUE_RE = re.compile(
    r"(?i)(?:api[_ -]?key|access[_ -]?token|password|passwd|secret|credential)"
    r"\s*[:=]\s*\S+|\bBearer\s+\S+|\bsk-[A-Za-z0-9_-]{12,}"
)
REQUIRED_METADATA_FIELDS = ("name", "version", "description")
OPTIONAL_METADATA_FIELDS = (
    "capabilities", "tools", "requirements", "examples", "aliases", "tags",
    "category", "keywords", "use_cases",
)


class SkillRegistry:
    """Store versioned skill descriptions; this registry grants no execution rights."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db, db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS skill_registry (
                    name TEXT NOT NULL,
                    version TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    source TEXT NOT NULL,
                    registered_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    validation_status TEXT NOT NULL,
                    status TEXT NOT NULL,
                    PRIMARY KEY (name, version)
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS skill_discovery_catalog (
                    name TEXT PRIMARY KEY,
                    version TEXT NOT NULL,
                    digest TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('active','retired')),
                    updated_at TEXT NOT NULL
                )
            """)
            db.executescript("""
                CREATE TABLE IF NOT EXISTS skill_lifecycle_history (
                    event_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    action TEXT NOT NULL,
                    skill_version TEXT,
                    previous_version TEXT,
                    previous_hash TEXT,
                    resulting_version TEXT,
                    resulting_hash TEXT,
                    source TEXT,
                    provider TEXT,
                    trust_before TEXT,
                    trust_after TEXT,
                    pin_before TEXT,
                    pin_after TEXT,
                    approval_event_id TEXT,
                    actor TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    result TEXT NOT NULL,
                    error_code TEXT,
                    details TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS skill_lifecycle_history_no_update
                BEFORE UPDATE ON skill_lifecycle_history BEGIN
                    SELECT RAISE(ABORT, 'lifecycle history is append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS skill_lifecycle_history_no_delete
                BEFORE DELETE ON skill_lifecycle_history BEGIN
                    SELECT RAISE(ABORT, 'lifecycle history is append-only');
                END;
                CREATE TABLE IF NOT EXISTS skill_lifecycle_approvals (
                    approval_event_id TEXT PRIMARY KEY,
                    token_hash TEXT NOT NULL,
                    action TEXT NOT NULL,
                    name TEXT NOT NULL,
                    version TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    current_hash TEXT,
                    acquisition_id TEXT,
                    target_trust_state TEXT,
                    target_pin_policy TEXT,
                    rollback_event_id TEXT,
                    rollback_snapshot_hash TEXT,
                    decision_id TEXT,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    consumed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS skill_lifecycle_decisions (
                    decision_id TEXT PRIMARY KEY,
                    action TEXT NOT NULL,
                    name TEXT NOT NULL,
                    version TEXT NOT NULL,
                    current_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    acquisition_id TEXT,
                    target_trust_state TEXT,
                    target_pin_policy TEXT,
                    rollback_event_id TEXT,
                    rollback_snapshot_hash TEXT,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    consumed_at TEXT
                );
            """)
            approval_columns = {
                row["name"] for row in db.execute(
                    "PRAGMA table_info(skill_lifecycle_approvals)"
                ).fetchall()
            }
            if "acquisition_id" not in approval_columns:
                db.execute("ALTER TABLE skill_lifecycle_approvals ADD COLUMN acquisition_id TEXT")
            for column, definition in (
                ("current_hash", "TEXT"), ("target_trust_state", "TEXT"),
                ("target_pin_policy", "TEXT"), ("rollback_event_id", "TEXT"),
                ("rollback_snapshot_hash", "TEXT"), ("decision_id", "TEXT"),
            ):
                if column not in approval_columns:
                    db.execute(
                        f"ALTER TABLE skill_lifecycle_approvals ADD COLUMN {column} {definition}"
                    )
            rows = db.execute(
                "SELECT name,version,metadata,status FROM skill_registry"
            ).fetchall()
            for row in rows:
                metadata = json.loads(row["metadata"])
                provenance = metadata.get("provenance") or {}
                if "lifecycle" in metadata or not provenance.get("installed_path"):
                    continue
                lifecycle = {
                    "state": "active" if row["status"] == "active" else "disabled",
                    "trust_state": "unreviewed", "pin_policy": "unpinned",
                    "pinned_version": None, "pinned_hash": None,
                    "content_hash": provenance.get("computed_sha256"),
                }
                metadata["lifecycle"] = lifecycle
                timestamp = self._now()
                event = {
                    "event_id": str(uuid.uuid4()), "name": row["name"],
                    "timestamp": timestamp, "action": "lifecycle_initialized",
                    "skill_version": row["version"], "previous_version": None,
                    "previous_hash": None, "resulting_version": row["version"],
                    "resulting_hash": lifecycle["content_hash"],
                    "source": provenance.get("source_url"),
                    "provider": provenance.get("provider"), "trust_before": None,
                    "trust_after": "unreviewed", "pin_before": None,
                    "pin_after": "unpinned", "approval_event_id": None,
                    "actor": "system", "reason": "initialize lifecycle state for installed skill",
                    "result": "success", "error_code": None,
                    "details": {"migration": "P15D"},
                }
                db.execute(
                    "UPDATE skill_registry SET metadata=?,updated_at=? WHERE name=? AND version=?",
                    (json.dumps(metadata, sort_keys=True), timestamp, row["name"], row["version"]),
                )
                db.execute(
                    "INSERT INTO skill_lifecycle_history "
                    "(event_id,name,timestamp,action,skill_version,previous_version,previous_hash,"
                    "resulting_version,resulting_hash,source,provider,trust_before,trust_after,"
                    "pin_before,pin_after,approval_event_id,actor,reason,result,"
                    "error_code,details) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (event["event_id"], event["name"], timestamp, event["action"],
                     event["skill_version"], None, None, event["resulting_version"],
                     event["resulting_hash"], event["source"], event["provider"], None,
                     "unreviewed", None, "unpinned", None, "system", event["reason"],
                     "success", None, json.dumps(event["details"], sort_keys=True)),
                )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _contains_secret_key(value: Any) -> bool:
        if isinstance(value, dict):
            return any(
                any(part in str(key).casefold() for part in _SECRET_KEY_PARTS)
                or SkillRegistry._contains_secret_key(item)
                for key, item in value.items()
            )
        if isinstance(value, (list, tuple)):
            return any(SkillRegistry._contains_secret_key(item) for item in value)
        if isinstance(value, str):
            return _SECRET_VALUE_RE.search(value) is not None
        return False

    @classmethod
    def _validate(cls, metadata: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(metadata, dict):
            raise ValueError("Skill metadata must be an object")
        if cls._contains_secret_key(metadata):
            raise ValueError("Skill metadata must not contain credentials or secrets")
        name, version, description = (metadata.get(field) for field in REQUIRED_METADATA_FIELDS)
        if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
            raise ValueError("name must be a non-empty kebab-case string")
        if not isinstance(version, str) or not _VERSION_RE.fullmatch(version):
            raise ValueError("version must use MAJOR.MINOR.PATCH semantic version format")
        if not isinstance(description, str) or not description.strip():
            raise ValueError("description must be a non-empty string")

        normalized = {
            "name": name,
            "version": version,
            "description": description.strip(),
        }
        list_fields = (
            "capabilities", "tools", "examples", "aliases", "tags", "keywords", "use_cases",
        )
        for field in list_fields:
            items = metadata.get(field, [])
            if not isinstance(items, list) or any(
                not isinstance(item, str) or not item.strip() for item in items
            ):
                raise ValueError(f"{field} must be a list of non-empty strings")
            normalized[field] = [item.strip() for item in items]
        category = metadata.get("category", "")
        if not isinstance(category, str):
            raise ValueError("category must be a string")
        normalized["category"] = category.strip()
        requirements = metadata.get("requirements", [])
        if not isinstance(requirements, (list, dict)):
            raise ValueError("requirements must be a list or object")
        normalized["requirements"] = requirements
        provenance = metadata.get("provenance")
        if provenance is not None:
            if not isinstance(provenance, dict):
                raise ValueError("provenance must be an object")
            try:
                json.dumps(provenance, sort_keys=True)
            except (TypeError, ValueError):
                raise ValueError("provenance must contain JSON-compatible values") from None
            normalized["provenance"] = provenance
        lifecycle = metadata.get("lifecycle")
        if lifecycle is not None:
            if not isinstance(lifecycle, dict):
                raise ValueError("lifecycle must be an object")
            allowed = {
                "state", "trust_state", "pin_policy", "pinned_version", "pinned_hash",
                "content_hash",
            }
            clean = {key: value for key, value in lifecycle.items() if key in allowed}
            if clean.get("state", "active") not in {
                "active", "disabled", "update-available", "superseded", "removed",
                "rollback-available", "quarantined",
            }:
                raise ValueError("invalid lifecycle state")
            if clean.get("trust_state", "unreviewed") not in {
                "unreviewed", "trusted", "revoked", "blocked",
            }:
                raise ValueError("invalid lifecycle trust state")
            if clean.get("pin_policy", "unpinned") not in {"unpinned", "exact", "hash"}:
                raise ValueError("invalid lifecycle pin policy")
            normalized["lifecycle"] = clean
        return normalized

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            **json.loads(row["metadata"]),
            "source": row["source"],
            "registered_at": row["registered_at"],
            "updated_at": row["updated_at"],
            "validation_status": row["validation_status"],
            "status": row["status"],
        }

    def register(self, metadata: dict[str, Any], *, source: str = "api") -> dict[str, Any]:
        """Validate and upsert a skill identity, retaining its original registration time."""
        if "lifecycle" in metadata:
            raise ValueError("lifecycle state may only change through audited lifecycle actions")
        normalized = self._validate(metadata)
        if not isinstance(source, str) or not source.strip():
            raise ValueError("source must be a non-empty string")
        if self._contains_secret_key(source):
            raise ValueError("Registration source must not contain credentials or secrets")
        name, version = normalized["name"], normalized["version"]
        now = self._now()
        with closing(self._connect()) as db, db:
            existing = db.execute(
                "SELECT metadata FROM skill_registry WHERE name=? AND version=?",
                (name, version),
            ).fetchone()
            if existing:
                prior = json.loads(existing["metadata"])
                if isinstance(prior.get("lifecycle"), dict):
                    normalized["lifecycle"] = prior["lifecycle"]
                prior_provenance = prior.get("provenance")
                if isinstance(prior_provenance, dict) and prior_provenance.get("installed_path"):
                    normalized["provenance"] = prior_provenance
            try:
                serialized = json.dumps(normalized, sort_keys=True)
            except (TypeError, ValueError):
                raise ValueError("Skill metadata must contain JSON-compatible values") from None
            db.execute("""
                INSERT INTO skill_registry
                    (name, version, metadata, source, registered_at, updated_at,
                     validation_status, status)
                VALUES (?, ?, ?, ?, ?, ?, 'valid', 'active')
                ON CONFLICT(name, version) DO UPDATE SET
                    metadata=excluded.metadata,
                    source=excluded.source,
                    updated_at=excluded.updated_at,
                    validation_status='valid',
                    status='active'
            """, (name, version, serialized, source.strip(), now, now))
            row = db.execute(
                "SELECT * FROM skill_registry WHERE name=? AND version=?", (name, version),
            ).fetchone()
        return self._row_to_dict(row)

    def get(self, name: str, version: str) -> dict[str, Any] | None:
        with closing(self._connect()) as db, db:
            row = db.execute(
                "SELECT * FROM skill_registry WHERE name=? AND version=?", (name, version),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def list(self, *, status: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM skill_registry"
        values: tuple[str, ...] = ()
        if status is not None:
            query += " WHERE status=?"
            values = (status,)
        query += " ORDER BY name COLLATE BINARY, version COLLATE BINARY"
        with closing(self._connect()) as db, db:
            rows = db.execute(query, values).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def reconcile_discovery_catalog(self, skills: list[Any]) -> dict[str, list[str]]:
        """Persist discovered skill digests and retire entries absent from a scan.

        Only catalog metadata and SHA-256 digests are stored; skill bodies remain
        at their source paths. A changed file digest updates the active catalog
        row even when its declared version did not change.
        """
        discovered: dict[str, dict[str, str]] = {}
        for skill in skills:
            def value(key: str, default: str = "") -> str:
                if isinstance(skill, dict):
                    item = skill.get(key, default)
                else:
                    item = getattr(skill, key, default)
                return str(item or default)

            name, version, path = value("name"), value("version", "0.0.0"), value("path")
            if not _NAME_RE.fullmatch(name) or not version or not path:
                continue
            try:
                digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
            except OSError:
                continue
            if name in discovered:
                raise ValueError(f"duplicate discovered skill name: {name}")
            metadata = {
                key: value(key) for key in ("name", "description", "category", "source")
            }
            discovered[name] = {
                "version": version, "digest": digest,
                "metadata": json.dumps(metadata, ensure_ascii=False, sort_keys=True),
            }

        result = {"added": [], "updated": [], "retired": [], "unchanged": []}
        now = self._now()
        with closing(self._connect()) as db, db:
            existing = {
                row["name"]: row for row in db.execute(
                    "SELECT name,version,digest,metadata,status FROM skill_discovery_catalog"
                ).fetchall()
            }
            for name, current in sorted(discovered.items()):
                prior = existing.get(name)
                if prior is None:
                    change = "added"
                elif (prior["version"], prior["digest"], prior["metadata"], prior["status"]) == (
                    current["version"], current["digest"], current["metadata"], "active",
                ):
                    result["unchanged"].append(name)
                    continue
                else:
                    change = "updated"
                db.execute("""
                    INSERT INTO skill_discovery_catalog
                        (name,version,digest,metadata,status,updated_at)
                    VALUES (?,?,?,?, 'active', ?)
                    ON CONFLICT(name) DO UPDATE SET
                        version=excluded.version,digest=excluded.digest,
                        metadata=excluded.metadata,status='active',updated_at=excluded.updated_at
                """, (name, current["version"], current["digest"], current["metadata"], now))
                result[change].append(name)

            for name, prior in existing.items():
                if name not in discovered and prior["status"] == "active":
                    db.execute(
                        "UPDATE skill_discovery_catalog SET status='retired',updated_at=? WHERE name=?",
                        (now, name),
                    )
                    result["retired"].append(name)
        for names in result.values():
            names.sort()
        return result

    def discovery_catalog(self, *, include_retired: bool = True) -> list[dict[str, Any]]:
        """Read the durable discovered-skill catalog without loading bodies."""
        query = "SELECT name,version,digest,metadata,status,updated_at FROM skill_discovery_catalog"
        if not include_retired:
            query += " WHERE status='active'"
        query += " ORDER BY name COLLATE BINARY"
        with closing(self._connect()) as db, db:
            rows = db.execute(query).fetchall()
        return [
            {**json.loads(row["metadata"]), "version": row["version"],
             "digest": row["digest"], "status": row["status"], "updated_at": row["updated_at"]}
            for row in rows
        ]

    def search(self, query: str) -> list[dict[str, Any]]:
        term = query.strip().casefold()
        if not term:
            return []
        matches = []
        for skill in self.list(status="active"):
            searchable = [skill["name"], skill["description"], *skill["capabilities"],
                          *skill["tools"]]
            if any(term in value.casefold() for value in searchable):
                matches.append(skill)
        return matches

    def status(self, name: str, version: str) -> str | None:
        skill = self.get(name, version)
        return skill["status"] if skill else None

    def disable(self, name: str, version: str) -> dict[str, Any] | None:
        with closing(self._connect()) as db, db:
            db.execute("""
                UPDATE skill_registry SET status='disabled', updated_at=?
                WHERE name=? AND version=?
            """, (self._now(), name, version))
        return self.get(name, version)

    def remove(self, name: str, version: str) -> bool:
        with closing(self._connect()) as db, db:
            cursor = db.execute(
                "DELETE FROM skill_registry WHERE name=? AND version=?", (name, version),
            )
            return cursor.rowcount > 0

    def lifecycle_history(self, name: str, *, limit: int = 100) -> list[dict[str, Any]]:
        with closing(self._connect()) as db, db:
            rows = db.execute(
                "SELECT * FROM skill_lifecycle_history WHERE name=? "
                "ORDER BY timestamp DESC, event_id DESC LIMIT ?", (name, limit),
            ).fetchall()
        return [{**dict(row), "details": json.loads(row["details"])} for row in rows]

    def record_lifecycle_event(
        self, event: dict[str, Any], *, metadata: dict[str, Any] | None = None,
        version: str | None = None, status: str | None = None,
    ) -> None:
        """Atomically persist lifecycle metadata and an immutable audit event."""
        details = event.get("details", {})
        if any(self._contains_secret_key(event.get(key, "")) for key in (
            "source", "provider", "reason",
        )) or self._contains_secret_key(details):
            raise ValueError("lifecycle audit must not contain credentials or secrets")
        columns = (
            "event_id", "name", "timestamp", "action", "skill_version",
            "previous_version", "previous_hash", "resulting_version", "resulting_hash",
            "source", "provider", "trust_before", "trust_after", "pin_before", "pin_after",
            "approval_event_id", "actor", "reason", "result", "error_code",
        )
        values = tuple(event.get(key) for key in columns)
        with closing(self._connect()) as db, db:
            if metadata is not None and version is not None:
                row = db.execute(
                    "SELECT metadata,status FROM skill_registry WHERE name=? AND version=?",
                    (event["name"], version),
                ).fetchone()
                if row is None:
                    raise KeyError("lifecycle registry record not found")
                normalized = self._validate(metadata)
                db.execute(
                    "UPDATE skill_registry SET metadata=?, status=?, updated_at=? "
                    "WHERE name=? AND version=?",
                    (json.dumps(normalized, sort_keys=True), status or row["status"],
                     self._now(), event["name"], version),
                )
            db.execute(
                f"INSERT INTO skill_lifecycle_history ({','.join(columns)},details) "
                f"VALUES ({','.join('?' for _ in range(len(columns) + 1))})",
                (*values, json.dumps(details, sort_keys=True)),
            )

    def create_lifecycle_decision(self, decision: dict[str, str]) -> None:
        if self._contains_secret_key(decision.get("reason", "")):
            raise ValueError("lifecycle approval reason must not contain credentials or secrets")
        fields = (
            "decision_id", "action", "name", "version", "current_hash", "content_hash",
            "acquisition_id", "target_trust_state", "target_pin_policy", "rollback_event_id",
            "rollback_snapshot_hash", "reason", "created_at", "expires_at",
        )
        with closing(self._connect()) as db, db:
            db.execute(
                f"INSERT INTO skill_lifecycle_decisions ({','.join(fields)}) "
                f"VALUES ({','.join('?' for _ in fields)})",
                tuple(decision.get(field) for field in fields),
            )

    def issue_lifecycle_approval(
        self, approval: dict[str, str], *, decision_id: str,
    ) -> bool:
        if self._contains_secret_key(approval.get("reason", "")):
            raise ValueError("lifecycle approval reason must not contain credentials or secrets")
        with closing(self._connect()) as db, db:
            decision = db.execute(
                "SELECT * FROM skill_lifecycle_decisions WHERE decision_id=? "
                "AND consumed_at IS NULL AND expires_at>?",
                (decision_id, approval["created_at"]),
            ).fetchone()
            scope = (
                "action", "name", "version", "current_hash", "content_hash", "acquisition_id",
                "target_trust_state", "target_pin_policy", "rollback_event_id",
                "rollback_snapshot_hash", "reason",
            )
            if decision is None or any(decision[key] != approval.get(key) for key in scope):
                return False
            cursor = db.execute(
                "UPDATE skill_lifecycle_decisions SET consumed_at=? "
                "WHERE decision_id=? AND consumed_at IS NULL",
                (approval["created_at"], decision_id),
            )
            if cursor.rowcount != 1:
                return False
            db.execute(
                "INSERT INTO skill_lifecycle_approvals "
                "(approval_event_id,token_hash,action,name,version,content_hash,current_hash,"
                "acquisition_id,target_trust_state,target_pin_policy,rollback_event_id,"
                "rollback_snapshot_hash,decision_id,reason,created_at,expires_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (approval["approval_event_id"], approval["token_hash"], approval["action"],
                 approval["name"], approval["version"], approval["content_hash"],
                 approval["current_hash"], approval.get("acquisition_id"),
                 approval.get("target_trust_state"), approval.get("target_pin_policy"),
                 approval.get("rollback_event_id"), approval.get("rollback_snapshot_hash"),
                 decision_id, approval["reason"],
                 approval["created_at"], approval["expires_at"]),
            )
        return True

    def issue_lifecycle_approval_from_decision(
        self, *, decision_id: str, approval_event_id: str, token_hash: str,
        created_at: str, expires_at: str,
    ) -> dict[str, str] | None:
        with closing(self._connect()) as db, db:
            decision = db.execute(
                "SELECT * FROM skill_lifecycle_decisions WHERE decision_id=? "
                "AND consumed_at IS NULL AND expires_at>?",
                (decision_id, created_at),
            ).fetchone()
            if decision is None:
                return None
            cursor = db.execute(
                "UPDATE skill_lifecycle_decisions SET consumed_at=? "
                "WHERE decision_id=? AND consumed_at IS NULL",
                (created_at, decision_id),
            )
            if cursor.rowcount != 1:
                return None
            db.execute(
                "INSERT INTO skill_lifecycle_approvals "
                "(approval_event_id,token_hash,action,name,version,content_hash,current_hash,"
                "acquisition_id,target_trust_state,target_pin_policy,rollback_event_id,"
                "rollback_snapshot_hash,decision_id,reason,created_at,expires_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (approval_event_id, token_hash, decision["action"], decision["name"],
                 decision["version"], decision["content_hash"], decision["current_hash"],
                 decision["acquisition_id"], decision["target_trust_state"],
                 decision["target_pin_policy"], decision["rollback_event_id"],
                 decision["rollback_snapshot_hash"], decision_id, decision["reason"],
                 created_at, expires_at),
            )
        return {key: decision[key] for key in (
            "action", "name", "version", "content_hash", "current_hash", "reason",
        )}

    def commit_lifecycle_update(
        self, *, previous: dict[str, Any], resulting: dict[str, Any],
        event: dict[str, Any], old_version: str,
    ) -> None:
        old_normalized = self._validate(previous)
        new_normalized = self._validate(resulting)
        columns = (
            "event_id", "name", "timestamp", "action", "skill_version",
            "previous_version", "previous_hash", "resulting_version", "resulting_hash",
            "source", "provider", "trust_before", "trust_after", "pin_before", "pin_after",
            "approval_event_id", "actor", "reason", "result", "error_code",
        )
        if (self._contains_secret_key(event.get("details", {}))
                or any(self._contains_secret_key(event.get(key, "")) for key in (
                    "source", "provider", "reason",
                ))):
            raise ValueError("lifecycle audit must not contain credentials or secrets")
        if new_normalized["version"] == old_version:
            old_provenance = old_normalized.get("provenance") or {}
            new_provenance = new_normalized.get("provenance") or {}
            identity_fields = ("provider", "external_id", "source_url")
            if (previous.get("source") != resulting.get("source")
                    or any(old_provenance.get(key) != new_provenance.get(key)
                           for key in identity_fields)):
                raise ValueError("same-version lifecycle transition changed source identity")
        with closing(self._connect()) as db, db:
            cursor = db.execute(
                "UPDATE skill_registry SET metadata=?, status='disabled', updated_at=? "
                "WHERE name=? AND version=?",
                (json.dumps(old_normalized, sort_keys=True), self._now(),
                 previous["name"], old_version),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("current registry state changed before update commit")
            now = self._now()
            if new_normalized["version"] == old_version:
                db.execute(
                    "UPDATE skill_registry SET metadata=?,source=?,updated_at=?,"
                    "validation_status='valid',status='active' WHERE name=? AND version=?",
                    (json.dumps(new_normalized, sort_keys=True),
                     resulting.get("source", "lifecycle"),
                     now, new_normalized["name"], new_normalized["version"]),
                )
            else:
                try:
                    db.execute(
                        "INSERT INTO skill_registry "
                        "(name,version,metadata,source,registered_at,updated_at,"
                        "validation_status,status) VALUES (?,?,?,?,?,?,'valid','active')",
                        (new_normalized["name"], new_normalized["version"],
                         json.dumps(new_normalized, sort_keys=True),
                         resulting.get("source", "lifecycle"),
                         now, now),
                    )
                except sqlite3.IntegrityError as exc:
                    raise ValueError(
                        "target skill name and version already exist in Registry"
                    ) from exc
            db.execute(
                f"INSERT INTO skill_lifecycle_history ({','.join(columns)},details) "
                f"VALUES ({','.join('?' for _ in range(len(columns) + 1))})",
                (*(event.get(key) for key in columns),
                 json.dumps(event.get("details", {}), sort_keys=True)),
            )

    def commit_lifecycle_rollback(
        self, *, current_version: str, current: dict[str, Any],
        restored_version: str, restored: dict[str, Any], event: dict[str, Any],
        restored_source: str | None = None,
    ) -> None:
        current_normalized = self._validate(current)
        restored_normalized = self._validate(restored)
        columns = (
            "event_id", "name", "timestamp", "action", "skill_version",
            "previous_version", "previous_hash", "resulting_version", "resulting_hash",
            "source", "provider", "trust_before", "trust_after", "pin_before", "pin_after",
            "approval_event_id", "actor", "reason", "result", "error_code",
        )
        with closing(self._connect()) as db, db:
            now = self._now()
            cursor = db.execute(
                "UPDATE skill_registry SET metadata=?,status='disabled',updated_at=? "
                "WHERE name=? AND version=?",
                (json.dumps(current_normalized, sort_keys=True), now,
                 event["name"], current_version),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("current registry state changed before rollback commit")
            if restored_version == current_version:
                cursor = db.execute(
                    "UPDATE skill_registry SET metadata=?,source=?,status='active',updated_at=? "
                    "WHERE name=? AND version=?",
                    (json.dumps(restored_normalized, sort_keys=True),
                     restored_source or "lifecycle", now,
                     event["name"], restored_version),
                )
            else:
                cursor = db.execute(
                    "UPDATE skill_registry SET metadata=?,source=?,status='active',updated_at=? "
                    "WHERE name=? AND version=?",
                    (json.dumps(restored_normalized, sort_keys=True),
                     restored_source or "lifecycle", now,
                     event["name"], restored_version),
                )
            if cursor.rowcount != 1:
                raise RuntimeError("rollback target registry record is missing")
            db.execute(
                f"INSERT INTO skill_lifecycle_history ({','.join(columns)},details) "
                f"VALUES ({','.join('?' for _ in range(len(columns) + 1))})",
                (*(event.get(key) for key in columns),
                 json.dumps(event.get("details", {}), sort_keys=True)),
            )

    def consume_lifecycle_approval(
        self, *, token: str, action: str, name: str, version: str, content_hash: str,
        current_hash: str, acquisition_id: str | None = None,
        target_trust_state: str | None = None, target_pin_policy: str | None = None,
        rollback_event_id: str | None = None, rollback_snapshot_hash: str | None = None,
    ) -> dict[str, str] | None:
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = self._now()
        with closing(self._connect()) as db, db:
            row = db.execute(
                "SELECT * FROM skill_lifecycle_approvals WHERE token_hash=? AND action=? "
                "AND name=? AND version=? AND content_hash=? AND consumed_at IS NULL "
                "AND current_hash=? AND acquisition_id IS ? AND target_trust_state IS ? "
                "AND target_pin_policy IS ? AND rollback_event_id IS ? "
                "AND rollback_snapshot_hash IS ? AND expires_at>?",
                (token_hash, action, name, version, content_hash, current_hash, acquisition_id,
                 target_trust_state, target_pin_policy, rollback_event_id,
                 rollback_snapshot_hash, now),
            ).fetchone()
            if row is None:
                return None
            cursor = db.execute(
                "UPDATE skill_lifecycle_approvals SET consumed_at=? "
                "WHERE approval_event_id=? AND consumed_at IS NULL",
                (now, row["approval_event_id"]),
            )
            if cursor.rowcount != 1:
                return None
        return {"approval_event_id": row["approval_event_id"], "reason": row["reason"]}
