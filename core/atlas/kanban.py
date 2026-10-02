# Atlas adaptation informed by NousResearch/hermes-agent tools/kanban_tools.py
# and tools/kanban_tools_schemas.py at 330d9d6df9c7bffe125ba0ae64a0abc488a7d2c3 (MIT).
"""Persistent Atlas task boards and dependency-aware task cards."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any

STATUSES = {"todo", "running", "blocked", "review", "done"}
_SCHEMA_LOCK = threading.Lock()
_MIGRATION_LOCK = threading.Lock()
_INITIALIZED_DATABASES: set[str] = set()


class KanbanStore:
    def __init__(self, database: Path) -> None:
        self.database = Path(database).resolve()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        key = str(self.database).casefold()
        with _SCHEMA_LOCK:
            if key not in _INITIALIZED_DATABASES:
                with self._connect() as db:
                    db.executescript("""
                        CREATE TABLE IF NOT EXISTS kanban_boards (
                            id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                        );
                        CREATE TABLE IF NOT EXISTS kanban_tasks (
                            id TEXT PRIMARY KEY, board_id TEXT NOT NULL REFERENCES kanban_boards(id) ON DELETE CASCADE,
                            title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', assignee TEXT NOT NULL DEFAULT '',
                            dependencies TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL DEFAULT 'todo',
                            output TEXT NOT NULL DEFAULT '', run_id TEXT NOT NULL DEFAULT '',
                            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                        );
                        CREATE INDEX IF NOT EXISTS kanban_tasks_board_status ON kanban_tasks(board_id, status);
                    """)
                _INITIALIZED_DATABASES.add(key)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.database, timeout=15)
        db.execute("PRAGMA busy_timeout=15000")
        return db

    def boards(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute("SELECT * FROM kanban_boards ORDER BY created_at")]

    def create_board(self, name: str, board_id: str | None = None) -> dict[str, Any]:
        name = name.strip()
        if not name or len(name) > 120:
            raise ValueError("board name must be 1 to 120 characters")
        identifier = board_id or re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-") or uuid.uuid4().hex
        with self._connect() as db:
            db.execute("INSERT INTO kanban_boards(id,name) VALUES (?,?)", (identifier, name))
        return {"id": identifier, "name": name}

    def tasks(self, board_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("SELECT * FROM kanban_tasks WHERE board_id=? ORDER BY created_at", (board_id,))
            return [{**dict(row), "dependencies": json.loads(row["dependencies"])} for row in rows]

    def create_task(self, board_id: str, value: dict[str, Any]) -> dict[str, Any]:
        title = value.get("title")
        if not isinstance(title, str) or not title.strip() or len(title) > 500:
            raise ValueError("title must be a non-empty string up to 500 characters")
        dependencies = value.get("dependencies", [])
        if not isinstance(dependencies, list) or any(not isinstance(dep, str) for dep in dependencies):
            raise ValueError("dependencies must be a list of task ids")
        task_id = str(value.get("id") or uuid.uuid4().hex)
        status = str(value.get("status", "todo"))
        if status not in STATUSES:
            raise ValueError("invalid task status")
        with self._connect() as db:
            if db.execute("SELECT 1 FROM kanban_boards WHERE id=?", (board_id,)).fetchone() is None:
                raise KeyError("board not found")
            for dep in dependencies:
                if db.execute("SELECT 1 FROM kanban_tasks WHERE id=? AND board_id=?", (dep, board_id)).fetchone() is None:
                    raise ValueError(f"unknown dependency: {dep}")
            db.execute("INSERT INTO kanban_tasks(id,board_id,title,description,assignee,dependencies,status,run_id) VALUES (?,?,?,?,?,?,?,?)",
                       (task_id, board_id, title.strip(), str(value.get("description", "")),
                        str(value.get("assignee", "")), json.dumps(dependencies), status,
                        str(value.get("run_id", ""))))
        return next(task for task in self.tasks(board_id) if task["id"] == task_id)
    def update_task(self, board_id: str, task_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        allowed = {"title", "description", "assignee", "dependencies", "status", "output", "run_id"}
        if set(changes) - allowed:
            raise ValueError("unsupported task fields")
        current = next((task for task in self.tasks(board_id) if task["id"] == task_id), None)
        if current is None:
            raise KeyError("task not found")
        merged = {**current, **changes}
        if merged["status"] not in STATUSES:
            raise ValueError("invalid task status")
        deps = merged.get("dependencies", [])
        if not isinstance(deps, list) or task_id in deps:
            raise ValueError("invalid or self-referential dependencies")
        all_tasks = self.tasks(board_id)
        by_id = {task["id"]: task for task in all_tasks}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> None:
            if node in visiting:
                raise ValueError("dependency cycle")
            if node in visited:
                return
            visiting.add(node)
            dependencies_for_node = deps if node == task_id else by_id.get(node, {}).get("dependencies", [])
            for dependency in dependencies_for_node:
                if dependency == task_id or dependency not in by_id:
                    raise ValueError(f"invalid dependency: {dependency}")
                visit(dependency)
            visiting.remove(node)
            visited.add(node)

        visit(task_id)
        if merged["status"] == "running" and any(
            by_id.get(dep, {}).get("status") != "done" for dep in deps
        ):
            raise ValueError("dependencies must be done before a task can run")
        with self._connect() as db:
            db.execute("UPDATE kanban_tasks SET title=?,description=?,assignee=?,dependencies=?,status=?,output=?,run_id=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND board_id=?",
                       (merged["title"], merged["description"], merged["assignee"], json.dumps(deps),
                        merged["status"], merged["output"], merged["run_id"], task_id, board_id))
        return next(task for task in self.tasks(board_id) if task["id"] == task_id)


def atlas_kanban_store() -> KanbanStore:
    """Use a dedicated SQLite file so live run/session writes cannot block board updates."""
    from atlas.config import get_config

    legacy_database = Path(get_config().db_path).resolve()
    database = legacy_database.with_name("kanban.db")
    store = KanbanStore(database)
    if database == legacy_database:
        return store
    with _MIGRATION_LOCK, sqlite3.connect(database, timeout=15) as target:
        target.execute("CREATE TABLE IF NOT EXISTS atlas_migrations (id TEXT PRIMARY KEY)")
        migrated = target.execute(
            "SELECT 1 FROM atlas_migrations WHERE id='kanban-from-atlas-db-v1'"
        ).fetchone()
        if migrated:
            return store
        if legacy_database.exists():
            with sqlite3.connect(legacy_database, timeout=15) as source:
                tables = {row[0] for row in source.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )}
                if {"kanban_boards", "kanban_tasks"} <= tables:
                    target.executemany(
                        "INSERT OR IGNORE INTO kanban_boards(id,name,created_at) VALUES(?,?,?)",
                        source.execute("SELECT id,name,created_at FROM kanban_boards"),
                    )
                    target.executemany(
                        "INSERT OR IGNORE INTO kanban_tasks "
                        "(id,board_id,title,description,assignee,dependencies,status,output,run_id,created_at,updated_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        source.execute(
                            "SELECT id,board_id,title,description,assignee,dependencies,status,output,run_id,created_at,updated_at "
                            "FROM kanban_tasks"
                        ),
                    )
        target.execute("INSERT INTO atlas_migrations(id) VALUES('kanban-from-atlas-db-v1')")
    return store
