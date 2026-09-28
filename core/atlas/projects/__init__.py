"""Project / Workspace as a first-class Atlas object.

A Project is the stable home for long-running work: its workspace/repo, current
goal and state, associated conversations, and (later) background jobs. This is
deliberately a thin store, not a project-management system.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import aiosqlite

PROJECT_STATUSES = {"active", "paused", "archived"}


@dataclass
class Project:
    project_id: str
    name: str
    workspace_path: str = ""
    repo_url: str = ""
    status: str = "active"
    current_goal: str = ""
    current_state: str = ""
    active_task_ids: list[str] = field(default_factory=list)
    memory_refs: list[str] = field(default_factory=list)
    skill_refs: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _row_to_project(row: aiosqlite.Row) -> Project:
    record = dict(row)
    for key in ("active_task_ids", "memory_refs", "skill_refs"):
        try:
            record[key] = json.loads(record.get(key) or "[]")
        except (TypeError, ValueError):
            record[key] = []
    return Project(**record)


class ProjectStore:
    """SQLite-backed project records and conversation association."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                project_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                workspace_path TEXT NOT NULL DEFAULT '',
                repo_url TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK(status IN ('active', 'paused', 'archived')),
                current_goal TEXT NOT NULL DEFAULT '',
                current_state TEXT NOT NULL DEFAULT '',
                active_task_ids TEXT NOT NULL DEFAULT '[]',
                memory_refs TEXT NOT NULL DEFAULT '[]',
                skill_refs TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS project_conversations (
                project_id TEXT NOT NULL REFERENCES projects(project_id),
                conversation_id TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (project_id, conversation_id)
            );
        """)
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    def _require_db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("ProjectStore.init() has not completed")
        return self._db

    # ----- CRUD -----

    async def create_project(
        self,
        name: str,
        workspace_path: str = "",
        repo_url: str = "",
        current_goal: str = "",
    ) -> Project:
        db = self._require_db()
        if not str(name).strip():
            raise ValueError("project name must not be empty")
        existing = await self.get_by_name(str(name))
        if existing is not None:
            raise ValueError(f"project already exists: {name}")
        project = Project(
            project_id=str(uuid.uuid4()),
            name=str(name).strip(),
            workspace_path=str(workspace_path or ""),
            repo_url=str(repo_url or ""),
            current_goal=str(current_goal or ""),
        )
        await db.execute(
            "INSERT INTO projects (project_id, name, workspace_path, repo_url, current_goal)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                project.project_id, project.name, project.workspace_path,
                project.repo_url, project.current_goal,
            ),
        )
        await db.commit()
        return await self.get(project.project_id)  # type: ignore[return-value]

    async def get(self, project_id: str) -> Project | None:
        db = self._require_db()
        cursor = await db.execute(
            "SELECT * FROM projects WHERE project_id = ?", (project_id,),
        )
        row = await cursor.fetchone()
        return _row_to_project(row) if row else None

    async def get_by_name(self, name: str) -> Project | None:
        db = self._require_db()
        cursor = await db.execute(
            "SELECT * FROM projects WHERE name = ? COLLATE NOCASE", (str(name).strip(),),
        )
        row = await cursor.fetchone()
        return _row_to_project(row) if row else None

    async def list_projects(self, status: str | None = None) -> list[Project]:
        db = self._require_db()
        if status:
            cursor = await db.execute(
                "SELECT * FROM projects WHERE status = ? ORDER BY updated_at DESC",
                (status,),
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM projects ORDER BY updated_at DESC",
            )
        return [_row_to_project(row) for row in await cursor.fetchall()]

    async def update_project(self, project_id: str, **fields: Any) -> Project | None:
        db = self._require_db()
        allowed = {
            "name", "workspace_path", "repo_url", "status", "current_goal",
            "current_state", "active_task_ids", "memory_refs", "skill_refs",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        if "status" in updates and updates["status"] not in PROJECT_STATUSES:
            raise ValueError(f"invalid project status: {updates['status']}")
        for key in ("active_task_ids", "memory_refs", "skill_refs"):
            if key in updates:
                updates[key] = json.dumps(list(updates[key] or []))
        if not updates:
            return await self.get(project_id)
        assignments = ", ".join(f"{key} = ?" for key in updates)
        await db.execute(
            f"UPDATE projects SET {assignments}, updated_at = datetime('now') "
            "WHERE project_id = ?",
            (*updates.values(), project_id),
        )
        await db.commit()
        return await self.get(project_id)

    async def archive(self, project_id: str) -> Project | None:
        return await self.update_project(project_id, status="archived")

    async def delete_project(self, project_id: str) -> bool:
        db = self._require_db()
        cursor = await db.execute(
            "DELETE FROM projects WHERE project_id = ?", (project_id,),
        )
        await db.execute(
            "DELETE FROM project_conversations WHERE project_id = ?", (project_id,),
        )
        await db.commit()
        return cursor.rowcount > 0

    # ----- Conversation association -----

    async def attach_conversation(self, project_id: str, conversation_id: str) -> bool:
        db = self._require_db()
        if await self.get(project_id) is None:
            raise ValueError(f"unknown project: {project_id}")
        await db.execute(
            "INSERT OR IGNORE INTO project_conversations (project_id, conversation_id)"
            " VALUES (?, ?)",
            (project_id, conversation_id),
        )
        await db.commit()
        return True

    async def detach_conversation(self, project_id: str, conversation_id: str) -> bool:
        db = self._require_db()
        cursor = await db.execute(
            "DELETE FROM project_conversations"
            " WHERE project_id = ? AND conversation_id = ?",
            (project_id, conversation_id),
        )
        await db.commit()
        return cursor.rowcount > 0

    async def find_by_conversation(self, conversation_id: str) -> Project | None:
        """Return the project a conversation is attached to, if any."""
        db = self._require_db()
        cursor = await db.execute(
            "SELECT p.* FROM projects p "
            "JOIN project_conversations pc ON pc.project_id = p.project_id "
            "WHERE pc.conversation_id = ? LIMIT 1",
            (conversation_id,),
        )
        row = await cursor.fetchone()
        return _row_to_project(row) if row else None

    async def list_conversations(self, project_id: str) -> list[str]:
        db = self._require_db()
        cursor = await db.execute(
            "SELECT conversation_id FROM project_conversations"
            " WHERE project_id = ? ORDER BY created_at ASC",
            (project_id,),
        )
        return [str(row["conversation_id"]) for row in await cursor.fetchall()]
