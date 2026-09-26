"""Atlas Memory Store — SQLite + FTS5 based conversation and memory storage."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite
import structlog

from atlas.config import get_config
from atlas.memory.quality import evaluate_memory_health

log = structlog.get_logger()

_MEMORY_LINE = re.compile(
    r"^\s*(?:remember|记住)\s*[:：]\s*"
    r"(?P<key>[\w.-]{1,64})\s*[=＝]\s*(?P<value>\S(?:.*\S)?)\s*$",
    re.IGNORECASE,
)
_MEMORY_TOKEN = re.compile(r"[\w.-]+", re.UNICODE)
_MEMORY_STOP_WORDS = {
    "a", "an", "and", "are", "be", "do", "does", "for", "how", "i",
    "in", "is", "it", "me", "my", "of", "on", "or", "should", "the",
    "to", "use", "what", "when", "where", "which", "who", "why", "with",
}
_UNCERTAIN_MEMORY = re.compile(
    r"\b(?:might|maybe|perhaps|possibly|probably|i think|not sure|guess|hypothetically)\b"
    r"|(?:可能|也许|或许|大概|我猜|不确定|假设)",
    re.IGNORECASE,
)
_SENSITIVE_MEMORY = re.compile(
    r"\b(?:api\s*key|access\s*token|password|passwd|secret|credential|private\s*key)\b"
    r"|(?:密钥|密码|令牌|凭据|私钥)",
    re.IGNORECASE,
)
_AUTO_MEMORY_PATTERNS = (
    (
        re.compile(r"^(?:I prefer|I like|I usually use|I always use)\s+(.+)$", re.I),
        "user_preference",
        "preference",
    ),
    (re.compile(r"^My (timezone|time zone|language|name|role) is\s+(.+)$", re.I), None, "personal"),
    (
        re.compile(r"^(?:Our|This) project (?:uses|is built with|runs on)\s+(.+)$", re.I),
        "project_stack",
        "project",
    ),
    (
        re.compile(r"^(?:We|Our team) decided to use\s+(.+)$", re.I),
        "project_decision",
        "decision",
    ),
    (
        re.compile(r"^我(?:更)?(?:喜欢|偏好|习惯使用|通常使用|始终使用)\s*(.+)$"),
        "user_preference",
        "preference",
    ),
    (re.compile(r"^我的(时区|语言|姓名|名字|角色)是\s*(.+)$"), None, "personal"),
    (re.compile(r"^(?:我们的|这个)项目(?:使用|采用|基于)\s*(.+)$"), "project_stack", "project"),
    (re.compile(r"^(?:我们|团队)决定(?:使用|采用)\s*(.+)$"), "project_decision", "decision"),
    (re.compile(r"^(?:I commit to|I promise to)\s+(.+)$", re.I), "user_commitment", "commitment"),
    (re.compile(r"^我(?:承诺|保证)\s*(.+)$"), "user_commitment", "commitment"),
)
_PERSONAL_KEYS = {
    "timezone": "user_timezone", "time zone": "user_timezone",
    "language": "user_language", "name": "user_name", "role": "user_role",
    "时区": "user_timezone", "语言": "user_language", "姓名": "user_name",
    "名字": "user_name", "角色": "user_role",
}


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
                source_conversation_id TEXT,
                source_message_id TEXT,
                confidence REAL NOT NULL DEFAULT 1.0,
                memory_type TEXT NOT NULL DEFAULT 'fact'
                    CHECK(memory_type IN ('fact', 'identity', 'commitment')),
                commitment_status TEXT
                    CHECK(commitment_status IS NULL OR commitment_status IN ('active', 'fulfilled', 'cancelled')),
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            -- Automatically extracted memories remain pending until approved.
            CREATE TABLE IF NOT EXISTS memory_candidates (
                id TEXT PRIMARY KEY,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                category TEXT NOT NULL,
                confidence REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'approved', 'rejected', 'superseded')),
                memory_type TEXT NOT NULL DEFAULT 'fact'
                    CHECK(memory_type IN ('fact', 'identity', 'commitment')),
                source_conversation_id TEXT NOT NULL,
                source_message_id TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(source_message_id, key, value)
            );

            CREATE TABLE IF NOT EXISTS memory_fact_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                category TEXT NOT NULL,
                confidence REAL NOT NULL,
                source_conversation_id TEXT,
                source_message_id TEXT,
                event_type TEXT NOT NULL CHECK(event_type IN ('superseded', 'duplicate')),
                candidate_id TEXT,
                recorded_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS memory_commitment_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL,
                previous_status TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('active', 'fulfilled', 'cancelled')),
                source_message_id TEXT NOT NULL,
                recorded_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS memory_usage_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_key TEXT NOT NULL,
                outcome TEXT NOT NULL CHECK(outcome IN ('used', 'not_used', 'helpful', 'unhelpful')),
                conversation_id TEXT,
                recorded_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS memory_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_key TEXT NOT NULL,
                signal TEXT NOT NULL CHECK(signal IN ('correction', 'rejected')),
                candidate_id TEXT,
                source_message_id TEXT,
                recorded_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS memory_evaluations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_key TEXT NOT NULL,
                rating TEXT NOT NULL CHECK(rating IN ('useful', 'not_useful', 'uncertain')),
                recorded_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """)
        cursor = await self._db.execute("PRAGMA table_info(facts)")
        fact_columns = {row["name"] for row in await cursor.fetchall()}
        if "source_conversation_id" not in fact_columns:
            await self._db.execute(
                "ALTER TABLE facts ADD COLUMN source_conversation_id TEXT"
            )
        if "source_message_id" not in fact_columns:
            await self._db.execute("ALTER TABLE facts ADD COLUMN source_message_id TEXT")
        if "confidence" not in fact_columns:
            await self._db.execute(
                "ALTER TABLE facts ADD COLUMN confidence REAL NOT NULL DEFAULT 1.0"
            )
        if "memory_type" not in fact_columns:
            await self._db.execute(
                "ALTER TABLE facts ADD COLUMN memory_type TEXT NOT NULL DEFAULT 'fact'"
            )
        if "commitment_status" not in fact_columns:
            await self._db.execute("ALTER TABLE facts ADD COLUMN commitment_status TEXT")
        await self._db.execute(
            "UPDATE facts SET memory_type = 'identity' "
            "WHERE category = 'personal' AND memory_type = 'fact'"
        )
        cursor = await self._db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='memory_candidates'"
        )
        candidate_sql = (await cursor.fetchone())["sql"] or ""
        if "'superseded'" not in candidate_sql:
            await self._db.executescript("""
                ALTER TABLE memory_candidates RENAME TO memory_candidates_legacy;
                CREATE TABLE memory_candidates (
                    id TEXT PRIMARY KEY,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    category TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending', 'approved', 'rejected', 'superseded')),
                    memory_type TEXT NOT NULL DEFAULT 'fact'
                        CHECK(memory_type IN ('fact', 'identity', 'commitment')),
                    source_conversation_id TEXT NOT NULL,
                    source_message_id TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                    UNIQUE(source_message_id, key, value)
                );
                INSERT INTO memory_candidates
                    (id, key, value, category, confidence, status,
                     source_conversation_id, source_message_id, created_at, updated_at)
                SELECT id, key, value, category, confidence, status,
                       source_conversation_id, source_message_id, created_at, updated_at
                FROM memory_candidates_legacy;
                DROP TABLE memory_candidates_legacy;
            """)
        cursor = await self._db.execute("PRAGMA table_info(memory_candidates)")
        candidate_columns = {row["name"] for row in await cursor.fetchall()}
        if "memory_type" not in candidate_columns:
            await self._db.execute(
                "ALTER TABLE memory_candidates ADD COLUMN memory_type TEXT NOT NULL DEFAULT 'fact'"
            )
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
            "SELECT id, role, content, created_at FROM messages "
            "WHERE conversation_id = ? ORDER BY created_at ASC, rowid ASC LIMIT ?",
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

    async def set_fact(
        self,
        key: str,
        value: str,
        category: str = "general",
        source_conversation_id: str | None = None,
        source_message_id: str | None = None,
        confidence: float = 1.0,
        memory_type: str = "fact",
    ) -> None:
        if memory_type not in {"fact", "identity", "commitment"}:
            raise ValueError("Unsupported memory type")
        assert self._db is not None
        await self._db.execute(
            "INSERT INTO facts (key, value, category, source_conversation_id, "
            "source_message_id, confidence, memory_type, commitment_status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
            "category=excluded.category, "
            "source_conversation_id=COALESCE(excluded.source_conversation_id, "
            "facts.source_conversation_id), "
            "source_message_id=excluded.source_message_id, "
            "confidence=excluded.confidence, "
            "memory_type=excluded.memory_type, "
            "commitment_status=CASE WHEN excluded.memory_type = 'commitment' "
            "THEN COALESCE(facts.commitment_status, 'active') ELSE NULL END, "
            "updated_at=datetime('now')",
            (key, value, category, source_conversation_id, source_message_id,
             confidence, memory_type, "active" if memory_type == "commitment" else None),
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
                "SELECT key, value, category, source_conversation_id, source_message_id, "
                "confidence, memory_type, commitment_status, updated_at FROM facts "
                "WHERE category = ? ORDER BY updated_at DESC",
                (category,),
            )
        else:
            cursor = await self._db.execute(
                "SELECT key, value, category, source_conversation_id, source_message_id, "
                "confidence, memory_type, commitment_status, updated_at FROM facts "
                "ORDER BY updated_at DESC"
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def extract_memories(
        self, conversation_id: str, content: str
    ) -> list[dict[str, str]]:
        """Persist explicitly marked ``remember: key = value`` lines as facts."""
        extracted: list[dict[str, str]] = []
        for line in content.splitlines():
            match = _MEMORY_LINE.match(line)
            if not match:
                continue
            key = match.group("key").strip().lower()
            value = match.group("value").strip()
            if len(value) > 500:
                continue
            await self.set_fact(
                key,
                value,
                category="extracted",
                source_conversation_id=conversation_id,
            )
            extracted.append({
                "key": key,
                "value": value,
                "category": "extracted",
                "source_conversation_id": conversation_id,
            })
        return extracted

    async def extract_conversation_candidates(
        self, conversation_id: str
    ) -> list[dict[str, Any]]:
        """Extract conservative user-stated memories into a review queue."""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT id, role, content FROM messages WHERE conversation_id = ? "
            "ORDER BY created_at ASC, rowid ASC",
            (conversation_id,),
        )
        messages = await cursor.fetchall()
        for message in messages:
            if message["role"] != "user":
                continue
            text = message["content"].strip()
            if not text or "?" in text or "？" in text or _UNCERTAIN_MEMORY.search(text):
                continue
            if _SENSITIVE_MEMORY.search(text):
                continue
            for line in text.splitlines():
                line = line.strip()
                for pattern, fixed_key, category in _AUTO_MEMORY_PATTERNS:
                    match = pattern.fullmatch(line.rstrip(".!。"))
                    if not match:
                        continue
                    groups = match.groups()
                    if fixed_key is None:
                        key = _PERSONAL_KEYS.get(groups[0].casefold())
                        value = groups[1].strip()
                    else:
                        key = fixed_key
                        value = groups[0].strip()
                    memory_type = (
                        "identity" if category == "personal"
                        else "commitment" if category == "commitment"
                        else "fact"
                    )
                    if memory_type == "commitment":
                        key = f"user_commitment_{message['id'].replace('-', '')[:16]}"
                    value = value.rstrip(".!。 ")
                    if not key or not 2 <= len(value) <= 160:
                        continue
                    if (
                        _SENSITIVE_MEMORY.search(value)
                        or _UNCERTAIN_MEMORY.search(value)
                    ):
                        continue
                    await self._db.execute(
                        "INSERT OR IGNORE INTO memory_candidates "
                        "(id, key, value, category, confidence, memory_type, "
                        "source_conversation_id, source_message_id) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            str(uuid.uuid4()), key, value, category, 0.9, memory_type,
                            conversation_id, message["id"],
                        ),
                    )
                    break
        await self._db.commit()
        return await self.list_memory_candidates(
            status="pending", source_conversation_id=conversation_id
        )

    async def list_memory_candidates(
        self, status: str | None = None,
        source_conversation_id: str | None = None,
    ) -> list[dict[str, Any]]:
        assert self._db is not None
        clauses: list[str] = []
        params: list[str] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if source_conversation_id:
            clauses.append("source_conversation_id = ?")
            params.append(source_conversation_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        cursor = await self._db.execute(
            "SELECT id, key, value, category, confidence, status, memory_type, "
            "source_conversation_id, source_message_id, created_at, updated_at "
            "FROM memory_candidates" + where + " ORDER BY created_at, rowid",
            params,
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def promote_memory_candidate(self, candidate_id: str) -> bool:
        assert self._db is not None
        await self._db.execute("BEGIN IMMEDIATE")
        cursor = await self._db.execute(
            "SELECT key, value, category, confidence, memory_type, source_conversation_id, source_message_id "
            "FROM memory_candidates WHERE id = ? AND status = 'pending'",
            (candidate_id,),
        )
        candidate = await cursor.fetchone()
        if not candidate:
            await self._db.rollback()
            return False
        cursor = await self._db.execute(
            "SELECT 1 FROM messages WHERE id = ? AND conversation_id = ? AND role = 'user'",
            (candidate["source_message_id"], candidate["source_conversation_id"]),
        )
        if not await cursor.fetchone():
            await self._db.rollback()
            return False
        cursor = await self._db.execute(
            "SELECT key, value, category, confidence, memory_type, commitment_status, "
            "source_conversation_id, source_message_id, updated_at FROM facts WHERE key = ?",
            (candidate["key"],),
        )
        current = await cursor.fetchone()
        if current and current["value"] == candidate["value"]:
            await self._db.execute(
                "INSERT INTO memory_fact_history "
                "(key, value, category, confidence, source_conversation_id, "
                "source_message_id, event_type, candidate_id) "
                "VALUES (?, ?, ?, ?, ?, ?, 'duplicate', ?)",
                (current["key"], current["value"], current["category"],
                 current["confidence"], current["source_conversation_id"],
                 current["source_message_id"], candidate_id),
            )
            await self._db.execute(
                "UPDATE memory_candidates SET status = 'approved', updated_at = datetime('now') "
                "WHERE id = ?", (candidate_id,),
            )
            await self._db.commit()
            return True
        if current:
            cursor = await self._db.execute(
                "SELECT created_at FROM messages WHERE id = ?",
                (candidate["source_message_id"],),
            )
            candidate_message = await cursor.fetchone()
            cursor = await self._db.execute(
                "SELECT created_at FROM messages WHERE id = ?",
                (current["source_message_id"],),
            )
            current_message = await cursor.fetchone()
            candidate_time = (
                candidate_message["created_at"] if candidate_message else None
            )
            current_time = (
                current_message["created_at"] if current_message else current["updated_at"]
            )
            if candidate_time and current_time and candidate_time < current_time:
                await self._db.execute(
                    "UPDATE memory_candidates SET status = 'superseded', "
                    "updated_at = datetime('now') WHERE id = ?",
                    (candidate_id,),
                )
                await self._db.commit()
                return False
            await self._db.execute(
                "INSERT INTO memory_fact_history "
                "(key, value, category, confidence, source_conversation_id, "
                "source_message_id, event_type, candidate_id) "
                "VALUES (?, ?, ?, ?, ?, ?, 'superseded', ?)",
                (current["key"], current["value"], current["category"],
                 current["confidence"], current["source_conversation_id"],
                 current["source_message_id"], candidate_id),
            )
        await self._db.execute(
            "INSERT INTO facts (key, value, category, source_conversation_id, "
            "source_message_id, confidence, memory_type, commitment_status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
            "category=excluded.category, "
            "source_conversation_id=COALESCE(excluded.source_conversation_id, "
            "facts.source_conversation_id), "
            "source_message_id=excluded.source_message_id, confidence=excluded.confidence, "
            "memory_type=excluded.memory_type, "
            "commitment_status=CASE WHEN excluded.memory_type = 'commitment' "
            "THEN COALESCE(facts.commitment_status, 'active') ELSE NULL END, "
            "updated_at=datetime('now')",
            (candidate["key"], candidate["value"], candidate["category"],
             candidate["source_conversation_id"], candidate["source_message_id"],
             candidate["confidence"], candidate["memory_type"],
             "active" if candidate["memory_type"] == "commitment" else None),
        )
        await self._db.execute(
            "UPDATE memory_candidates SET status = 'approved', updated_at = datetime('now') "
            "WHERE id = ? AND status = 'pending'", (candidate_id,),
        )
        await self._db.commit()
        return True

    async def list_memory_conflicts(self) -> list[dict[str, Any]]:
        """Return pending candidates whose values disagree with the current fact."""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT c.id AS candidate_id, c.key, c.value AS candidate_value, "
            "c.confidence AS candidate_confidence, c.source_conversation_id "
            "AS candidate_source_conversation_id, c.source_message_id "
            "AS candidate_source_message_id, f.value AS current_value, "
            "f.confidence AS current_confidence, f.source_conversation_id "
            "AS current_source_conversation_id, f.source_message_id "
            "AS current_source_message_id FROM memory_candidates c "
            "JOIN facts f ON f.key = c.key WHERE c.status = 'pending' "
            "AND c.value <> f.value ORDER BY c.created_at, c.rowid"
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def list_memory_fact_history(self, key: str) -> list[dict[str, Any]]:
        """Return superseded fact versions and duplicate consolidation records."""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT key, value, category, confidence, source_conversation_id, "
            "source_message_id, event_type, candidate_id, recorded_at "
            "FROM memory_fact_history WHERE key = ? ORDER BY id", (key,)
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def reject_memory_candidate(self, candidate_id: str) -> bool:
        assert self._db is not None
        await self._db.execute("BEGIN IMMEDIATE")
        cursor = await self._db.execute(
            "SELECT key FROM memory_candidates WHERE id = ? AND status = 'pending'",
            (candidate_id,),
        )
        candidate = await cursor.fetchone()
        if not candidate:
            await self._db.rollback()
            return False
        await self._db.execute(
            "UPDATE memory_candidates SET status = 'rejected', updated_at = datetime('now') "
            "WHERE id = ? AND status = 'pending'", (candidate_id,),
        )
        await self._db.execute(
            "INSERT INTO memory_feedback (memory_key, signal, candidate_id) "
            "VALUES (?, 'rejected', ?)", (candidate["key"], candidate_id),
        )
        await self._db.commit()
        return True

    async def record_memory_usage(
        self, key: str, outcome: str, conversation_id: str | None = None,
    ) -> int:
        """Persist how an active memory affected a conversation."""
        if _SENSITIVE_MEMORY.search(key):
            raise ValueError("Sensitive memories cannot be recorded as feedback")
        if outcome not in {"used", "not_used", "helpful", "unhelpful"}:
            raise ValueError("Unsupported memory usage outcome")
        assert self._db is not None
        cursor = await self._db.execute("SELECT 1 FROM facts WHERE key = ?", (key,))
        if not await cursor.fetchone():
            raise ValueError("Cannot record usage for an unknown memory")
        cursor = await self._db.execute(
            "INSERT INTO memory_usage_events (memory_key, outcome, conversation_id) "
            "VALUES (?, ?, ?)", (key, outcome, conversation_id),
        )
        await self._db.commit()
        return int(cursor.lastrowid)

    async def record_memory_correction(
        self, key: str, source_message_id: str | None = None,
    ) -> int:
        """Record a user correction without changing or promoting a memory."""
        if _SENSITIVE_MEMORY.search(key):
            raise ValueError("Sensitive memories cannot be recorded as feedback")
        assert self._db is not None
        cursor = await self._db.execute("SELECT 1 FROM facts WHERE key = ?", (key,))
        if not await cursor.fetchone():
            raise ValueError("Cannot correct an unknown memory")
        if source_message_id:
            cursor = await self._db.execute(
                "SELECT 1 FROM messages WHERE id = ? AND role = 'user'",
                (source_message_id,),
            )
            if not await cursor.fetchone():
                raise ValueError("Correction evidence must be a user message")
        cursor = await self._db.execute(
            "INSERT INTO memory_feedback (memory_key, signal, source_message_id) "
            "VALUES (?, 'correction', ?)", (key, source_message_id),
        )
        await self._db.commit()
        return int(cursor.lastrowid)

    async def record_memory_evaluation(self, key: str, rating: str) -> int:
        """Persist an explicit usefulness evaluation for an active memory."""
        if _SENSITIVE_MEMORY.search(key):
            raise ValueError("Sensitive memories cannot be recorded as feedback")
        if rating not in {"useful", "not_useful", "uncertain"}:
            raise ValueError("Unsupported memory usefulness rating")
        assert self._db is not None
        cursor = await self._db.execute("SELECT 1 FROM facts WHERE key = ?", (key,))
        if not await cursor.fetchone():
            raise ValueError("Cannot evaluate an unknown memory")
        cursor = await self._db.execute(
            "INSERT INTO memory_evaluations (memory_key, rating) VALUES (?, ?)",
            (key, rating),
        )
        await self._db.commit()
        return int(cursor.lastrowid)

    async def get_memory_quality(self, key: str) -> dict[str, int]:
        """Return durable outcome, feedback, and evaluation counts for a memory."""
        assert self._db is not None
        usage = await self._db.execute(
            "SELECT outcome, COUNT(*) AS count FROM memory_usage_events "
            "WHERE memory_key = ? GROUP BY outcome", (key,),
        )
        feedback = await self._db.execute(
            "SELECT signal, COUNT(*) AS count FROM memory_feedback "
            "WHERE memory_key = ? GROUP BY signal", (key,),
        )
        evaluations = await self._db.execute(
            "SELECT rating, COUNT(*) AS count FROM memory_evaluations "
            "WHERE memory_key = ? GROUP BY rating", (key,),
        )
        result = {
            "used_count": 0, "not_used_count": 0, "helpful_count": 0,
            "unhelpful_count": 0, "correction_count": 0, "rejected_count": 0,
            "useful_count": 0, "not_useful_count": 0, "uncertain_count": 0,
        }
        for row in await usage.fetchall():
            result[f"{row['outcome']}_count"] = row["count"]
        for row in await feedback.fetchall():
            result[f"{row['signal']}_count"] = row["count"]
        for row in await evaluations.fetchall():
            result[f"{row['rating']}_count"] = row["count"]
        return result

    async def list_memory_usage(self, key: str) -> list[dict[str, Any]]:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT memory_key, outcome, conversation_id, recorded_at "
            "FROM memory_usage_events WHERE memory_key = ? ORDER BY id", (key,),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def list_memory_feedback(self, key: str) -> list[dict[str, Any]]:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT memory_key, signal, candidate_id, source_message_id, recorded_at "
            "FROM memory_feedback WHERE memory_key = ? ORDER BY id", (key,),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def list_memory_evaluations(self, key: str) -> list[dict[str, Any]]:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT memory_key, rating, recorded_at FROM memory_evaluations "
            "WHERE memory_key = ? ORDER BY id", (key,),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def get_memory_health(
        self,
        *,
        stale_after_days: int = 180,
        window_days: int = 90,
        as_of: datetime | None = None,
    ) -> dict[str, Any]:
        """Aggregate durable feedback and return advisory review flags."""
        if stale_after_days < 0 or window_days < 0:
            raise ValueError("Memory health windows must be non-negative")
        assert self._db is not None
        now = as_of or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        now = now.astimezone(timezone.utc)
        now_text = now.strftime("%Y-%m-%d %H:%M:%S")
        cutoff_modifier = f"-{window_days} days"
        cursor = await self._db.execute(
            "SELECT f.key, f.memory_type, f.updated_at, "
            "(SELECT COUNT(*) FROM memory_usage_events u WHERE u.memory_key=f.key AND u.outcome='used') AS used_count, "
            "(SELECT COUNT(*) FROM memory_usage_events u WHERE u.memory_key=f.key AND u.outcome='not_used') AS not_used_count, "
            "(SELECT COUNT(*) FROM memory_usage_events u WHERE u.memory_key=f.key AND u.outcome='helpful') AS helpful_count, "
            "(SELECT COUNT(*) FROM memory_usage_events u WHERE u.memory_key=f.key AND u.outcome='unhelpful') AS unhelpful_count, "
            "(SELECT COUNT(*) FROM memory_feedback b WHERE b.memory_key=f.key AND b.signal='correction') AS correction_count, "
            "(SELECT COUNT(*) FROM memory_feedback b WHERE b.memory_key=f.key AND b.signal='rejected') AS rejected_count, "
            "(SELECT COUNT(*) FROM memory_evaluations e WHERE e.memory_key=f.key AND e.rating='useful') AS useful_count, "
            "(SELECT COUNT(*) FROM memory_evaluations e WHERE e.memory_key=f.key AND e.rating='not_useful') AS not_useful_count, "
            "(SELECT COUNT(*) FROM memory_evaluations e WHERE e.memory_key=f.key AND e.rating='uncertain') AS uncertain_count, "
            "((SELECT COUNT(*) FROM memory_usage_events u WHERE u.memory_key=f.key AND u.recorded_at >= datetime(?, ?)) + "
            " (SELECT COUNT(*) FROM memory_feedback b WHERE b.memory_key=f.key AND b.recorded_at >= datetime(?, ?)) + "
            " (SELECT COUNT(*) FROM memory_evaluations e WHERE e.memory_key=f.key AND e.recorded_at >= datetime(?, ?))) AS recent_signal_count "
            "FROM facts f ORDER BY f.key",
            (now_text, cutoff_modifier, now_text, cutoff_modifier,
             now_text, cutoff_modifier),
        )
        memories = [dict(row) for row in await cursor.fetchall()]
        return evaluate_memory_health(
            memories,
            stale_after_days=stale_after_days,
            window_days=window_days,
            as_of=now,
        )

    async def get_agent_context(
        self, query: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Return query-relevant validated facts for the current agent request."""
        return await self.get_active_context(query, limit=limit)

    async def get_active_context(
        self, query: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Assemble bounded, deterministic context from validated facts only.

        Pending candidates are deliberately excluded: only facts written directly
        by an explicit remember request or promoted through approval enter context.
        """
        facts = await self.list_facts()
        terms = {
            token.casefold()
            for token in _MEMORY_TOKEN.findall(query)
            if len(token) > 1 and token.casefold() not in _MEMORY_STOP_WORDS
        }
        if not terms:
            return []
        ranked: list[tuple[int, dict[str, Any]]] = []
        for fact in facts:
            if fact["memory_type"] in {"identity", "commitment"}:
                if not await self._has_approved_user_evidence(
                    fact, fact["memory_type"]
                ):
                    continue
            if fact["memory_type"] == "commitment":
                if fact["commitment_status"] != "active":
                    continue
            key = fact["key"].casefold()
            key_terms = {token for token in re.split(r"[\W_]+", key) if token}
            value_terms = {token.casefold() for token in _MEMORY_TOKEN.findall(fact["value"])}
            score = sum(
                4 if term in key_terms else 1 if term in value_terms else 0
                for term in terms
            )
            if score:
                ranked.append((score, fact))

        ranked.sort(key=lambda item: item[1]["key"])
        ranked.sort(key=lambda item: item[1]["updated_at"], reverse=True)
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [fact for _, fact in ranked[: max(0, limit)]]

    async def _has_approved_user_evidence(
        self, fact: dict[str, Any], memory_type: str
    ) -> bool:
        """Require an approved candidate and its original user message for durable recall."""
        assert self._db is not None
        source_message_id = fact.get("source_message_id")
        source_conversation_id = fact.get("source_conversation_id")
        if not source_message_id or not source_conversation_id:
            return False
        cursor = await self._db.execute(
            "SELECT 1 FROM messages WHERE id = ? AND conversation_id = ? AND role = 'user'",
            (source_message_id, source_conversation_id),
        )
        if not await cursor.fetchone():
            return False
        cursor = await self._db.execute(
            "SELECT 1 FROM memory_candidates WHERE key = ? AND value = ? "
            "AND memory_type = ? AND status = 'approved' "
            "AND source_message_id = ? AND source_conversation_id = ?",
            (fact["key"], fact["value"], memory_type,
             source_message_id, source_conversation_id),
        )
        return await cursor.fetchone() is not None

    async def set_commitment_status(
        self, key: str, status: str, source_message_id: str
    ) -> bool:
        """Change an approved commitment lifecycle with a user message as evidence."""
        if status not in {"active", "fulfilled", "cancelled"}:
            raise ValueError("Unsupported commitment status")
        assert self._db is not None
        await self._db.execute("BEGIN IMMEDIATE")
        cursor = await self._db.execute(
            "SELECT commitment_status FROM facts WHERE key = ? AND memory_type = 'commitment'",
            (key,),
        )
        fact = await cursor.fetchone()
        if not fact:
            await self._db.rollback()
            return False
        cursor = await self._db.execute(
            "SELECT 1 FROM messages WHERE id = ? AND role = 'user'", (source_message_id,)
        )
        if not await cursor.fetchone():
            await self._db.rollback()
            return False
        previous_status = fact["commitment_status"] or "active"
        if previous_status == status:
            await self._db.rollback()
            return False
        await self._db.execute(
            "UPDATE facts SET commitment_status = ?, updated_at = datetime('now') "
            "WHERE key = ? AND memory_type = 'commitment'",
            (status, key),
        )
        await self._db.execute(
            "INSERT INTO memory_commitment_history "
            "(key, previous_status, status, source_message_id) VALUES (?, ?, ?, ?)",
            (key, previous_status, status, source_message_id),
        )
        await self._db.commit()
        return True

    async def list_commitment_history(self, key: str) -> list[dict[str, Any]]:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT key, previous_status, status, source_message_id, recorded_at "
            "FROM memory_commitment_history WHERE key = ? ORDER BY id", (key,)
        )
        return [dict(row) for row in await cursor.fetchall()]

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
