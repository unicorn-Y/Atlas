"""Project / Workspace as a first-class Atlas object.

A Project is the stable home for long-running work: its workspace/repo, current
goal and state, associated conversations, and (later) background jobs. This is
deliberately a thin store, not a project-management system.
"""

from __future__ import annotations

import json
import asyncio
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import aiosqlite

PROJECT_STATUSES = {"active", "paused", "archived"}
PROJECT_ICONS = {"folder", "code", "terminal", "book", "sparkles"}
_TEXT_SUFFIXES = {".txt", ".md", ".rst", ".csv", ".json", ".jsonl", ".py", ".js",
                  ".ts", ".tsx", ".jsx", ".html", ".css", ".scss", ".yaml", ".yml",
                  ".toml", ".xml", ".sql", ".sh", ".ps1", ".go", ".rs", ".java",
                  ".c", ".h", ".cpp", ".hpp", ".rb", ".php", ".swift", ".kt",
                  ".ini", ".cfg", ".log"}


@dataclass
class Project:
    project_id: str
    name: str
    workspace_path: str = ""
    repo_url: str = ""
    status: str = "active"
    color: str = ""
    icon: str = "folder"
    current_goal: str = ""
    current_state: str = ""
    active_task_ids: list[str] = field(default_factory=list)
    memory_refs: list[str] = field(default_factory=list)
    memory_scope: str = "global"
    skill_refs: list[str] = field(default_factory=list)
    default_model: str = ""
    default_preset_id: str = ""
    pinned: bool = False
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _row_to_project(row: aiosqlite.Row) -> Project:
    record = dict(row)
    record["pinned"] = bool(record.get("pinned", False))
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
                color TEXT NOT NULL DEFAULT '',
                icon TEXT NOT NULL DEFAULT 'folder',
                current_goal TEXT NOT NULL DEFAULT '',
                current_state TEXT NOT NULL DEFAULT '',
                active_task_ids TEXT NOT NULL DEFAULT '[]',
                memory_refs TEXT NOT NULL DEFAULT '[]',
                skill_refs TEXT NOT NULL DEFAULT '[]',
                memory_scope TEXT NOT NULL DEFAULT 'global',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS project_conversations (
                project_id TEXT NOT NULL REFERENCES projects(project_id),
                conversation_id TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (project_id, conversation_id)
            );
            CREATE TABLE IF NOT EXISTS project_source_settings (
                project_id TEXT PRIMARY KEY,
                instructions TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS project_sources (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                path TEXT,
                url TEXT,
                text TEXT,
                bytes INTEGER NOT NULL DEFAULT 0,
                added_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_project_sources_project
                ON project_sources(project_id, added_at);
            CREATE VIRTUAL TABLE IF NOT EXISTS project_source_fts USING fts5(
                project_id UNINDEXED, source_id UNINDEXED, path UNINDEXED, text,
                tokenize='unicode61'
            );
            CREATE TABLE IF NOT EXISTS project_memories (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL, text TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS global_project_memories (
                id TEXT PRIMARY KEY, text TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_project_memories_scope ON project_memories(project_id, created_at);
        """)
        cursor = await self._db.execute("PRAGMA table_info(projects)")
        columns = {row["name"] for row in await cursor.fetchall()}
        if "color" not in columns:
            await self._db.execute("ALTER TABLE projects ADD COLUMN color TEXT NOT NULL DEFAULT ''")
        if "icon" not in columns:
            await self._db.execute("ALTER TABLE projects ADD COLUMN icon TEXT NOT NULL DEFAULT 'folder'")
        if "default_model" not in columns:
            await self._db.execute("ALTER TABLE projects ADD COLUMN default_model TEXT NOT NULL DEFAULT ''")
        if "default_preset_id" not in columns:
            await self._db.execute("ALTER TABLE projects ADD COLUMN default_preset_id TEXT NOT NULL DEFAULT ''")
        if "pinned" not in columns:
            await self._db.execute("ALTER TABLE projects ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")
        if "memory_scope" not in columns:
            await self._db.execute("ALTER TABLE projects ADD COLUMN memory_scope TEXT NOT NULL DEFAULT 'global'")
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
        color: str = "",
        default_model: str = "",
        default_preset_id: str = "",
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
            color=str(color or ""), default_model=str(default_model or ""),
            default_preset_id=str(default_preset_id or ""),
        )
        await db.execute(
            "INSERT INTO projects (project_id, name, workspace_path, repo_url, current_goal, color, default_model, default_preset_id)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                project.project_id, project.name, project.workspace_path,
                project.repo_url, project.current_goal, project.color,
                project.default_model, project.default_preset_id,
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
                "SELECT * FROM projects WHERE status = ? ORDER BY pinned DESC, updated_at DESC",
                (status,),
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM projects ORDER BY pinned DESC, updated_at DESC",
            )
        return [_row_to_project(row) for row in await cursor.fetchall()]

    async def update_project(self, project_id: str, **fields: Any) -> Project | None:
        db = self._require_db()
        allowed = {
            "name", "workspace_path", "repo_url", "status", "current_goal",
            "current_state", "active_task_ids", "memory_refs", "skill_refs", "color", "icon",
            "default_model", "default_preset_id", "pinned", "memory_scope",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        if "name" in updates:
            name = str(updates["name"]).strip()
            if not name:
                raise ValueError("project name must not be empty")
            existing = await self.get_by_name(name)
            if existing is not None and existing.project_id != project_id:
                raise ValueError(f"project already exists: {name}")
            updates["name"] = name
        if "status" in updates and updates["status"] not in PROJECT_STATUSES:
            raise ValueError(f"invalid project status: {updates['status']}")
        if "memory_scope" in updates and updates["memory_scope"] not in {"global", "project-only"}:
            raise ValueError("memory_scope must be global or project-only")
        if "color" in updates:
            color = str(updates["color"] or "")
            if color and (len(color) not in (4, 7) or color[0] != "#" or any(char not in "0123456789abcdefABCDEF" for char in color[1:])):
                raise ValueError("project color must be a three- or six-digit hex color")
            updates["color"] = color
        if "icon" in updates:
            if not isinstance(updates["icon"], str) or updates["icon"] not in PROJECT_ICONS:
                raise ValueError("invalid project icon")
        if "pinned" in updates:
            updates["pinned"] = int(bool(updates["pinned"]))
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

    async def delete_project(self, project_id: str, memory_action: str = "archive") -> bool:
        db = self._require_db()
        if memory_action not in {"delete", "global", "archive"}:
            raise ValueError("memory_action must be delete, global or archive")
        if memory_action == "global":
            cursor = await db.execute("SELECT id,text,created_at FROM project_memories WHERE project_id=?", (project_id,))
            rows = await cursor.fetchall()
            await db.executemany("INSERT OR REPLACE INTO global_project_memories(id,text,created_at) VALUES(?,?,?)",
                                 [(row["id"], row["text"], row["created_at"]) for row in rows])
            await db.execute("DELETE FROM project_memories WHERE project_id=?", (project_id,))
        elif memory_action == "delete":
            await db.execute("DELETE FROM project_memories WHERE project_id=?", (project_id,))
        else:
            await db.execute("UPDATE project_memories SET project_id=? WHERE project_id=?", (f"archived:{project_id}", project_id))
        cursor = await db.execute(
            "DELETE FROM projects WHERE project_id = ?", (project_id,),
        )
        await db.execute(
            "DELETE FROM project_conversations WHERE project_id = ?", (project_id,),
        )
        await db.commit()
        return cursor.rowcount > 0

    async def add_project_memory(self, project_id: str, text: str, memory_id: str | None = None) -> dict[str, Any]:
        if await self.get(project_id) is None:
            raise KeyError(project_id)
        value = str(text).strip()
        if not value:
            raise ValueError("memory text must not be empty")
        item_id = memory_id or uuid.uuid4().hex
        db = self._require_db()
        existing = await db.execute("SELECT id FROM project_memories WHERE project_id=? AND text=? LIMIT 1", (project_id,value))
        prior = await existing.fetchone()
        if prior is not None:
            return {"id": str(prior["id"]), "project_id": project_id, "text": value}
        await db.execute("INSERT INTO project_memories(id,project_id,text) VALUES(?,?,?)", (item_id, project_id, value))
        await db.commit()
        return {"id": item_id, "project_id": project_id, "text": value}

    async def search_project_memories(self, project_id: str, query: str = "", limit: int = 8) -> list[dict[str, Any]]:
        db = self._require_db()
        words = [word for word in str(query).split() if len(word) > 1]
        clause = " AND ".join("text LIKE ?" for _ in words)
        params: list[Any] = [project_id, *[f"%{word}%" for word in words]]
        where = "project_id=?" + (f" AND {clause}" if clause else "")
        cursor = await db.execute(f"SELECT id,text,created_at FROM project_memories WHERE {where} ORDER BY created_at DESC LIMIT ?", (*params, max(1,min(int(limit),30))))
        return [dict(row) for row in await cursor.fetchall()]

    async def list_project_memories(self, project_id: str) -> list[dict[str, Any]]:
        return await self.search_project_memories(project_id, "", 100)

    async def search_global_memories(self, query: str = "", limit: int = 50) -> list[dict[str, Any]]:
        db = self._require_db()
        words = [word for word in str(query).split() if len(word) > 1]
        clause = " AND ".join("text LIKE ?" for _ in words)
        where = clause or "1=1"
        cursor = await db.execute(f"SELECT id,text,created_at FROM global_project_memories WHERE {where} ORDER BY created_at DESC LIMIT ?", (*[f"%{word}%" for word in words], max(1,min(int(limit),100))))
        return [dict(row) for row in await cursor.fetchall()]

    async def recall_project_memories(self, project_id: str, query: str, *, project_only: bool = False, limit: int = 8) -> list[dict[str, Any]]:
        rows = await self.search_project_memories(project_id, query, limit)
        if not project_only:
            rows.extend(await self.search_global_memories(query, max(1, limit - len(rows))))
        return rows[:max(1, limit)]

    async def move_global_memory(self, memory_id: str, target_project_id: str) -> bool:
        db = self._require_db()
        if await self.get(target_project_id) is None: raise KeyError(target_project_id)
        cursor = await db.execute("SELECT id,text,created_at FROM global_project_memories WHERE id=?", (memory_id,))
        row = await cursor.fetchone()
        if row is None: return False
        await db.execute("INSERT INTO project_memories(id,project_id,text,created_at) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET project_id=excluded.project_id,text=excluded.text",(row["id"],target_project_id,row["text"],row["created_at"]))
        await db.execute("DELETE FROM global_project_memories WHERE id=?",(memory_id,)); await db.commit(); return True

    async def move_project_memory(self, memory_id: str, target_project_id: str | None) -> bool:
        db = self._require_db()
        if target_project_id is None:
            cursor = await db.execute("SELECT id,text,created_at FROM project_memories WHERE id=?", (memory_id,))
            row = await cursor.fetchone()
            if row is None: return False
            await db.execute("INSERT OR REPLACE INTO global_project_memories(id,text,created_at) VALUES(?,?,?)", (row["id"],row["text"],row["created_at"]))
            await db.execute("DELETE FROM project_memories WHERE id=?", (memory_id,))
        else:
            if await self.get(target_project_id) is None: raise KeyError(target_project_id)
            cursor = await db.execute("UPDATE project_memories SET project_id=? WHERE id=?", (target_project_id,memory_id))
            if not cursor.rowcount: return False
        await db.commit()
        return True

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

    async def get_sources(self, project_id: str) -> dict[str, Any] | None:
        db = self._require_db()
        if await self.get(project_id) is None:
            return None
        cursor = await db.execute(
            "SELECT instructions FROM project_source_settings WHERE project_id=?",
            (project_id,),
        )
        row = await cursor.fetchone()
        cursor = await db.execute(
            "SELECT id, kind, title, path, url, text, bytes, added_at FROM project_sources "
            "WHERE project_id=? ORDER BY added_at, id", (project_id,),
        )
        return {"instructions": str(row["instructions"]) if row else "",
                "sources": [dict(item) for item in await cursor.fetchall()]}

    async def set_source_instructions(self, project_id: str, instructions: str) -> bool:
        db = self._require_db()
        if await self.get(project_id) is None:
            return False
        if len(instructions) > 8000:
            raise ValueError("项目指令不能超过 8000 字。")
        await db.execute(
            "INSERT INTO project_source_settings(project_id,instructions) VALUES(?,?) "
            "ON CONFLICT(project_id) DO UPDATE SET instructions=excluded.instructions",
            (project_id, instructions),
        )
        await db.commit()
        return True

    async def add_source(
        self, project_id: str, kind: str, *, title: str = "", path: str | None = None,
        url: str | None = None, text: str | None = None, web_extractor: Any = None,
        _source_id: str | None = None,
    ) -> dict[str, Any]:
        db = self._require_db()
        if await self.get(project_id) is None:
            raise KeyError(project_id)
        if kind not in {"file", "folder", "url", "note"}:
            raise ValueError("资料类型无效。")
        source_id = _source_id or uuid.uuid4().hex
        source_title = title.strip() or (Path(path).name if path else url or "项目备注")
        index_entries: list[tuple[str, str, int]] = []
        stored_text: str | None = None
        byte_count = 0
        cursor = await db.execute("SELECT COALESCE(SUM(bytes),0) AS total FROM project_sources WHERE project_id=?",
                                  (project_id,))
        current_bytes = int((await cursor.fetchone())["total"])
        if kind in {"file", "folder"}:
            if not path or not Path(path).is_absolute():
                raise ValueError("资料路径必须是绝对路径。")
            target = Path(path).expanduser().resolve()
            if kind == "file" and not target.is_file() or kind == "folder" and not target.is_dir():
                raise ValueError("资料路径不存在或类型不匹配。")
            candidates = [target] if target.is_file() else sorted(p for p in target.rglob("*") if p.is_file())
            for item in candidates:
                size = item.stat().st_size
                if (size > 2 * 1024 * 1024
                        or current_bytes + byte_count + size > 50 * 1024 * 1024):
                    continue
                extracted = await asyncio.to_thread(_extract_file_text, item)
                if not extracted:
                    continue
                byte_count += size
                index_entries.extend((str(item), chunk, size) for chunk in _chunks(extracted))
        elif kind == "url":
            if not url or web_extractor is None:
                raise ValueError("网页资料需要有效网址和正文提取服务。")
            extracted = web_extractor(url)
            extracted = await extracted if hasattr(extracted, "__await__") else extracted
            stored_text = str(extracted.get("text", ""))
            source_title = title.strip() or str(extracted.get("title") or url)
            byte_count = len(stored_text.encode("utf-8"))
            index_entries.extend((url, chunk, byte_count) for chunk in _chunks(stored_text))
        else:
            stored_text = str(text or "")
            byte_count = len(stored_text.encode("utf-8"))
            index_entries.extend(("", chunk, byte_count) for chunk in _chunks(stored_text))
        await db.execute(
            "INSERT INTO project_sources(id,project_id,kind,title,path,url,text,bytes) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (source_id, project_id, kind, source_title, path, url, stored_text, byte_count),
        )
        await self._replace_source_index(project_id, source_id, index_entries)
        await db.commit()
        return next(item for item in (await self.get_sources(project_id))["sources"]
                    if item["id"] == source_id)

    async def _replace_source_index(
        self, project_id: str, source_id: str, entries: list[tuple[str, str, int]],
    ) -> None:
        db = self._require_db()
        await db.execute("DELETE FROM project_source_fts WHERE source_id=?", (source_id,))
        await db.executemany(
            "INSERT INTO project_source_fts(project_id,source_id,path,text) VALUES(?,?,?,?)",
            [(project_id, source_id, path, content) for path, content, _size in entries],
        )

    async def search_sources(
        self, project_id: str, query: str, limit: int = 8,
    ) -> list[dict[str, Any]]:
        db = self._require_db()
        words = [word for word in query.strip().split() if word]
        if not words:
            return []
        limit = min(max(int(limit), 1), 20)
        expression = " OR ".join('"' + word.replace('"', '""') + '"' for word in words)
        try:
            cursor = await db.execute(
                "SELECT s.title,f.path,f.text,bm25(project_source_fts) AS rank "
                "FROM project_source_fts f JOIN project_sources s ON s.id=f.source_id "
                "WHERE f.project_id=? AND project_source_fts MATCH ? "
                "ORDER BY rank LIMIT ?", (project_id, expression, limit),
            )
            rows = await cursor.fetchall()
            if not rows:
                clauses = " OR ".join("f.text LIKE ?" for _ in words)
                cursor = await db.execute(
                    "SELECT s.title,f.path,f.text,0.0 AS rank FROM project_source_fts f "
                    "JOIN project_sources s ON s.id=f.source_id WHERE f.project_id=? AND (" + clauses + ") LIMIT ?",
                    (project_id, *[f"%{word}%" for word in words], limit),
                )
                rows = await cursor.fetchall()
        except Exception:
            clauses = " OR ".join("f.text LIKE ?" for _ in words)
            cursor = await db.execute(
                "SELECT s.title,f.path,f.text,0.0 AS rank FROM project_source_fts f "
                "JOIN project_sources s ON s.id=f.source_id WHERE f.project_id=? AND (" + clauses + ") LIMIT ?",
                (project_id, *[f"%{word}%" for word in words], limit),
            )
            rows = await cursor.fetchall()
        return [{"title": row["title"], "path": row["path"],
                 "snippet": str(row["text"])[:1200], "score": float(row["rank"])}
                for row in rows]

    async def delete_source(self, project_id: str, source_id: str) -> bool:
        db = self._require_db()
        await db.execute("DELETE FROM project_source_fts WHERE source_id=?", (source_id,))
        cursor = await db.execute(
            "DELETE FROM project_sources WHERE project_id=? AND id=?", (project_id, source_id),
        )
        await db.commit()
        return cursor.rowcount > 0

    async def refresh_source(self, project_id: str, source_id: str, **kwargs: Any) -> dict[str, Any] | None:
        db = self._require_db()
        cursor = await db.execute(
            "SELECT kind,title,path,url,text FROM project_sources WHERE project_id=? AND id=?",
            (project_id, source_id),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        await self.delete_source(project_id, source_id)
        return await self.add_source(
            project_id, row["kind"], title=row["title"], path=row["path"],
            url=row["url"], text=row["text"], web_extractor=kwargs.get("web_extractor"),
            _source_id=source_id,
        )


def _chunks(text: str, size: int = 1000, overlap: int = 120) -> list[str]:
    clean = text.strip()
    return [clean[index:index + size] for index in range(0, len(clean), size - overlap)] if clean else []


def _extract_file_text(path: Path) -> str:
    suffix = path.suffix.casefold()
    if suffix in _TEXT_SUFFIXES:
        return path.read_text(encoding="utf-8", errors="replace")
    try:
        if suffix == ".docx":
            from docx import Document
            doc = Document(path)
            return "\n".join([p.text for p in doc.paragraphs] + [
                "\t".join(cell.text for cell in row.cells)
                for table in doc.tables for row in table.rows
            ])
        if suffix == ".xlsx":
            from openpyxl import load_workbook
            book = load_workbook(path, read_only=True, data_only=True)
            return "\n".join("\t".join(str(value or "") for value in row)
                              for sheet in book for row in sheet.iter_rows(values_only=True))
        if suffix == ".pptx":
            from pptx import Presentation
            return "\n".join(shape.text for slide in Presentation(path).slides
                              for shape in slide.shapes if getattr(shape, "has_text_frame", False))
        if suffix == ".pdf":
            from pypdf import PdfReader
            return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    except (ImportError, OSError, ValueError):
        return ""
    return ""
