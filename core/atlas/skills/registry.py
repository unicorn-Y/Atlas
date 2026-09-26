"""Persistent metadata registry for descriptive Atlas skills.

The required metadata fields are ``name``, ``version``, and ``description``.
Optional fields are ``capabilities``, ``tools``, ``requirements``, and ``examples``;
the latter fields default to empty lists (``requirements`` also accepts an object).
"""

from __future__ import annotations

import json
import re
import sqlite3
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
OPTIONAL_METADATA_FIELDS = ("capabilities", "tools", "requirements", "examples")


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
        for field in ("capabilities", "tools", "examples"):
            items = metadata.get(field, [])
            if not isinstance(items, list) or any(
                not isinstance(item, str) or not item.strip() for item in items
            ):
                raise ValueError(f"{field} must be a list of non-empty strings")
            normalized[field] = [item.strip() for item in items]
        requirements = metadata.get("requirements", [])
        if not isinstance(requirements, (list, dict)):
            raise ValueError("requirements must be a list or object")
        normalized["requirements"] = requirements
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
        normalized = self._validate(metadata)
        if not isinstance(source, str) or not source.strip():
            raise ValueError("source must be a non-empty string")
        if self._contains_secret_key(source):
            raise ValueError("Registration source must not contain credentials or secrets")
        try:
            serialized = json.dumps(normalized, sort_keys=True)
        except (TypeError, ValueError):
            raise ValueError("Skill metadata must contain JSON-compatible values") from None
        name, version = normalized["name"], normalized["version"]
        now = self._now()
        with closing(self._connect()) as db, db:
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
