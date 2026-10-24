"""Atlas conversation store — SQLite + FTS5 for conversation metadata, legacy
messages, rewinds and user-provided reference notes (资料).

Long-term memory lives in the transparent memory library
(``atlas.memory.library``, data/memory); this store holds no memory of its own.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from pathlib import Path
from typing import Any

import aiosqlite
import structlog

from atlas.config import get_config

# memory.init() runs inside lifespan(), before uvicorn binds the port. These bounds turn a
# locked or wedged database into a fast, loud failure instead of a silent hang.
_DB_CONNECT_TIMEOUT_S = 5.0
_DB_INIT_TIMEOUT_S = 20.0
# Kept well under the init timeout on purpose: SQLite retries a locked database for the
# whole busy_timeout inside a single C call, and asyncio.wait_for cannot interrupt that
# (measured: a locked CREATE TABLE took 7.4s to return with the driver default). A short
# value makes the failure surface before the outer timeout instead of after it.
_DB_BUSY_TIMEOUT_MS = 2000
_FAILED_INIT_CLOSE_S = 0.5

log = structlog.get_logger()

# Tables of the retired memory systems (facts/candidates/reflections/goal
# knowledge). Dropped on start so no old memory survives in atlas.db.
_RETIRED_TABLES = (
    "facts", "memory_candidates", "memory_candidates_legacy", "memory_fact_history",
    "memory_commitment_history", "memory_usage_events", "memory_feedback",
    "memory_evaluations", "memory_optimization_reports", "memory_maturity_reports",
    "memory_self_steering_reports", "memory_optimization_candidates",
    "memory_optimization_candidate_reviews", "memory_consolidation_proposals",
    "memory_consolidation_proposal_reviews", "memory_knowledge_activations",
    "memory_knowledge_activation_history", "memory_knowledge_verifications",
    "memory_knowledge_verification_history", "memory_knowledge_health_reports",
    "memory_knowledge_health_report_reviews", "memory_knowledge_consolidated_insights",
    "memory_knowledge_insight_applications", "agent_reflections", "goal_outcomes",
    "goal_knowledge", "goal_knowledge_usage_events", "goal_knowledge_feedback_events",
    "goal_knowledge_proposals", "goal_knowledge_refinement_evaluations",
    "goal_knowledge_refinements", "goal_knowledge_governance_events",
    "goal_knowledge_evolution_evaluations", "goal_knowledge_evolution_recommendations",
)


class MemoryStore:
    """SQLite store for conversation metadata, messages, rewinds and 资料 notes."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or get_config().db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        """Initialize database and create tables.

        Bounded on purpose: ``lifespan()`` awaits this before uvicorn binds the port, so
        an unbounded wait here leaves the port closed and the UI reports that it cannot
        reach the backend with no diagnostic. A locked or wedged database now fails
        loudly and quickly instead of hanging start-up.
        """
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._db = await asyncio.wait_for(
                aiosqlite.connect(str(self._db_path), timeout=_DB_CONNECT_TIMEOUT_S),
                timeout=_DB_INIT_TIMEOUT_S,
            )
        except (asyncio.TimeoutError, TimeoutError) as exc:
            await self._close_after_failed_init()
            raise TimeoutError(
                f"memory.init timed out after {_DB_INIT_TIMEOUT_S:.0f}s opening {self._db_path}; "
                "the database may be locked by another process"
            ) from exc
        self._db.row_factory = aiosqlite.Row
        # Wait on a held write lock rather than failing the statement immediately.
        await self._db.execute(f"PRAGMA busy_timeout = {_DB_BUSY_TIMEOUT_MS}")
        await self._db.execute("PRAGMA foreign_keys = ON")
        try:
            await asyncio.wait_for(self._create_tables(), timeout=_DB_INIT_TIMEOUT_S)
        except (asyncio.TimeoutError, TimeoutError) as exc:
            # wait_for cancels _create_tables, but the aiosqlite worker thread stays
            # alive mid-statement. Close it here so a failed boot does not leave a
            # thread that dies later with "Event loop is closed".
            await self._close_after_failed_init()
            raise TimeoutError(
                f"memory.init timed out after {_DB_INIT_TIMEOUT_S:.0f}s creating tables in "
                f"{self._db_path}; the database may be locked by another process"
            ) from exc
        log.info("memory.init", db=str(self._db_path))

    async def _close_after_failed_init(self) -> None:
        """Best-effort teardown of a half-initialised connection.

        Kept short: the connection is already stuck on a locked database, so waiting on
        close() would just add its full timeout to a boot that has already failed.
        """
        db, self._db = self._db, None
        if db is None:
            return
        try:
            await asyncio.wait_for(db.close(), timeout=_FAILED_INIT_CLOSE_S)
        except Exception:
            log.warning("memory.init_close_failed", db=str(self._db_path))

    async def _create_tables(self) -> None:
        assert self._db is not None
        await self._db.executescript("""
            -- Conversations
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT 'New Conversation',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                metadata TEXT DEFAULT '{}',
                pinned INTEGER NOT NULL DEFAULT 0,
                archived INTEGER NOT NULL DEFAULT 0,
                workspace TEXT,
                worktree_path TEXT,
                worktree_branch TEXT,
                base_branch TEXT,
                parent_conversation_id TEXT,
                fork_message_id TEXT,
                permission_mode TEXT NOT NULL DEFAULT 'full_access',
                allowed_paths TEXT NOT NULL DEFAULT '[]',
                executor TEXT NOT NULL DEFAULT 'atlas',
                sandbox TEXT NOT NULL DEFAULT 'null',
                extra_roots TEXT NOT NULL DEFAULT '[]',
                source TEXT NOT NULL DEFAULT 'desktop'
            );

            -- Messages
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system', 'tool')),
                content TEXT NOT NULL,
                metadata TEXT DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            );

            CREATE INDEX IF NOT EXISTS idx_messages_conv
                ON messages(conversation_id, created_at);

            CREATE TABLE IF NOT EXISTS conversation_rewinds (
                rewind_id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                removed_messages INTEGER NOT NULL DEFAULT 0,
                restored_files INTEGER NOT NULL DEFAULT 0,
                redone INTEGER NOT NULL DEFAULT 0,
                snapshot TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_conversation_rewinds
                ON conversation_rewinds(conversation_id, created_at DESC);

            -- Full-text search on messages
            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                content, content=messages, content_rowid=rowid
            );

            -- Triggers to keep FTS in sync
            CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
                INSERT INTO messages_fts(rowid, content) VALUES (new.rowid, new.content);
            END;

            CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
                INSERT INTO messages_fts(messages_fts, rowid, content)
                    VALUES ('delete', old.rowid, old.content);
            END;

            CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
                INSERT INTO messages_fts(messages_fts, rowid, content)
                    VALUES ('delete', old.rowid, old.content);
                INSERT INTO messages_fts(rowid, content) VALUES (new.rowid, new.content);
            END;
        """)
        await self._db.execute("PRAGMA foreign_keys = OFF")
        for table in _RETIRED_TABLES:
            await self._db.execute(f"DROP TABLE IF EXISTS {table}")
        await self._db.execute("PRAGMA foreign_keys = ON")
        cursor = await self._db.execute("PRAGMA table_info(conversations)")
        conversation_columns = {row["name"] for row in await cursor.fetchall()}
        for name, declaration in (("pinned", "INTEGER NOT NULL DEFAULT 0"),
                                  ("archived", "INTEGER NOT NULL DEFAULT 0"),
                                  ("workspace", "TEXT"), ("worktree_path", "TEXT"),
                                  ("worktree_branch", "TEXT"), ("base_branch", "TEXT"),
                                  ("parent_conversation_id", "TEXT"), ("fork_message_id", "TEXT"),
                                  ("permission_mode", "TEXT NOT NULL DEFAULT 'full_access'"),
                                  ("allowed_paths", "TEXT NOT NULL DEFAULT '[]'"),
                                  ("executor", "TEXT NOT NULL DEFAULT 'atlas'"),
                                  ("sandbox", "TEXT NOT NULL DEFAULT 'null'"),
                                  ("extra_roots", "TEXT NOT NULL DEFAULT '[]'"),
                                  ("source", "TEXT NOT NULL DEFAULT 'desktop'")):
            if name not in conversation_columns:
                await self._db.execute(
                    f"ALTER TABLE conversations ADD COLUMN {name} {declaration}"
                )
        cursor = await self._db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='messages_fts'"
        )
        fts_sql = (await cursor.fetchone())["sql"] or ""
        if "trigram" not in fts_sql.casefold():
            await self._db.executescript("""
                DROP TRIGGER IF EXISTS messages_ai;
                DROP TRIGGER IF EXISTS messages_ad;
                DROP TRIGGER IF EXISTS messages_au;
                DROP TABLE IF EXISTS messages_fts;
                CREATE VIRTUAL TABLE messages_fts USING fts5(
                    content, content=messages, content_rowid=rowid, tokenize='trigram'
                );
                INSERT INTO messages_fts(messages_fts) VALUES ('rebuild');
                CREATE TRIGGER messages_ai AFTER INSERT ON messages BEGIN
                    INSERT INTO messages_fts(rowid, content) VALUES (new.rowid, new.content);
                END;
                CREATE TRIGGER messages_ad AFTER DELETE ON messages BEGIN
                    INSERT INTO messages_fts(messages_fts, rowid, content)
                    VALUES ('delete', old.rowid, old.content);
                END;
                CREATE TRIGGER messages_au AFTER UPDATE ON messages BEGIN
                    INSERT INTO messages_fts(messages_fts, rowid, content)
                    VALUES ('delete', old.rowid, old.content);
                    INSERT INTO messages_fts(rowid, content) VALUES (new.rowid, new.content);
                END;
            """)
        await self._db.commit()

    # ----- Conversations -----

    async def create_conversation(self, title: str = "New Conversation") -> str:
        assert self._db is not None
        conv_id = str(uuid.uuid4())
        await self._db.execute(
            "INSERT INTO conversations (id, title) VALUES (?, ?)",
            (conv_id, title),
        )
        await self._db.commit()
        return conv_id

    async def save_conversation_metadata(
        self, conversation_id: str, *, title_hint: str = "",
    ) -> None:
        """Create/touch conversation metadata without persisting transcript text."""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT id, title FROM conversations WHERE id = ?", (conversation_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            title = title_hint[:30].strip() + ("..." if len(title_hint) > 30 else "")
            await self._db.execute(
                "INSERT INTO conversations (id, title) VALUES (?, ?)",
                (conversation_id, title or "New Conversation"),
            )
        else:
            await self._db.execute(
                "UPDATE conversations SET updated_at=datetime('now') WHERE id=?",
                (conversation_id,),
            )
        await self._db.commit()

    async def fork_conversation_metadata(
        self, conversation_id: str, *, title: str | None = None,
    ) -> dict[str, Any] | None:
        """Create only the Atlas metadata row for a SessionDB-owned branch."""
        source = await self.get_conversation(conversation_id)
        if source is None:
            return None
        fork_id = await self.create_conversation(title or f"{source['title']} (fork)")
        await self.update_conversation(
            fork_id, parent_conversation_id=conversation_id, workspace=source.get("workspace"),
            permission_mode=source.get("permission_mode"), source=source.get("source"),
        )
        return await self.get_conversation(fork_id)

    async def list_conversations(self, limit: int | None = 50) -> list[dict[str, Any]]:
        assert self._db is not None
        query = (
            "SELECT id, title, created_at, updated_at, pinned, archived, workspace, "
            "worktree_path, worktree_branch, base_branch, parent_conversation_id, fork_message_id, "
            "permission_mode, allowed_paths, executor, sandbox, extra_roots, source "
            "FROM conversations ORDER BY pinned DESC, updated_at DESC"
        )
        cursor = await self._db.execute(query if limit is None else query + " LIMIT ?",
                                        () if limit is None else (limit,))
        rows = await cursor.fetchall()
        return [{**dict(r), "pinned": bool(r["pinned"]),
                 "archived": bool(r["archived"]),
                 "allowed_paths": json.loads(r["allowed_paths"] or "[]"),
                 "sandbox": json.loads(r["sandbox"] or "null"),
                 "extra_roots": json.loads(r["extra_roots"] or "[]"),
                 "source": r["source"]} for r in rows]

    async def get_conversation_messages(
        self, conversation_id: str, limit: int = 100, before_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Return a page of messages in ascending order.

        Default page: the NEWEST ``limit`` messages (was: the oldest — the LIMIT
        on an ASC query silently returned the head of the history).  ``before_id``
        returns the page immediately BEFORE that message id, so a client can page
        backwards through history.  Output is always oldest → newest.
        """
        assert self._db is not None
        if before_id:
            cursor = await self._db.execute(
                "SELECT created_at, rowid FROM messages WHERE id = ? AND conversation_id = ?",
                (before_id, conversation_id),
            )
            anchor = await cursor.fetchone()
            if anchor is None:
                return []
            cursor = await self._db.execute(
                "SELECT id, role, content, metadata, created_at FROM messages "
                "WHERE conversation_id = ? "
                "AND (created_at < ? OR (created_at = ? AND rowid < ?)) "
                "ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (conversation_id, anchor["created_at"], anchor["created_at"], anchor["rowid"], limit),
            )
        else:
            cursor = await self._db.execute(
                "SELECT id, role, content, metadata, created_at FROM messages "
                "WHERE conversation_id = ? ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (conversation_id, limit),
            )
        rows = list(reversed(await cursor.fetchall()))
        messages: list[dict[str, Any]] = []
        for row in rows:
            message = dict(row)
            try:
                metadata = json.loads(message["metadata"] or "{}")
            except (TypeError, json.JSONDecodeError):
                metadata = {}
            message["metadata"] = metadata if isinstance(metadata, dict) else {}
            messages.append(message)
        return messages

    # ----- Messages -----

    async def save_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        assert self._db is not None

        # Auto-create conversation if it doesn't exist
        cursor = await self._db.execute(
            "SELECT id FROM conversations WHERE id = ?",
            (conversation_id,),
        )
        if not await cursor.fetchone():
            # Use first ~30 chars of content as title
            title = content[:30].strip() + ("..." if len(content) > 30 else "")
            await self._db.execute(
                "INSERT INTO conversations (id, title) VALUES (?, ?)",
                (conversation_id, title),
            )

        msg_id = str(uuid.uuid4())
        await self._db.execute(
            "INSERT INTO messages (id, conversation_id, role, content, metadata) "
            "VALUES (?, ?, ?, ?, ?)",
            (msg_id, conversation_id, role, content, json.dumps(metadata or {})),
        )

        # Update conversation timestamp
        await self._db.execute(
            "UPDATE conversations SET updated_at = datetime('now') WHERE id = ?",
            (conversation_id,),
        )

        await self._db.commit()
        return msg_id

    async def save_message_first(
        self, conversation_id: str, role: str, content: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Insert a message before the current transcript, used for fork summaries."""
        assert self._db is not None
        msg_id = str(uuid.uuid4())
        await self._db.execute(
            "INSERT INTO messages (id, conversation_id, role, content, metadata, created_at) "
            "VALUES (?, ?, ?, ?, ?, '0001-01-01T00:00:00+00:00')",
            (msg_id, conversation_id, role, content, json.dumps(metadata or {})),
        )
        await self._db.execute(
            "UPDATE conversations SET updated_at=datetime('now') WHERE id=?",
            (conversation_id,),
        )
        await self._db.commit()
        return msg_id

    async def save_branch_summary(
        self, parent_id: str, child_id: str, fork_message_id: str, content: str,
    ) -> str:
        """Upsert one structured branch summary immediately after its fork-point message."""
        assert self._db is not None
        messages = await self.get_conversation_messages(parent_id, limit=100000)
        anchor = next((item for item in messages if item["id"] == fork_message_id), None)
        if anchor is None:
            raise ValueError("branch fork point is missing from the parent transcript")
        metadata = {"kind": "branch_summary", "child_conversation_id": child_id,
                    "fork_message_id": fork_message_id}
        existing = next((item for item in messages
                         if item.get("metadata", {}).get("kind") == "branch_summary"
                         and item.get("metadata", {}).get("child_conversation_id") == child_id), None)
        if existing:
            await self._db.execute("UPDATE messages SET content=?,metadata=? WHERE id=?",
                                   (content, json.dumps(metadata), existing["id"]))
            msg_id = str(existing["id"])
        else:
            msg_id = str(uuid.uuid4())
            await self._db.execute(
                "INSERT INTO messages (id, conversation_id, role, content, metadata, created_at) VALUES (?,?,?,?,?,?)",
                (msg_id, parent_id, "assistant", content, json.dumps(metadata), anchor["created_at"]),
            )
        await self._db.execute("UPDATE conversations SET updated_at=datetime('now') WHERE id=?", (parent_id,))
        await self._db.commit()
        return msg_id

    # ----- Search -----

    async def search(
        self, query: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Full-text search across all messages."""
        assert self._db is not None
        normalized = query.strip()
        if not normalized:
            return []
        if len(normalized) < 3:
            cursor = await self._db.execute(
                "SELECT m.id, m.conversation_id, m.role, m.content, m.created_at, "
                "c.title, substr(m.content, 1, 200) AS snippet "
                "FROM messages m JOIN conversations c ON c.id=m.conversation_id "
                "WHERE m.content LIKE ? ORDER BY m.created_at DESC LIMIT ?",
                (f"%{normalized}%", limit),
            )
        else:
            cursor = await self._db.execute(
                "SELECT m.id, m.conversation_id, m.role, m.content, m.created_at, "
                "c.title, highlight(messages_fts, 0, '<b>', '</b>') AS snippet "
                "FROM messages_fts JOIN messages m ON messages_fts.rowid = m.rowid "
                "JOIN conversations c ON c.id=m.conversation_id "
                "WHERE messages_fts MATCH ? ORDER BY rank LIMIT ?",
                (f'"{normalized.replace(chr(34), chr(34) * 2)}"', limit),
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def session_search(
        self, query: str, limit: int = 8, context: int = 2,
        conversation_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Search raw past conversations and return hits with surrounding context.

        This is the raw-history recall path ("what exactly did I say back then"),
        complementary to the summarized knowledge in facts/knowledge tables.
        When ``conversation_ids`` is provided, only those conversations are
        searched (used for project-scoped recall).
        """
        if not (query or "").strip():
            return []
        from atlas.config import DATA_ROOT
        from atlas.engine.session_sync import search_session_messages

        session_home = DATA_ROOT / "engine"
        if (session_home / "state.db").exists():
            hits = await asyncio.to_thread(
                search_session_messages, session_home, query, limit=limit,
            )
        else:
            assert self._db is not None
            tokens = re.findall(r"[\w\u4e00-\u9fff]+", query or "")
            if not tokens:
                return []
            match_query = " OR ".join(f'"{token}"' for token in tokens[:12])
            hits = []
            try:
                cursor = await self._db.execute(
                    "SELECT m.id, m.conversation_id, m.role, m.content, m.created_at, "
                    "c.title AS conversation_title, "
                    "highlight(messages_fts, 0, '[', ']') AS snippet "
                    "FROM messages_fts JOIN messages m ON messages_fts.rowid=m.rowid "
                    "JOIN conversations c ON c.id=m.conversation_id "
                    "WHERE messages_fts MATCH ? ORDER BY rank LIMIT ?",
                    (match_query, limit),
                )
                hits = [dict(row) for row in await cursor.fetchall()]
            except aiosqlite.OperationalError:
                hits = []
            if not hits:
                cursor = await self._db.execute(
                    "SELECT m.id, m.conversation_id, m.role, m.content, m.created_at, "
                    "c.title AS conversation_title, substr(m.content, 1, 200) AS snippet "
                    "FROM messages m JOIN conversations c ON c.id=m.conversation_id "
                    "WHERE m.content LIKE ? ORDER BY m.created_at DESC LIMIT ?",
                    (f"%{query.strip()}%", limit),
                )
                hits = [dict(row) for row in await cursor.fetchall()]
        if conversation_ids is not None:
            allowed = {str(value) for value in conversation_ids}
            hits = [hit for hit in hits if str(hit["conversation_id"]) in allowed]
        for hit in hits:
            conversation = await self.get_conversation(str(hit["conversation_id"]))
            hit["conversation_title"] = (conversation or {}).get("title", "")
            hit["context"] = await self._session_context(
                str(hit["conversation_id"]), str(hit["id"]), context,
            )
        return hits

    async def _session_context(
        self, conversation_id: str, message_id: str, window: int,
    ) -> list[dict[str, Any]]:
        from atlas.config import DATA_ROOT

        session_home = DATA_ROOT / "engine"
        if (session_home / "state.db").exists():
            from atlas.engine.session_sync import read_session_all_messages

            messages = await asyncio.to_thread(
                read_session_all_messages, session_home, conversation_id,
            )
        else:
            assert self._db is not None
            cursor = await self._db.execute(
                "SELECT id, role, content, created_at FROM messages "
                "WHERE conversation_id = ? ORDER BY created_at ASC, rowid ASC",
                (conversation_id,),
            )
            messages = [dict(row) for row in await cursor.fetchall()]
        index = next(
            (i for i, message in enumerate(messages) if message["id"] == message_id), None,
        )
        if index is None:
            return []
        return messages[max(index - window, 0): index + window + 1]


    # ----- Conversation management -----

    async def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        """Return a single conversation by ID, or None."""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT id, title, created_at, updated_at, metadata, pinned, archived, workspace, "
            "worktree_path, worktree_branch, base_branch, parent_conversation_id, fork_message_id, "
            "permission_mode, allowed_paths, executor, sandbox, extra_roots, source "
            "FROM conversations WHERE id = ?",
            (conversation_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        result = dict(row)
        result["allowed_paths"] = json.loads(result.get("allowed_paths") or "[]")
        result["sandbox"] = json.loads(result.get("sandbox") or "null")
        result["extra_roots"] = json.loads(result.get("extra_roots") or "[]")
        return result

    async def update_conversation(
        self, conversation_id: str, *, title: str | None = None,
        pinned: bool | None = None, archived: bool | None = None,
        workspace: str | None = None, worktree_path: str | None = None,
        worktree_branch: str | None = None, base_branch: str | None = None,
        parent_conversation_id: str | None = None, fork_message_id: str | None = None,
        permission_mode: str | None = None, allowed_paths: list[str] | None = None,
        executor: str | None = None, sandbox: dict[str, Any] | None = None,
        sandbox_set: bool = False,
        extra_roots: list[str] | None = None,
        source: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Update optional conversation fields. Returns True if found."""
        assert self._db is not None
        fields = {"title": title, "pinned": None if pinned is None else int(pinned),
                  "archived": None if archived is None else int(archived),
                  "workspace": workspace, "worktree_path": worktree_path,
                  "worktree_branch": worktree_branch, "base_branch": base_branch,
                  "parent_conversation_id": parent_conversation_id,
                  "fork_message_id": fork_message_id}
        fields["permission_mode"] = permission_mode
        fields["allowed_paths"] = None if allowed_paths is None else json.dumps(allowed_paths)
        fields["executor"] = executor
        fields["sandbox"] = json.dumps(sandbox) if sandbox_set else None
        fields["extra_roots"] = None if extra_roots is None else json.dumps(extra_roots)
        fields["source"] = source
        fields["metadata"] = json.dumps(metadata, ensure_ascii=False) if metadata is not None else None
        if not any(value is not None for value in fields.values()):
            cursor = await self._db.execute(
                "SELECT 1 FROM conversations WHERE id=?", (conversation_id,)
            )
            return await cursor.fetchone() is not None
        updates = ", ".join(f"{key}=?" for key, value in fields.items()
                             if value is not None)
        values = [value for value in fields.values() if value is not None]
        cursor = await self._db.execute(
            f"UPDATE conversations SET {updates}, updated_at=datetime('now') WHERE id=?",
            (*values, conversation_id),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def update_conversation_title(self, conversation_id: str, title: str) -> bool:
        return await self.update_conversation(conversation_id, title=title)

    async def truncate_conversation(self, conversation_id: str, message_id: str) -> bool:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT rowid FROM messages WHERE conversation_id=? AND id=?",
            (conversation_id, message_id),
        )
        row = await cursor.fetchone()
        if row is None:
            return False
        await self._db.execute(
            "DELETE FROM messages WHERE conversation_id=? AND rowid>=?",
            (conversation_id, row["rowid"]),
        )
        await self._db.execute(
            "UPDATE conversations SET updated_at=datetime('now') WHERE id=?",
            (conversation_id,),
        )
        await self._db.commit()
        return True

    async def fork_conversation(
        self, conversation_id: str, through_message_id: str,
    ) -> dict[str, Any] | None:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT rowid FROM messages WHERE conversation_id=? AND id=?",
            (conversation_id, through_message_id),
        )
        boundary = await cursor.fetchone()
        source = await self.get_conversation(conversation_id)
        if not boundary or not source:
            return None
        fork_id = await self.create_conversation(f"{source['title']} (fork)")
        rows = await self._db.execute_fetchall(
            "SELECT role, content, metadata FROM messages WHERE conversation_id=? AND rowid<=? "
            "ORDER BY rowid", (conversation_id, boundary["rowid"]),
        )
        for row in rows:
            try:
                metadata = json.loads(row["metadata"] or "{}")
            except (TypeError, json.JSONDecodeError):
                metadata = {}
            await self.save_message(fork_id, row["role"], row["content"], metadata)
        return {**(await self.get_conversation(fork_id) or {}), "files_shared": True}

    async def delete_conversation(self, conversation_id: str) -> bool:
        """Delete the SessionDB transcript, legacy body rows and Atlas metadata."""
        assert self._db is not None
        if await self.get_conversation(conversation_id) is None:
            return False
        from atlas.config import DATA_ROOT
        from atlas.engine.session_sync import delete_session

        await asyncio.to_thread(delete_session, DATA_ROOT / "engine", conversation_id)
        await self._db.execute(
            "DELETE FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        )
        cursor = await self._db.execute(
            "DELETE FROM conversations WHERE id = ?",
            (conversation_id,),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def get_messages_with_rowid(self, conversation_id: str) -> list[dict[str, Any]]:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT rowid AS row_id,id,conversation_id,role,content,metadata,created_at "
            "FROM messages WHERE conversation_id=? ORDER BY rowid", (conversation_id,),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def remove_messages_from(self, conversation_id: str, message_id: str) -> int | None:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT rowid FROM messages WHERE conversation_id=? AND id=?",
            (conversation_id, message_id),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        first_row = int(row["rowid"])
        await self._db.execute(
            "DELETE FROM messages WHERE conversation_id=? AND rowid>=?",
            (conversation_id, first_row),
        )
        await self._db.commit()
        return first_row

    async def replace_messages(self, conversation_id: str, messages: list[dict[str, Any]]) -> None:
        assert self._db is not None
        await self._db.execute("BEGIN IMMEDIATE")
        await self._db.execute("DELETE FROM messages WHERE conversation_id=?", (conversation_id,))
        await self._db.executemany(
            "INSERT INTO messages(rowid,id,conversation_id,role,content,metadata,created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            [(item["row_id"], item["id"], conversation_id, item["role"], item["content"],
              item.get("metadata", "{}"), item["created_at"]) for item in messages],
        )
        await self._db.commit()

    async def save_rewind(self, record: dict[str, Any]) -> None:
        assert self._db is not None
        await self._db.execute(
            "INSERT INTO conversation_rewinds(rewind_id,conversation_id,removed_messages,"
            "restored_files,snapshot) VALUES(?,?,?,?,?)",
            (record["rewind_id"], record["conversation_id"], record["removed_messages"],
             record["restored_files"], json.dumps(record["snapshot"], ensure_ascii=False)),
        )
        await self._db.execute(
            "DELETE FROM conversation_rewinds WHERE conversation_id=? AND rewind_id NOT IN "
            "(SELECT rewind_id FROM conversation_rewinds WHERE conversation_id=? "
            "ORDER BY created_at DESC,rowid DESC LIMIT 5)",
            (record["conversation_id"], record["conversation_id"]),
        )
        await self._db.commit()

    async def list_rewinds(self, conversation_id: str) -> list[dict[str, Any]]:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT rewind_id,created_at,removed_messages,restored_files,redone "
            "FROM conversation_rewinds WHERE conversation_id=? "
            "ORDER BY created_at DESC,rowid DESC LIMIT 5", (conversation_id,),
        )
        return [{**dict(row), "redone": bool(row["redone"])} for row in await cursor.fetchall()]

    async def get_rewind(self, conversation_id: str, rewind_id: str) -> dict[str, Any] | None:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT * FROM conversation_rewinds WHERE conversation_id=? AND rewind_id=?",
            (conversation_id, rewind_id),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        record = dict(row)
        record["snapshot"] = json.loads(record["snapshot"])
        record["redone"] = bool(record["redone"])
        return record

    async def mark_rewind_redone(self, conversation_id: str, rewind_id: str) -> None:
        assert self._db is not None
        await self._db.execute(
            "UPDATE conversation_rewinds SET redone=1 WHERE conversation_id=? AND rewind_id=?",
            (conversation_id, rewind_id),
        )
        await self._db.commit()

    async def update_rewind_restored_files(self, rewind_id: str,
                                           restored_files: int) -> None:
        """RUNTIME_AUTHORITY（authority-map 1.0）：rewind 恢复文件计数回写。

        T01.3：取代 conversations_router rewind_redo 端点直摸 ``memory._db``
        的唯一写点（与 mark_rewind_redone 同型）；表为运行权威，保留本地。
        """
        assert self._db is not None
        await self._db.execute(
            "UPDATE conversation_rewinds SET restored_files=? WHERE rewind_id=?",
            (restored_files, rewind_id),
        )
        await self._db.commit()

    async def list_conversation_ids(self) -> list[str]:
        """RUNTIME_AUTHORITY（authority-map 1.0）：有消息的会话 ID 清单（只读）。

        T01.3：取代 engine/session_sync.py 遗留会话迁移直摸
        ``memory_store._db`` 的 DISTINCT 只读查询；迁移退役后本方法随之删除。
        """
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT DISTINCT c.id FROM conversations c "
            "JOIN messages m ON m.conversation_id=c.id"
        )
        return [str(row[0]) for row in await cursor.fetchall()]


    # ----- Knowledge Base (vector search placeholder) -----

    async def _ensure_knowledge_table(self) -> None:
        """Create knowledge table for embeddings if it doesn't exist."""
        assert self._db is not None
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS knowledge (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                embedding BLOB,
                source TEXT DEFAULT '',
                category TEXT DEFAULT 'general',
                metadata TEXT DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_knowledge_category
                ON knowledge(category);

            -- FTS for keyword fallback
            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
                content,
                source,
                content=knowledge,
                content_rowid=rowid
            );

            CREATE TRIGGER IF NOT EXISTS knowledge_ai AFTER INSERT ON knowledge BEGIN
                INSERT INTO knowledge_fts(rowid, content, source)
                    VALUES (new.rowid, new.content, new.source);
            END;

            CREATE TRIGGER IF NOT EXISTS knowledge_ad AFTER DELETE ON knowledge BEGIN
                INSERT INTO knowledge_fts(knowledge_fts, rowid, content, source)
                    VALUES ('delete', old.rowid, old.content, old.source);
            END;

            CREATE TRIGGER IF NOT EXISTS knowledge_au AFTER UPDATE ON knowledge BEGIN
                INSERT INTO knowledge_fts(knowledge_fts, rowid, content, source)
                    VALUES ('delete', old.rowid, old.content, old.source);
                INSERT INTO knowledge_fts(rowid, content, source)
                    VALUES (new.rowid, new.content, new.source);
            END;
        """)
        await self._db.commit()

    async def add_knowledge(
        self,
        content: str,
        source: str = "",
        category: str = "general",
        metadata: dict[str, Any] | None = None,
        embedding: bytes | None = None,
    ) -> str:
        """Add a knowledge entry.

        Args:
            content: The text content.
            source: Where this came from (URL, file path, etc.).
            category: Grouping label.
            metadata: Extra metadata dict.
            embedding: Pre-computed embedding as bytes (optional).

        Returns:
            The new entry's ID.
        """
        assert self._db is not None
        await self._ensure_knowledge_table()

        entry_id = str(uuid.uuid4())
        await self._db.execute(
            "INSERT INTO knowledge (id, content, embedding, source, category, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (entry_id, content, embedding, source, category,
             json.dumps(metadata or {})),
        )
        await self._db.commit()
        return entry_id

    async def search_knowledge(
        self,
        query: str,
        category: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search knowledge base using FTS5 (keyword search).

        Vector similarity search will be added when embeddings are
        integrated; for now this provides keyword-based retrieval.
        """
        assert self._db is not None
        await self._ensure_knowledge_table()

        if category:
            cursor = await self._db.execute(
                "SELECT k.id, k.content, k.source, k.category, k.metadata, "
                "       k.created_at, "
                "       highlight(knowledge_fts, 0, '<b>', '</b>') AS snippet "
                "FROM knowledge_fts "
                "JOIN knowledge k ON knowledge_fts.rowid = k.rowid "
                "WHERE knowledge_fts MATCH ? AND k.category = ? "
                "ORDER BY rank LIMIT ?",
                (query, category, limit),
            )
        else:
            cursor = await self._db.execute(
                "SELECT k.id, k.content, k.source, k.category, k.metadata, "
                "       k.created_at, "
                "       highlight(knowledge_fts, 0, '<b>', '</b>') AS snippet "
                "FROM knowledge_fts "
                "JOIN knowledge k ON knowledge_fts.rowid = k.rowid "
                "WHERE knowledge_fts MATCH ? "
                "ORDER BY rank LIMIT ?",
                (query, limit),
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def list_knowledge(
        self,
        category: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List knowledge entries, optionally filtered by category."""
        assert self._db is not None
        await self._ensure_knowledge_table()

        if category:
            cursor = await self._db.execute(
                "SELECT id, content, source, category, metadata, created_at "
                "FROM knowledge WHERE category = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (category, limit),
            )
        else:
            cursor = await self._db.execute(
                "SELECT id, content, source, category, metadata, created_at "
                "FROM knowledge ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def delete_knowledge(self, entry_id: str) -> bool:
        """Delete a knowledge entry by ID. Returns True if found."""
        assert self._db is not None
        await self._ensure_knowledge_table()

        cursor = await self._db.execute(
            "DELETE FROM knowledge WHERE id = ?",
            (entry_id,),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    # ----- Cleanup -----

    async def close(self) -> None:
        db = self._db
        if db is None:
            return
        worker = getattr(db, "_thread", db)
        await db.close()
        # aiosqlite resolves its stop future before the worker executes its
        # final loop break. Join off-loop so callers can rely on close()
        # having actually stopped the SQLite thread when it returns.
        await asyncio.to_thread(worker.join)
        self._db = None
