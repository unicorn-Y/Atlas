"""Atlas Memory Store — SQLite + FTS5 based conversation and memory storage."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite
import structlog

from atlas.config import get_config

log = structlog.get_logger()


class MemoryStore:
    """SQLite + FTS5 memory system.

    Handles:
    - Conversation history (messages per conversation)
    - Key-value facts (user preferences, project info)
    - Full-text search across all stored content

    Designed with a clean interface so the backing store
    can be swapped to a stronger memory system later.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or get_config().db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        """Initialize database and create tables."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self._db_path))
        self._db.row_factory = aiosqlite.Row
        await self._create_tables()
        log.info("memory.init", db=str(self._db_path))

    async def _create_tables(self) -> None:
        assert self._db is not None
        await self._db.executescript("""
            -- Conversations
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT 'New Conversation',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                metadata TEXT DEFAULT '{}'
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

            -- Full-text search on messages
            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                content,
                content=messages,
                content_rowid=rowid
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

            -- Key-value facts (user prefs, project info, etc.)
            CREATE TABLE IF NOT EXISTS facts (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'general',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
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

    async def list_conversations(self, limit: int = 50) -> list[dict[str, Any]]:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT id, title, created_at, updated_at FROM conversations "
            "ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_conversation_messages(
        self, conversation_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT id, role, content, metadata, created_at FROM messages "
            "WHERE conversation_id = ? ORDER BY created_at ASC LIMIT ?",
            (conversation_id, limit),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

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

    # ----- Search -----

    async def search(
        self, query: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Full-text search across all messages."""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT m.id, m.conversation_id, m.role, m.content, m.created_at, "
            "       highlight(messages_fts, 0, '<b>', '</b>') AS snippet "
            "FROM messages_fts "
            "JOIN messages m ON messages_fts.rowid = m.rowid "
            "WHERE messages_fts MATCH ? "
            "ORDER BY rank LIMIT ?",
            (query, limit),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ----- Facts -----

    async def set_fact(self, key: str, value: str, category: str = "general") -> None:
        assert self._db is not None
        await self._db.execute(
            "INSERT INTO facts (key, value, category) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
            "updated_at=datetime('now')",
            (key, value, category),
        )
        await self._db.commit()

    async def get_fact(self, key: str) -> str | None:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT value FROM facts WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        return row["value"] if row else None

    async def list_facts(self, category: str | None = None) -> list[dict[str, Any]]:
        assert self._db is not None
        if category:
            cursor = await self._db.execute(
                "SELECT key, value, category, updated_at FROM facts "
                "WHERE category = ? ORDER BY updated_at DESC",
                (category,),
            )
        else:
            cursor = await self._db.execute(
                "SELECT key, value, category, updated_at FROM facts "
                "ORDER BY updated_at DESC"
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ----- Conversation management -----

    async def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        """Return a single conversation by ID, or None."""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT id, title, created_at, updated_at, metadata "
            "FROM conversations WHERE id = ?",
            (conversation_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def update_conversation_title(
        self, conversation_id: str, title: str
    ) -> bool:
        """Update a conversation's title. Returns True if found."""
        assert self._db is not None
        cursor = await self._db.execute(
            "UPDATE conversations SET title = ?, updated_at = datetime('now') "
            "WHERE id = ?",
            (title, conversation_id),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation and all its messages. Returns True if found."""
        assert self._db is not None
        # Delete messages first (triggers clean up FTS)
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

    async def delete_fact(self, key: str) -> bool:
        """Delete a fact by key. Returns True if found."""
        assert self._db is not None
        cursor = await self._db.execute(
            "DELETE FROM facts WHERE key = ?",
            (key,),
        )
        await self._db.commit()
        return cursor.rowcount > 0

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
        if self._db:
            await self._db.close()
            self._db = None
