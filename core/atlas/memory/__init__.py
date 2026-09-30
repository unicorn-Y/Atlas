"""Atlas Memory Store — SQLite + FTS5 based conversation and memory storage."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite
import structlog

from atlas.config import get_config
from atlas.memory.quality import (
    evaluate_consolidated_knowledge_insights,
    evaluate_knowledge_consolidation_proposals,
    evaluate_knowledge_health,
    evaluate_knowledge_maturity,
    evaluate_knowledge_optimization_candidate,
    evaluate_knowledge_optimization_candidates,
    evaluate_knowledge_self_steering,
    evaluate_memory_health,
    evaluate_memory_optimization,
)

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
_GOAL_KNOWLEDGE_REFINEMENT_MIN_CANDIDATES = 2
_REFLECTION_SECRET = re.compile(
    r"(?i)\b(api[_ -]?key|access[_ -]?token|password|passwd|secret|credential)\b"
    r"\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
    r"|\bBearer\s+[^\s,;]+|\bsk-[A-Za-z0-9_-]{12,}"
)
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
        await self._db.execute("PRAGMA foreign_keys = ON")
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
                metadata TEXT DEFAULT '{}',
                pinned INTEGER NOT NULL DEFAULT 0,
                archived INTEGER NOT NULL DEFAULT 0,
                workspace TEXT
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

            CREATE TABLE IF NOT EXISTS memory_optimization_reports (
                id TEXT PRIMARY KEY,
                report_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS memory_maturity_reports (
                id TEXT PRIMARY KEY,
                report_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS memory_self_steering_reports (
                id TEXT PRIMARY KEY,
                report_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                reviewed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS memory_optimization_candidates (
                id TEXT PRIMARY KEY,
                source_report_id TEXT NOT NULL,
                candidate_json TEXT NOT NULL,
                evaluation_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'approved', 'rejected')),
                reviewed_at TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(source_report_id) REFERENCES memory_self_steering_reports(id)
            );

            CREATE TABLE IF NOT EXISTS memory_optimization_candidate_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id TEXT NOT NULL,
                decision TEXT NOT NULL CHECK(decision IN ('approved', 'rejected')),
                reviewed_at TEXT NOT NULL,
                FOREIGN KEY(candidate_id) REFERENCES memory_optimization_candidates(id)
            );

            CREATE TABLE IF NOT EXISTS memory_consolidation_proposals (
                id TEXT PRIMARY KEY,
                proposal_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'approved', 'rejected')),
                reviewed_at TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS memory_consolidation_proposal_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                proposal_id TEXT NOT NULL,
                decision TEXT NOT NULL CHECK(decision IN ('approved', 'rejected')),
                reviewed_at TEXT NOT NULL,
                FOREIGN KEY(proposal_id) REFERENCES memory_consolidation_proposals(id)
            );

            CREATE TABLE IF NOT EXISTS memory_knowledge_activations (
                id TEXT PRIMARY KEY,
                proposal_id TEXT NOT NULL UNIQUE,
                activation_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(proposal_id) REFERENCES memory_consolidation_proposals(id)
            );

            CREATE TABLE IF NOT EXISTS memory_knowledge_activation_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                activation_id TEXT NOT NULL,
                event TEXT NOT NULL CHECK(event IN ('activated')),
                created_at TEXT NOT NULL,
                FOREIGN KEY(activation_id) REFERENCES memory_knowledge_activations(id)
            );

            CREATE TABLE IF NOT EXISTS memory_knowledge_verifications (
                id TEXT PRIMARY KEY,
                activation_id TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('verified', 'unverified')),
                verification_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(activation_id) REFERENCES memory_knowledge_activations(id)
            );

            CREATE INDEX IF NOT EXISTS idx_memory_knowledge_verifications_activation
                ON memory_knowledge_verifications(activation_id, created_at);

            CREATE TABLE IF NOT EXISTS memory_knowledge_verification_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                verification_id TEXT NOT NULL,
                event TEXT NOT NULL CHECK(event IN ('verification_recorded')),
                created_at TEXT NOT NULL,
                FOREIGN KEY(verification_id) REFERENCES memory_knowledge_verifications(id)
            );

            CREATE TABLE IF NOT EXISTS memory_knowledge_health_reports (
                id TEXT PRIMARY KEY,
                report_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS memory_knowledge_health_report_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id TEXT NOT NULL,
                decision TEXT NOT NULL CHECK(decision IN ('approved', 'rejected')),
                reviewed_at TEXT NOT NULL,
                FOREIGN KEY(report_id) REFERENCES memory_knowledge_health_reports(id)
            );

            CREATE TABLE IF NOT EXISTS memory_knowledge_consolidated_insights (
                id TEXT PRIMARY KEY,
                insight_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS memory_knowledge_insight_applications (
                id TEXT PRIMARY KEY,
                application_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS agent_reflections (
                id TEXT PRIMARY KEY,
                category TEXT NOT NULL CHECK(category IN ('tool', 'model', 'runtime')),
                component TEXT NOT NULL,
                summary TEXT NOT NULL,
                resolution_hint TEXT NOT NULL,
                source_conversation_id TEXT NOT NULL,
                source_run_id TEXT,
                model TEXT,
                recovered INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_agent_reflections_run
                ON agent_reflections(source_run_id, recovered);

            CREATE TABLE IF NOT EXISTS goal_outcomes (
                id TEXT PRIMARY KEY,
                goal_id TEXT NOT NULL,
                goal TEXT NOT NULL,
                status TEXT NOT NULL,
                evaluation_json TEXT NOT NULL,
                steps_json TEXT NOT NULL,
                source_conversation_id TEXT NOT NULL,
                source_run_id TEXT NOT NULL,
                experience_status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(experience_status IN ('pending', 'approved', 'rejected')),
                reviewed_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_goal_outcomes_run
                ON goal_outcomes(source_run_id);

            CREATE TABLE IF NOT EXISTS goal_knowledge (
                id TEXT PRIMARY KEY,
                source_outcome_id TEXT NOT NULL UNIQUE,
                source_goal_id TEXT NOT NULL,
                goal TEXT NOT NULL,
                outcome_status TEXT NOT NULL,
                evaluation_json TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                source_conversation_id TEXT NOT NULL,
                source_run_id TEXT NOT NULL,
                source_approval_status TEXT NOT NULL
                    CHECK(source_approval_status = 'approved'),
                source_approved_at TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(source_outcome_id) REFERENCES goal_outcomes(id)
            );
            CREATE INDEX IF NOT EXISTS idx_goal_knowledge_goal
                ON goal_knowledge(source_goal_id);

            CREATE TABLE IF NOT EXISTS goal_knowledge_usage_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                knowledge_id TEXT NOT NULL,
                source_outcome_id TEXT NOT NULL,
                context_type TEXT NOT NULL
                    CHECK(context_type IN ('planning', 'execution')),
                conversation_id TEXT NOT NULL,
                source_run_id TEXT,
                recorded_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(knowledge_id) REFERENCES goal_knowledge(id),
                FOREIGN KEY(source_outcome_id) REFERENCES goal_outcomes(id)
            );
            CREATE INDEX IF NOT EXISTS idx_goal_knowledge_usage_context
                ON goal_knowledge_usage_events(conversation_id, context_type);

            CREATE TABLE IF NOT EXISTS goal_knowledge_feedback_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usage_event_id INTEGER NOT NULL UNIQUE,
                knowledge_id TEXT NOT NULL,
                source_outcome_id TEXT NOT NULL,
                execution_outcome_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                source_run_id TEXT NOT NULL,
                signal TEXT NOT NULL CHECK(signal IN ('helpful', 'failed')),
                recorded_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(usage_event_id) REFERENCES goal_knowledge_usage_events(id),
                FOREIGN KEY(knowledge_id) REFERENCES goal_knowledge(id),
                FOREIGN KEY(source_outcome_id) REFERENCES goal_outcomes(id),
                FOREIGN KEY(execution_outcome_id) REFERENCES goal_outcomes(id)
            );
            CREATE INDEX IF NOT EXISTS idx_goal_knowledge_feedback_knowledge
                ON goal_knowledge_feedback_events(knowledge_id, signal);

            CREATE TABLE IF NOT EXISTS goal_knowledge_proposals (
                id TEXT PRIMARY KEY,
                usage_event_id INTEGER NOT NULL,
                knowledge_id TEXT NOT NULL,
                source_outcome_id TEXT NOT NULL,
                execution_outcome_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                source_run_id TEXT NOT NULL,
                signal TEXT NOT NULL CHECK(signal = 'failed'),
                proposed_guidance TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'approved', 'rejected')),
                reviewed_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(usage_event_id, execution_outcome_id),
                FOREIGN KEY(usage_event_id) REFERENCES goal_knowledge_usage_events(id),
                FOREIGN KEY(knowledge_id) REFERENCES goal_knowledge(id),
                FOREIGN KEY(source_outcome_id) REFERENCES goal_outcomes(id),
                FOREIGN KEY(execution_outcome_id) REFERENCES goal_outcomes(id)
            );
            CREATE INDEX IF NOT EXISTS idx_goal_knowledge_proposals_status
                ON goal_knowledge_proposals(status, created_at);

            CREATE TABLE IF NOT EXISTS goal_knowledge_refinement_evaluations (
                id TEXT PRIMARY KEY,
                knowledge_id TEXT NOT NULL,
                input_signature TEXT NOT NULL,
                approved_candidate_count INTEGER NOT NULL,
                required_candidate_count INTEGER NOT NULL,
                eligible INTEGER NOT NULL CHECK(eligible IN (0, 1)),
                decision_reason TEXT NOT NULL,
                proposal_ids_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(knowledge_id, input_signature),
                FOREIGN KEY(knowledge_id) REFERENCES goal_knowledge(id)
            );

            CREATE TABLE IF NOT EXISTS goal_knowledge_refinements (
                id TEXT PRIMARY KEY,
                evaluation_id TEXT NOT NULL UNIQUE,
                knowledge_id TEXT NOT NULL,
                proposal_ids_json TEXT NOT NULL,
                proposed_guidance TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'approved', 'rejected')),
                reviewed_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(evaluation_id)
                    REFERENCES goal_knowledge_refinement_evaluations(id),
                FOREIGN KEY(knowledge_id) REFERENCES goal_knowledge(id)
            );
            CREATE INDEX IF NOT EXISTS idx_goal_knowledge_refinements_status
                ON goal_knowledge_refinements(status, created_at);

            CREATE TABLE IF NOT EXISTS goal_knowledge_governance_events (
                id TEXT PRIMARY KEY,
                entity_type TEXT NOT NULL CHECK(entity_type IN ('proposal', 'refinement')),
                entity_id TEXT NOT NULL,
                knowledge_id TEXT NOT NULL,
                decision TEXT NOT NULL CHECK(decision IN ('approved', 'rejected')),
                decision_reason TEXT NOT NULL,
                provenance_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(entity_type, entity_id),
                FOREIGN KEY(knowledge_id) REFERENCES goal_knowledge(id)
            );
            CREATE INDEX IF NOT EXISTS idx_goal_knowledge_governance_knowledge
                ON goal_knowledge_governance_events(knowledge_id, created_at);

            CREATE TABLE IF NOT EXISTS goal_knowledge_evolution_evaluations (
                id TEXT PRIMARY KEY,
                knowledge_id TEXT NOT NULL,
                input_signature TEXT NOT NULL,
                helpful_count INTEGER NOT NULL,
                failed_count INTEGER NOT NULL,
                decision TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(knowledge_id, input_signature),
                FOREIGN KEY(knowledge_id) REFERENCES goal_knowledge(id)
            );
            CREATE TABLE IF NOT EXISTS goal_knowledge_evolution_recommendations (
                id TEXT PRIMARY KEY,
                evaluation_id TEXT NOT NULL UNIQUE,
                knowledge_id TEXT NOT NULL,
                recommendation TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(evaluation_id)
                    REFERENCES goal_knowledge_evolution_evaluations(id),
                FOREIGN KEY(knowledge_id) REFERENCES goal_knowledge(id)
            );
        """)
        cursor = await self._db.execute("PRAGMA table_info(goal_outcomes)")
        goal_outcome_columns = {row["name"] for row in await cursor.fetchall()}
        if "reviewed_at" not in goal_outcome_columns:
            await self._db.execute("ALTER TABLE goal_outcomes ADD COLUMN reviewed_at TEXT")
        cursor = await self._db.execute("PRAGMA table_info(goal_knowledge_usage_events)")
        goal_knowledge_usage_columns = {row["name"] for row in await cursor.fetchall()}
        if "source_run_id" not in goal_knowledge_usage_columns:
            await self._db.execute(
                "ALTER TABLE goal_knowledge_usage_events ADD COLUMN source_run_id TEXT"
            )
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
        cursor = await self._db.execute("PRAGMA table_info(memory_self_steering_reports)")
        steering_columns = {row["name"] for row in await cursor.fetchall()}
        if "status" not in steering_columns:
            await self._db.execute(
                "ALTER TABLE memory_self_steering_reports "
                "ADD COLUMN status TEXT NOT NULL DEFAULT 'pending'"
            )
        if "reviewed_at" not in steering_columns:
            await self._db.execute(
                "ALTER TABLE memory_self_steering_reports ADD COLUMN reviewed_at TEXT"
            )
        cursor = await self._db.execute("PRAGMA table_info(conversations)")
        conversation_columns = {row["name"] for row in await cursor.fetchall()}
        for name, declaration in (("pinned", "INTEGER NOT NULL DEFAULT 0"),
                                  ("archived", "INTEGER NOT NULL DEFAULT 0"),
                                  ("workspace", "TEXT")):
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

    async def list_conversations(self, limit: int = 50) -> list[dict[str, Any]]:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT id, title, created_at, updated_at, pinned, archived, workspace "
            "FROM conversations ORDER BY pinned DESC, updated_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [{**dict(r), "pinned": bool(r["pinned"]),
                 "archived": bool(r["archived"])} for r in rows]

    async def get_conversation_messages(
        self, conversation_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT id, role, content, metadata, created_at FROM messages "
            "WHERE conversation_id = ? ORDER BY created_at ASC, rowid ASC LIMIT ?",
            (conversation_id, limit),
        )
        rows = await cursor.fetchall()
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
        assert self._db is not None
        tokens = re.findall(r"[\w\u4e00-\u9fff]+", query or "")
        if not tokens:
            return []
        match_query = " OR ".join(f'"{token}"' for token in tokens[:12])
        hits: list[dict[str, Any]] = []
        try:
            cursor = await self._db.execute(
                "SELECT m.id, m.conversation_id, m.role, m.content, m.created_at, "
                "       c.title AS conversation_title, "
                "       highlight(messages_fts, 0, '[', ']') AS snippet "
                "FROM messages_fts "
                "JOIN messages m ON messages_fts.rowid = m.rowid "
                "JOIN conversations c ON c.id = m.conversation_id "
                "WHERE messages_fts MATCH ? "
                "ORDER BY rank LIMIT ?",
                (match_query, limit),
            )
            hits = [dict(row) for row in await cursor.fetchall()]
        except aiosqlite.OperationalError:
            hits = []
        if not hits:
            like = f"%{query.strip()}%"
            cursor = await self._db.execute(
                "SELECT m.id, m.conversation_id, m.role, m.content, m.created_at, "
                "       c.title AS conversation_title, "
                "       substr(m.content, 1, 200) AS snippet "
                "FROM messages m JOIN conversations c ON c.id = m.conversation_id "
                "WHERE m.content LIKE ? ORDER BY m.created_at DESC LIMIT ?",
                (like, limit),
            )
            hits = [dict(row) for row in await cursor.fetchall()]
        if conversation_ids is not None:
            allowed = {str(value) for value in conversation_ids}
            hits = [hit for hit in hits if str(hit["conversation_id"]) in allowed]
        for hit in hits:
            hit["context"] = await self._session_context(
                str(hit["conversation_id"]), str(hit["id"]), context,
            )
        return hits

    async def _session_context(
        self, conversation_id: str, message_id: str, window: int,
    ) -> list[dict[str, Any]]:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT id, role, content, created_at FROM messages "
            "WHERE conversation_id = ? ORDER BY created_at ASC, rowid ASC",
            (conversation_id,),
        )
        messages = [dict(row) for row in await cursor.fetchall()]
        index = next(
            (i for i, message in enumerate(messages) if message["id"] == message_id), 0,
        )
        return messages[max(index - window, 0): index + window + 1]

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

    async def persist_reflection_proposals(
        self,
        candidates: list[dict[str, Any]],
        *,
        conversation_id: str,
        source_run_id: str | None,
        reviewer_evidence: list[dict[str, Any]],
    ) -> list[str]:
        """Store advisory Agent reflections in MemoryOS's governed proposal queue."""
        assert self._db is not None
        allowed = {"experience", "fact", "preference", "project_state", "decision"}
        proposal_ids: list[str] = []

        def clean(value: Any, limit: int) -> str:
            text = value if isinstance(value, str) else ""
            text = _REFLECTION_SECRET.sub(
                lambda match: f"{match.group(1) or 'credential'}=[redacted]", text
            )
            return " ".join(text.split())[:limit]

        safe_evidence = clean(json.dumps(reviewer_evidence, ensure_ascii=False), 2000)
        for candidate in candidates:
            category = str(candidate.get("type", ""))
            summary = clean(candidate.get("summary"), 500)
            goal = clean(candidate.get("goal"), 1000)
            if category not in allowed or not summary or _SENSITIVE_MEMORY.search(summary):
                continue
            identity = "\0".join((
                conversation_id, source_run_id or "", category, summary.casefold(),
            ))
            proposal_id = "agent-reflection:" + hashlib.sha256(
                identity.encode("utf-8")
            ).hexdigest()[:32]
            proposal = {
                "id": proposal_id,
                "type": category,
                "category": str(candidate.get("category", category)),
                "summary": summary,
                "goal": goal,
                "source_conversation_id": conversation_id,
                "source_run_id": source_run_id,
                "reviewer_evidence": safe_evidence,
                "advisory_only": True,
            }
            await self._db.execute(
                "INSERT OR IGNORE INTO memory_consolidation_proposals "
                "(id, proposal_json, created_at) VALUES (?, ?, ?)",
                (
                    proposal_id,
                    json.dumps(proposal, ensure_ascii=False, sort_keys=True),
                    datetime.now(UTC).isoformat(),
                ),
            )
            proposal_ids.append(proposal_id)
        await self._db.commit()
        return proposal_ids

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

    async def record_agent_reflection(
        self,
        *,
        category: str,
        component: str,
        summary: str,
        resolution_hint: str,
        source_conversation_id: str,
        source_run_id: str | None,
        model: str | None,
    ) -> str:
        """Persist a redacted failure observation and its execution provenance."""
        if category not in {"tool", "model", "runtime"}:
            raise ValueError("Unsupported agent reflection category")
        if not source_conversation_id:
            raise ValueError("Agent reflections require a source conversation")
        reflection_id = str(uuid.uuid4())

        def safe_text(value: str, limit: int) -> str:
            value = _REFLECTION_SECRET.sub(
                lambda match: f"{match.group(1) or 'credential'}=[redacted]", value
            )
            value = " ".join(value.split())
            return value[:limit] or "Unspecified failure"

        assert self._db is not None
        await self._db.execute(
            "INSERT INTO agent_reflections "
            "(id, category, component, summary, resolution_hint, "
            "source_conversation_id, source_run_id, model) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                reflection_id, category, safe_text(component, 160),
                safe_text(summary, 500), safe_text(resolution_hint, 500),
                source_conversation_id, source_run_id, model,
            ),
        )
        await self._db.commit()
        return reflection_id

    async def retrieve_agent_reflections(
        self, query: str, limit: int = 3,
    ) -> list[dict[str, Any]]:
        """Retrieve relevant failure observations without activating their hints."""
        if limit <= 0:
            return []
        terms = {
            token.casefold()
            for token in _MEMORY_TOKEN.findall(query)
            if len(token) > 1 and token.casefold() not in _MEMORY_STOP_WORDS
        }
        if not terms:
            return []
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT id, category, component, summary, resolution_hint, "
            "source_conversation_id, source_run_id, model, recovered "
            "FROM agent_reflections ORDER BY created_at DESC, rowid DESC LIMIT 200"
        )
        ranked: list[tuple[float, int, dict[str, Any]]] = []
        for row in await cursor.fetchall():
            item = dict(row)
            content_terms = {
                token.casefold()
                for field in ("component", "summary")
                for token in _MEMORY_TOKEN.findall(item[field])
            }
            matched = terms & content_terms
            coverage = len(matched) / len(terms)
            if coverage >= 0.5:
                item["recovered"] = bool(item["recovered"])
                ranked.append((coverage, len(matched), item))
        ranked.sort(key=lambda entry: entry[2]["id"])
        ranked.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
        return [item for _, _, item in ranked[:limit]]

    async def mark_agent_reflections_recovered(self, source_run_id: str) -> None:
        """Record that a run with tool failures later completed successfully."""
        if not source_run_id:
            return
        assert self._db is not None
        await self._db.execute(
            "UPDATE agent_reflections SET recovered = 1, "
            "resolution_hint = 'This run completed after the failure; review its later actions and validate them before reuse.' "
            "WHERE source_run_id = ? AND category = 'tool' AND recovered = 0",
            (source_run_id,),
        )
        await self._db.commit()

    async def record_goal_outcome(
        self,
        *,
        goal_id: str,
        goal: str,
        status: str,
        evaluation: dict[str, Any],
        steps: list[dict[str, Any]],
        source_conversation_id: str,
        source_run_id: str,
    ) -> str:
        """Persist a goal result as a pending experience with step provenance."""
        if not goal_id or not source_conversation_id or not source_run_id:
            raise ValueError("Goal outcomes require goal and run provenance")

        def safe_text(value: Any, limit: int) -> str:
            text = value if isinstance(value, str) else ""
            text = _REFLECTION_SECRET.sub(
                lambda match: f"{match.group(1) or 'credential'}=[redacted]", text
            )
            return " ".join(text.split())[:limit]

        safe_evaluation = {
            "satisfied": evaluation.get("satisfied") is True,
            "evidence": safe_text(evaluation.get("evidence"), 2000),
            "reason": safe_text(evaluation.get("reason"), 1000),
        }
        safe_steps = [
            {
                "id": safe_text(step.get("id"), 160),
                "title": safe_text(step.get("title"), 300),
                "status": safe_text(step.get("status"), 40),
                "evidence": safe_text(step.get("evidence"), 2000),
            }
            for step in steps if isinstance(step, dict)
        ]
        outcome_id = str(uuid.uuid4())
        assert self._db is not None
        await self._db.execute(
            "INSERT INTO goal_outcomes "
            "(id, goal_id, goal, status, evaluation_json, steps_json, "
            "source_conversation_id, source_run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                outcome_id, safe_text(goal_id, 160), safe_text(goal, 1000),
                safe_text(status, 40), json.dumps(safe_evaluation, ensure_ascii=False),
                json.dumps(safe_steps, ensure_ascii=False), source_conversation_id,
                source_run_id,
            ),
        )
        await self._record_goal_knowledge_feedback_for_outcome(outcome_id)
        await self._db.commit()
        return outcome_id

    async def _record_goal_knowledge_feedback_for_outcome(
        self, execution_outcome_id: str,
    ) -> None:
        """Attach execution results to knowledge actually supplied in that conversation."""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT id, status, evaluation_json, steps_json, source_conversation_id, "
            "source_run_id FROM goal_outcomes WHERE id = ?",
            (execution_outcome_id,),
        )
        outcome = await cursor.fetchone()
        if outcome is None:
            return
        evaluation = json.loads(outcome["evaluation_json"])
        signal = (
            "helpful"
            if outcome["status"] == "completed" and evaluation.get("satisfied") is True
            else "failed"
        )
        usage_cursor = await self._db.execute(
            "SELECT usage.id, usage.knowledge_id, usage.source_outcome_id "
            "FROM goal_knowledge_usage_events AS usage "
            "JOIN goal_knowledge AS knowledge ON knowledge.id = usage.knowledge_id "
            "WHERE usage.conversation_id = ? AND usage.context_type = 'execution' "
            "AND (usage.source_run_id = ? OR usage.source_run_id IS NULL) "
            "AND knowledge.source_approval_status = 'approved' "
            "ORDER BY usage.id",
            (outcome["source_conversation_id"], outcome["source_run_id"]),
        )
        usages = await usage_cursor.fetchall()
        for usage in usages:
            await self._db.execute(
                "INSERT OR IGNORE INTO goal_knowledge_feedback_events "
                "(usage_event_id, knowledge_id, source_outcome_id, execution_outcome_id, "
                "conversation_id, source_run_id, signal) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    usage["id"], usage["knowledge_id"], usage["source_outcome_id"],
                    execution_outcome_id, outcome["source_conversation_id"],
                    outcome["source_run_id"], signal,
                ),
            )
            if signal == "failed":
                steps = json.loads(outcome["steps_json"])
                failed_steps = [
                    f"{step['title']}: {step['evidence']}"
                    for step in steps
                    if step.get("status", "").casefold() in {"failed", "blocked"}
                ]
                reasons = [
                    value for value in (
                        evaluation.get("reason", ""),
                        evaluation.get("evidence", ""),
                        *failed_steps,
                    ) if value
                ]
                guidance = (
                    "Review the applied knowledge against this unsuccessful execution "
                    "before reusing or changing it."
                )
                if reasons:
                    guidance += " Observed outcome: " + " ".join(reasons)
                await self._db.execute(
                    "INSERT OR IGNORE INTO goal_knowledge_proposals "
                    "(id, usage_event_id, knowledge_id, source_outcome_id, "
                    "execution_outcome_id, conversation_id, source_run_id, signal, "
                    "proposed_guidance) VALUES (?, ?, ?, ?, ?, ?, ?, 'failed', ?)",
                    (
                        f"goal-knowledge-proposal:{usage['id']}:{execution_outcome_id}",
                        usage["id"], usage["knowledge_id"], usage["source_outcome_id"],
                        execution_outcome_id, outcome["source_conversation_id"],
                        outcome["source_run_id"], guidance[:4000],
                    ),
                )

    async def list_goal_knowledge_feedback(
        self, knowledge_id: str | None = None, limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List result feedback with links to both the applied knowledge and execution."""
        assert self._db is not None
        query = (
            "SELECT id, usage_event_id, knowledge_id, source_outcome_id, "
            "execution_outcome_id, conversation_id, source_run_id, signal, recorded_at "
            "FROM goal_knowledge_feedback_events"
        )
        params: list[Any] = []
        if knowledge_id is not None:
            query += " WHERE knowledge_id = ?"
            params.append(knowledge_id)
        query += " ORDER BY id LIMIT ?"
        params.append(max(0, limit))
        cursor = await self._db.execute(query, params)
        return [dict(row) for row in await cursor.fetchall()]

    async def evaluate_goal_knowledge_evolution(
        self, knowledge_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Analyze approved advisory knowledge usage without changing active knowledge."""
        assert self._db is not None
        query = (
            "SELECT id, source_outcome_id FROM goal_knowledge "
            "WHERE source_approval_status = 'approved'"
        )
        params: list[Any] = []
        if knowledge_id is not None:
            query += " AND id = ?"
            params.append(knowledge_id)
        query += " ORDER BY id"
        cursor = await self._db.execute(query, params)
        knowledge_rows = await cursor.fetchall()

        evaluations: list[dict[str, Any]] = []
        for knowledge_row in knowledge_rows:
            source_id = knowledge_row["id"]
            feedback_cursor = await self._db.execute(
                "SELECT feedback.id, feedback.usage_event_id, feedback.knowledge_id, "
                "feedback.source_outcome_id, feedback.execution_outcome_id, "
                "feedback.conversation_id, feedback.source_run_id, feedback.signal "
                "FROM goal_knowledge_feedback_events AS feedback "
                "JOIN goal_knowledge_usage_events AS usage "
                "ON usage.id = feedback.usage_event_id "
                "JOIN goal_outcomes AS source ON source.id = feedback.source_outcome_id "
                "JOIN goal_outcomes AS execution ON execution.id = feedback.execution_outcome_id "
                "JOIN goal_knowledge AS knowledge ON knowledge.id = feedback.knowledge_id "
                "WHERE feedback.knowledge_id = ? "
                "AND usage.knowledge_id = feedback.knowledge_id "
                "AND usage.source_outcome_id = feedback.source_outcome_id "
                "AND usage.conversation_id = feedback.conversation_id "
                "AND (usage.source_run_id = feedback.source_run_id "
                "OR usage.source_run_id IS NULL) "
                "AND source.experience_status = 'approved' "
                "AND knowledge.source_approval_status = 'approved' "
                "AND execution.source_conversation_id = feedback.conversation_id "
                "AND execution.source_run_id = feedback.source_run_id "
                "ORDER BY feedback.id",
                (source_id,),
            )
            evidence = [dict(row) for row in await feedback_cursor.fetchall()]
            helpful_count = sum(item["signal"] == "helpful" for item in evidence)
            failed_count = sum(item["signal"] == "failed" for item in evidence)
            signature_payload = json.dumps(
                evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            )
            input_signature = hashlib.sha256(signature_payload.encode("utf-8")).hexdigest()
            evaluation_id = f"goal-knowledge-evolution-evaluation:{source_id}:{input_signature}"
            decision = (
                "review_recommended_after_repeated_failures"
                if failed_count >= 2 else
                "monitor_after_single_failure"
                if failed_count == 1 else
                "positive_evidence_only"
                if helpful_count else "insufficient_usage_evidence"
            )
            evidence_json = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
            await self._db.execute(
                "INSERT OR IGNORE INTO goal_knowledge_evolution_evaluations "
                "(id, knowledge_id, input_signature, helpful_count, failed_count, "
                "decision, evidence_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    evaluation_id, source_id, input_signature, helpful_count,
                    failed_count, decision, evidence_json,
                ),
            )
            recommendation_id = None
            recommendation_text = None
            if failed_count >= 2:
                recommendation_id = f"goal-knowledge-evolution-recommendation:{input_signature}"
                recommendation_text = (
                    "Review this approved advisory knowledge against its repeated failed "
                    "applications before deciding whether to refine it."
                )
                await self._db.execute(
                    "INSERT OR IGNORE INTO goal_knowledge_evolution_recommendations "
                    "(id, evaluation_id, knowledge_id, recommendation, evidence_json) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        recommendation_id, evaluation_id, source_id,
                        recommendation_text, evidence_json,
                    ),
                )
            evaluations.append({
                "id": evaluation_id,
                "knowledge_id": source_id,
                "source_outcome_id": knowledge_row["source_outcome_id"],
                "input_signature": input_signature,
                "helpful_count": helpful_count,
                "failed_count": failed_count,
                "decision": decision,
                "evidence": evidence,
                "recommendation_id": recommendation_id,
                "recommendation": recommendation_text,
            })
        await self._db.commit()
        return evaluations

    async def list_goal_knowledge_evolution_evaluations(
        self, knowledge_id: str | None = None, limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return durable evolution decisions and their complete supporting evidence."""
        assert self._db is not None
        query = (
            "SELECT id, knowledge_id, input_signature, helpful_count, failed_count, "
            "decision, evidence_json, created_at FROM goal_knowledge_evolution_evaluations"
        )
        params: list[Any] = []
        if knowledge_id is not None:
            query += " WHERE knowledge_id = ?"
            params.append(knowledge_id)
        query += " ORDER BY id LIMIT ?"
        params.append(max(0, limit))
        cursor = await self._db.execute(query, params)
        results = []
        for row in await cursor.fetchall():
            item = dict(row)
            item["evidence"] = json.loads(item.pop("evidence_json"))
            results.append(item)
        return results

    async def list_goal_knowledge_evolution_recommendations(
        self, knowledge_id: str | None = None, limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List review-only recommendations separately from active advisory knowledge."""
        assert self._db is not None
        query = (
            "SELECT id, evaluation_id, knowledge_id, recommendation, evidence_json, created_at "
            "FROM goal_knowledge_evolution_recommendations"
        )
        params: list[Any] = []
        if knowledge_id is not None:
            query += " WHERE knowledge_id = ?"
            params.append(knowledge_id)
        query += " ORDER BY id LIMIT ?"
        params.append(max(0, limit))
        cursor = await self._db.execute(query, params)
        results = []
        for row in await cursor.fetchall():
            item = dict(row)
            item["evidence"] = json.loads(item.pop("evidence_json"))
            results.append(item)
        return results

    async def list_goal_knowledge_proposals(
        self, status: str | None = None, limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List pending or reviewed improvement candidates without applying them."""
        if status not in (None, "pending", "approved", "rejected"):
            raise ValueError("Unsupported goal knowledge proposal status")
        assert self._db is not None
        query = (
            "SELECT id, usage_event_id, knowledge_id, source_outcome_id, "
            "execution_outcome_id, conversation_id, source_run_id, signal, "
            "proposed_guidance, status, reviewed_at, created_at "
            "FROM goal_knowledge_proposals"
        )
        params: list[Any] = []
        if status is not None:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY id LIMIT ?"
        params.append(max(0, limit))
        cursor = await self._db.execute(query, params)
        return [dict(row) for row in await cursor.fetchall()]

    async def evaluate_goal_knowledge_refinements(
        self, knowledge_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Audit approved improvement candidates and create eligible refinement candidates."""
        assert self._db is not None
        query = (
            "SELECT knowledge_id, id, proposed_guidance FROM goal_knowledge_proposals "
            "WHERE status = 'approved'"
        )
        params: list[Any] = []
        if knowledge_id is not None:
            query += " AND knowledge_id = ?"
            params.append(knowledge_id)
        query += " ORDER BY knowledge_id, id"
        cursor = await self._db.execute(query, params)
        rows = await cursor.fetchall()
        grouped: dict[str, list[Any]] = {}
        for row in rows:
            grouped.setdefault(row["knowledge_id"], []).append(row)

        if knowledge_id is not None and knowledge_id not in grouped:
            exists = await self._db.execute(
                "SELECT 1 FROM goal_knowledge WHERE id = ? AND source_approval_status = 'approved'",
                (knowledge_id,),
            )
            if await exists.fetchone():
                grouped[knowledge_id] = []

        evaluations: list[dict[str, Any]] = []
        for source_id, candidates in sorted(grouped.items()):
            approved_refinements = await self._db.execute(
                "SELECT proposal_ids_json FROM goal_knowledge_refinements "
                "WHERE knowledge_id = ? AND status = 'approved'",
                (source_id,),
            )
            consumed_ids = {
                proposal_id
                for row in await approved_refinements.fetchall()
                for proposal_id in json.loads(row["proposal_ids_json"])
            }
            candidates = [row for row in candidates if row["id"] not in consumed_ids]
            proposal_ids = [row["id"] for row in candidates]
            proposal_ids_json = json.dumps(proposal_ids, ensure_ascii=False)
            input_signature = hashlib.sha256(proposal_ids_json.encode("utf-8")).hexdigest()
            evaluation_id = f"goal-knowledge-refinement-evaluation:{source_id}:{input_signature}"
            eligible = len(candidates) >= _GOAL_KNOWLEDGE_REFINEMENT_MIN_CANDIDATES
            decision_reason = (
                "repeated_approved_improvements"
                if eligible else "insufficient_approved_improvements"
            )
            await self._db.execute(
                "INSERT OR IGNORE INTO goal_knowledge_refinement_evaluations "
                "(id, knowledge_id, input_signature, approved_candidate_count, "
                "required_candidate_count, eligible, decision_reason, proposal_ids_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    evaluation_id, source_id, input_signature, len(candidates),
                    _GOAL_KNOWLEDGE_REFINEMENT_MIN_CANDIDATES, int(eligible),
                    decision_reason, proposal_ids_json,
                ),
            )
            refinement_id = None
            if eligible:
                unique_guidance = list(dict.fromkeys(
                    row["proposed_guidance"].strip() for row in candidates
                    if row["proposed_guidance"].strip()
                ))
                guidance = " ".join(unique_guidance)[:4000]
                refinement_id = f"goal-knowledge-refinement:{evaluation_id.rsplit(':', 1)[-1]}"
                await self._db.execute(
                    "INSERT OR IGNORE INTO goal_knowledge_refinements "
                    "(id, evaluation_id, knowledge_id, proposal_ids_json, proposed_guidance) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (refinement_id, evaluation_id, source_id, proposal_ids_json, guidance),
                )
            evaluations.append({
                "id": evaluation_id,
                "knowledge_id": source_id,
                "approved_candidate_count": len(candidates),
                "required_candidate_count": _GOAL_KNOWLEDGE_REFINEMENT_MIN_CANDIDATES,
                "eligible": eligible,
                "decision_reason": decision_reason,
                "proposal_ids": proposal_ids,
                "refinement_id": refinement_id,
            })
        await self._db.commit()
        return evaluations

    async def list_goal_knowledge_refinement_evaluations(
        self, knowledge_id: str | None = None, limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return durable refinement decisions with thresholds and source candidates."""
        assert self._db is not None
        query = (
            "SELECT id, knowledge_id, approved_candidate_count, required_candidate_count, "
            "eligible, decision_reason, proposal_ids_json, created_at "
            "FROM goal_knowledge_refinement_evaluations"
        )
        params: list[Any] = []
        if knowledge_id is not None:
            query += " WHERE knowledge_id = ?"
            params.append(knowledge_id)
        query += " ORDER BY id LIMIT ?"
        params.append(max(0, limit))
        cursor = await self._db.execute(query, params)
        evaluations = []
        for row in await cursor.fetchall():
            item = dict(row)
            item["eligible"] = bool(item["eligible"])
            item["proposal_ids"] = json.loads(item.pop("proposal_ids_json"))
            evaluations.append(item)
        return evaluations

    async def list_goal_knowledge_refinements(
        self, status: str | None = None, limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List candidate, reviewed, and source provenance for advisory refinements."""
        if status not in (None, "pending", "approved", "rejected"):
            raise ValueError("Unsupported goal knowledge refinement status")
        assert self._db is not None
        query = (
            "SELECT id, evaluation_id, knowledge_id, proposal_ids_json, proposed_guidance, "
            "status, reviewed_at, created_at FROM goal_knowledge_refinements"
        )
        params: list[Any] = []
        if status is not None:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY id LIMIT ?"
        params.append(max(0, limit))
        cursor = await self._db.execute(query, params)
        results = []
        for row in await cursor.fetchall():
            item = dict(row)
            item["proposal_ids"] = json.loads(item.pop("proposal_ids_json"))
            results.append(item)
        return results

    async def evaluate_goal_knowledge_governance(
        self, entity_type: str | None = None, entity_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Deterministically evaluate pending advisory candidates against approval gates."""
        if entity_type not in (None, "proposal", "refinement"):
            raise ValueError("Unsupported goal knowledge governance entity type")
        assert self._db is not None
        evaluated: list[dict[str, Any]] = []
        for kind in ((entity_type,) if entity_type else ("proposal", "refinement")):
            if kind == "proposal":
                query = (
                    "SELECT id, knowledge_id, usage_event_id, source_outcome_id, "
                    "execution_outcome_id, conversation_id, source_run_id "
                    "FROM goal_knowledge_proposals WHERE status = 'pending'"
                )
                params: list[Any] = []
                if entity_id is not None:
                    query += " AND id = ?"
                    params.append(entity_id)
                query += " ORDER BY id"
                cursor = await self._db.execute(query, params)
                for row in await cursor.fetchall():
                    knowledge_cursor = await self._db.execute(
                        "SELECT source_approval_status FROM goal_knowledge WHERE id = ?",
                        (row["knowledge_id"],),
                    )
                    knowledge = await knowledge_cursor.fetchone()
                    provenance = {
                        key: row[key] for key in (
                            "usage_event_id", "source_outcome_id", "execution_outcome_id",
                            "conversation_id", "source_run_id",
                        )
                    }
                    complete = all(value is not None for value in provenance.values())
                    eligible = bool(
                        knowledge and knowledge["source_approval_status"] == "approved"
                        and complete
                    )
                    evaluated.append({
                        "entity_type": "proposal", "entity_id": row["id"],
                        "knowledge_id": row["knowledge_id"], "eligible": eligible,
                        "decision_reason": (
                            "approved_advisory_source_with_complete_provenance"
                            if eligible else "missing_approved_source_or_provenance"
                        ),
                        "provenance": provenance,
                    })
            else:
                query = (
                    "SELECT id, evaluation_id, knowledge_id, proposal_ids_json "
                    "FROM goal_knowledge_refinements WHERE status = 'pending'"
                )
                params = []
                if entity_id is not None:
                    query += " AND id = ?"
                    params.append(entity_id)
                query += " ORDER BY id"
                cursor = await self._db.execute(query, params)
                for row in await cursor.fetchall():
                    proposal_ids = json.loads(row["proposal_ids_json"])
                    evaluation_cursor = await self._db.execute(
                        "SELECT eligible FROM goal_knowledge_refinement_evaluations "
                        "WHERE id = ? AND knowledge_id = ?",
                        (row["evaluation_id"], row["knowledge_id"]),
                    )
                    evaluation = await evaluation_cursor.fetchone()
                    knowledge_cursor = await self._db.execute(
                        "SELECT source_approval_status FROM goal_knowledge WHERE id = ?",
                        (row["knowledge_id"],),
                    )
                    knowledge = await knowledge_cursor.fetchone()
                    proposals_cursor = await self._db.execute(
                        "SELECT id, knowledge_id, status FROM goal_knowledge_proposals "
                        "WHERE id IN (" + ",".join("?" for _ in proposal_ids) + ") "
                        "ORDER BY id" if proposal_ids else
                        "SELECT id, knowledge_id, status FROM goal_knowledge_proposals WHERE 0",
                        proposal_ids,
                    )
                    proposals = await proposals_cursor.fetchall()
                    proposal_gate = (
                        len(proposals) == len(proposal_ids)
                        and all(
                            item["knowledge_id"] == row["knowledge_id"]
                            and item["status"] == "approved" for item in proposals
                        )
                    )
                    eligible = bool(
                        evaluation and evaluation["eligible"] == 1
                        and knowledge and knowledge["source_approval_status"] == "approved"
                        and proposal_ids and proposal_gate
                    )
                    evaluated.append({
                        "entity_type": "refinement", "entity_id": row["id"],
                        "knowledge_id": row["knowledge_id"], "eligible": eligible,
                        "decision_reason": (
                            "eligible_evaluation_with_approved_provenance"
                            if eligible else "ineligible_evaluation_or_unapproved_provenance"
                        ),
                        "evaluation_id": row["evaluation_id"],
                        "proposal_ids": proposal_ids,
                    })
        return evaluated

    async def list_goal_knowledge_governance_history(
        self, knowledge_id: str | None = None, limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return immutable explicit-review decisions and their source provenance."""
        assert self._db is not None
        query = (
            "SELECT id, entity_type, entity_id, knowledge_id, decision, "
            "decision_reason, provenance_json, created_at "
            "FROM goal_knowledge_governance_events"
        )
        params: list[Any] = []
        if knowledge_id is not None:
            query += " WHERE knowledge_id = ?"
            params.append(knowledge_id)
        query += " ORDER BY rowid LIMIT ?"
        params.append(max(0, limit))
        cursor = await self._db.execute(query, params)
        events = []
        for row in await cursor.fetchall():
            item = dict(row)
            item["provenance"] = json.loads(item.pop("provenance_json"))
            events.append(item)
        return events

    async def _record_goal_knowledge_governance_event(
        self, entity_type: str, entity_id: str, knowledge_id: str,
        decision: str, decision_reason: str, provenance: dict[str, Any],
    ) -> str:
        assert self._db is not None
        event_id = f"goal-knowledge-governance:{entity_type}:{entity_id}"
        await self._db.execute(
            "INSERT INTO goal_knowledge_governance_events "
            "(id, entity_type, entity_id, knowledge_id, decision, decision_reason, "
            "provenance_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                event_id, entity_type, entity_id, knowledge_id, decision, decision_reason,
                json.dumps(provenance, ensure_ascii=False, sort_keys=True),
            ),
        )
        return event_id

    async def review_goal_knowledge_refinement(
        self, refinement_id: str, approved: bool,
    ) -> bool:
        """Apply an approved refinement to advisory knowledge after explicit review."""
        assert self._db is not None
        [governance] = await self.evaluate_goal_knowledge_governance(
            entity_type="refinement", entity_id=refinement_id,
        ) or [{}]
        if approved and not governance.get("eligible"):
            return False
        refinement_cursor = await self._db.execute(
            "SELECT knowledge_id, proposal_ids_json, evaluation_id "
            "FROM goal_knowledge_refinements WHERE id = ? AND status = 'pending'",
            (refinement_id,),
        )
        candidate = await refinement_cursor.fetchone()
        if candidate is None:
            return False
        provenance = {
            "evaluation_id": candidate["evaluation_id"],
            "proposal_ids": json.loads(candidate["proposal_ids_json"]),
        }
        cursor = await self._db.execute(
            "UPDATE goal_knowledge_refinements SET status = ?, reviewed_at = datetime('now') "
            "WHERE id = ? AND status = 'pending'",
            ("approved" if approved else "rejected", refinement_id),
        )
        if cursor.rowcount == 0:
            await self._db.commit()
            return False
        event_id = await self._record_goal_knowledge_governance_event(
            "refinement", refinement_id, candidate["knowledge_id"],
            "approved" if approved else "rejected",
            governance.get("decision_reason", "explicit_rejection_of_pending_candidate"),
            provenance,
        )
        if approved:
            candidate_cursor = await self._db.execute(
                "SELECT knowledge_id, proposal_ids_json, proposed_guidance "
                "FROM goal_knowledge_refinements WHERE id = ?",
                (refinement_id,),
            )
            candidate = await candidate_cursor.fetchone()
            evidence_cursor = await self._db.execute(
                "SELECT goal, evidence_json FROM goal_knowledge WHERE id = ? "
                "AND source_approval_status = 'approved'",
                (candidate["knowledge_id"],),
            )
            knowledge = await evidence_cursor.fetchone()
            if knowledge is None:
                await self._db.rollback()
                return False
            evidence = json.loads(knowledge["evidence_json"])
            evidence.append({
                "type": "approved_knowledge_refinement",
                "refinement_id": refinement_id,
                "governance_event_id": event_id,
                "proposal_ids": json.loads(candidate["proposal_ids_json"]),
                "guidance": candidate["proposed_guidance"],
            })
            await self._db.execute(
                "UPDATE goal_knowledge SET goal = ?, evidence_json = ? WHERE id = ?",
                (
                    knowledge["goal"] + " " + candidate["proposed_guidance"],
                    json.dumps(evidence, ensure_ascii=False, sort_keys=True),
                    candidate["knowledge_id"],
                ),
            )
        await self._db.commit()
        return True

    async def review_goal_knowledge_proposal(
        self, proposal_id: str, approved: bool,
    ) -> bool:
        """Reject a candidate or explicitly promote it as new advisory knowledge."""
        assert self._db is not None
        [governance] = await self.evaluate_goal_knowledge_governance(
            entity_type="proposal", entity_id=proposal_id,
        ) or [{}]
        if approved and not governance.get("eligible"):
            return False
        proposal_cursor = await self._db.execute(
            "SELECT knowledge_id, usage_event_id, source_outcome_id, execution_outcome_id, "
            "conversation_id, source_run_id FROM goal_knowledge_proposals "
            "WHERE id = ? AND status = 'pending'",
            (proposal_id,),
        )
        pending_proposal = await proposal_cursor.fetchone()
        if pending_proposal is None:
            return False
        provenance = {
            key: pending_proposal[key] for key in (
                "usage_event_id", "source_outcome_id", "execution_outcome_id",
                "conversation_id", "source_run_id",
            )
        }
        cursor = await self._db.execute(
            "UPDATE goal_knowledge_proposals SET status = ?, reviewed_at = datetime('now') "
            "WHERE id = ? AND status = 'pending'",
            ("approved" if approved else "rejected", proposal_id),
        )
        if cursor.rowcount == 0:
            await self._db.commit()
            return False
        event_id = await self._record_goal_knowledge_governance_event(
            "proposal", proposal_id, pending_proposal["knowledge_id"],
            "approved" if approved else "rejected",
            governance.get("decision_reason", "explicit_rejection_of_pending_candidate"),
            provenance,
        )
        if approved:
            proposal_cursor = await self._db.execute(
                "SELECT execution_outcome_id, proposed_guidance "
                "FROM goal_knowledge_proposals WHERE id = ?",
                (proposal_id,),
            )
            proposal = await proposal_cursor.fetchone()
            # Approval of the proposed improvement is an explicit review of this result.
            await self._db.execute(
                "UPDATE goal_outcomes SET experience_status = 'approved', "
                "reviewed_at = COALESCE(reviewed_at, datetime('now')) "
                "WHERE id = ? AND experience_status = 'pending'",
                (proposal["execution_outcome_id"],),
            )
            await self._consolidate_goal_outcome(proposal["execution_outcome_id"])
            knowledge_cursor = await self._db.execute(
                "SELECT id, goal, evidence_json FROM goal_knowledge "
                "WHERE source_outcome_id = ? AND source_approval_status = 'approved'",
                (proposal["execution_outcome_id"],),
            )
            knowledge = await knowledge_cursor.fetchone()
            if knowledge is not None:
                evidence = json.loads(knowledge["evidence_json"])
                evidence.append({
                    "type": "approved_improvement_proposal",
                    "proposal_id": proposal_id,
                    "governance_event_id": event_id,
                    "guidance": proposal["proposed_guidance"],
                })
                await self._db.execute(
                    "UPDATE goal_knowledge SET goal = ?, evidence_json = ? WHERE id = ?",
                    (
                        knowledge["goal"] + " " + proposal["proposed_guidance"],
                        json.dumps(evidence, ensure_ascii=False, sort_keys=True),
                        knowledge["id"],
                    ),
                )
        await self._db.commit()
        return True

    async def list_goal_outcomes(
        self, experience_status: str | None = None, limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List durable goal outcomes for review."""
        if experience_status not in (None, "pending", "approved", "rejected"):
            raise ValueError("Unsupported goal experience status")
        assert self._db is not None
        query = (
            "SELECT id, goal_id, goal, status, evaluation_json, steps_json, "
            "source_conversation_id, source_run_id, experience_status, reviewed_at, created_at "
            "FROM goal_outcomes"
        )
        params: list[Any] = []
        if experience_status is not None:
            query += " WHERE experience_status = ?"
            params.append(experience_status)
        query += " ORDER BY created_at DESC, id LIMIT ?"
        params.append(max(0, limit))
        cursor = await self._db.execute(query, params)
        outcomes = []
        for row in await cursor.fetchall():
            outcome = dict(row)
            outcome["evaluation"] = json.loads(outcome.pop("evaluation_json"))
            outcome["steps"] = json.loads(outcome.pop("steps_json"))
            outcomes.append(outcome)
        return outcomes

    async def review_goal_experience(self, outcome_id: str, approved: bool) -> bool:
        """Explicitly approve or reject a pending goal experience."""
        assert self._db is not None
        cursor = await self._db.execute(
            "UPDATE goal_outcomes SET experience_status = ?, reviewed_at = datetime('now') "
            "WHERE id = ? AND experience_status = 'pending'",
            ("approved" if approved else "rejected", outcome_id),
        )
        if cursor.rowcount and approved:
            await self._consolidate_goal_outcome(outcome_id)
        await self._db.commit()
        return cursor.rowcount > 0

    async def _consolidate_goal_outcome(self, outcome_id: str) -> bool:
        """Persist one approved goal outcome as traceable advisory knowledge."""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT id, goal_id, goal, status, evaluation_json, steps_json, "
            "source_conversation_id, source_run_id, experience_status, reviewed_at "
            "FROM goal_outcomes WHERE id = ? AND experience_status = 'approved'",
            (outcome_id,),
        )
        row = await cursor.fetchone()
        if row is None or row["reviewed_at"] is None:
            return False
        evaluation = json.loads(row["evaluation_json"])
        steps = json.loads(row["steps_json"])
        evidence = [
            {
                "step_id": step["id"], "title": step["title"],
                "status": step["status"], "evidence": step["evidence"],
            }
            for step in steps
        ]
        content = " ".join([
            row["goal"], row["status"], evaluation.get("reason", ""),
            evaluation.get("evidence", ""),
            *(f"{item['title']} {item['evidence']}" for item in evidence),
        ])
        await self._db.execute(
            "INSERT OR IGNORE INTO goal_knowledge "
            "(id, source_outcome_id, source_goal_id, goal, outcome_status, "
            "evaluation_json, evidence_json, source_conversation_id, source_run_id, "
            "source_approval_status, source_approved_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'approved', ?)",
            (
                f"goal-knowledge:{row['id']}", row["id"], row["goal_id"], content,
                row["status"], row["evaluation_json"],
                json.dumps(evidence, ensure_ascii=False, sort_keys=True),
                row["source_conversation_id"], row["source_run_id"], row["reviewed_at"],
            ),
        )
        return True

    async def retrieve_approved_goal_knowledge(
        self, query: str, limit: int = 3,
    ) -> list[dict[str, Any]]:
        """Return deterministic, provenance-linked knowledge from approved goals."""
        terms = {
            token.casefold() for token in _MEMORY_TOKEN.findall(query)
            if len(token) > 1 and token.casefold() not in _MEMORY_STOP_WORDS
        }
        if not terms or limit <= 0:
            return []
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT id, source_outcome_id, source_goal_id, goal, outcome_status, "
            "evaluation_json, evidence_json, source_conversation_id, source_run_id, "
            "source_approval_status, source_approved_at FROM goal_knowledge "
            "WHERE source_approval_status = 'approved' "
            "ORDER BY source_outcome_id"
        )
        ranked: list[tuple[int, str, dict[str, Any]]] = []
        for row in await cursor.fetchall():
            item = dict(row)
            matched = terms & {
                token.casefold() for token in _MEMORY_TOKEN.findall(item["goal"])
            }
            if not matched:
                continue
            item["evaluation"] = json.loads(item.pop("evaluation_json"))
            item["evidence"] = json.loads(item.pop("evidence_json"))
            item["approval_status"] = item.pop("source_approval_status")
            item["approved_at"] = item.pop("source_approved_at")
            item["advisory"] = True
            item["matched_terms"] = sorted(matched)
            ranked.append((len(matched), item["source_outcome_id"], item))
        ranked.sort(key=lambda entry: entry[1])
        ranked.sort(key=lambda entry: entry[0], reverse=True)
        return [item for _, _, item in ranked[:limit]]

    async def record_goal_knowledge_usage(
        self, knowledge_id: str, context_type: str, conversation_id: str,
        source_run_id: str | None = None,
    ) -> int:
        """Record approved goal knowledge when supplied to a planning or execution prompt."""
        if context_type not in {"planning", "execution"}:
            raise ValueError("Unsupported goal knowledge context type")
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT source_outcome_id FROM goal_knowledge "
            "WHERE id = ? AND source_approval_status = 'approved'",
            (knowledge_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise ValueError("Cannot record usage for unapproved goal knowledge")
        cursor = await self._db.execute(
            "INSERT INTO goal_knowledge_usage_events "
            "(knowledge_id, source_outcome_id, context_type, conversation_id, source_run_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                knowledge_id, row["source_outcome_id"], context_type, conversation_id,
                source_run_id,
            ),
        )
        await self._db.commit()
        return int(cursor.lastrowid)

    async def retrieve_approved_goal_experiences(
        self, query: str, limit: int = 3,
    ) -> list[dict[str, Any]]:
        """Return relevant, explicitly approved goal experience as advisory data."""
        terms = {
            token.casefold() for token in _MEMORY_TOKEN.findall(query)
            if len(token) > 1 and token.casefold() not in _MEMORY_STOP_WORDS
        }
        if not terms or limit <= 0:
            return []
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT id, goal, status, evaluation_json, steps_json, "
            "source_conversation_id, source_run_id, reviewed_at FROM goal_outcomes "
            "WHERE experience_status = 'approved' "
            "ORDER BY created_at DESC, id LIMIT 200"
        )
        ranked: list[tuple[int, str, dict[str, Any]]] = []
        for row in await cursor.fetchall():
            item = dict(row)
            content = item["goal"] + " " + " ".join(
                step["title"] + " " + step["evidence"]
                for step in json.loads(item["steps_json"])
            )
            matched = terms & {
                token.casefold() for token in _MEMORY_TOKEN.findall(content)
            }
            if not matched:
                continue
            item["evaluation"] = json.loads(item.pop("evaluation_json"))
            item["steps"] = json.loads(item.pop("steps_json"))
            ranked.append((len(matched), item["id"], item))
        ranked.sort(key=lambda entry: entry[1])
        ranked.sort(key=lambda entry: entry[0], reverse=True)
        return [item for _, _, item in ranked[:limit]]

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

    async def create_memory_optimization_report(
        self,
        *,
        stale_after_days: int = 180,
        window_days: int = 90,
        as_of: datetime | None = None,
    ) -> dict[str, Any]:
        """Create and durably audit an advisory optimization report snapshot."""
        report = evaluate_memory_optimization(await self.get_memory_health(
            stale_after_days=stale_after_days,
            window_days=window_days,
            as_of=as_of,
        ))
        report_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        assert self._db is not None
        await self._db.execute(
            "INSERT INTO memory_optimization_reports (id, report_json, created_at) "
            "VALUES (?, ?, ?)",
            (report_id, json.dumps(report, ensure_ascii=False, sort_keys=True), created_at),
        )
        await self._db.commit()
        return {"id": report_id, "created_at": created_at, "report": report}

    async def list_memory_optimization_reports(
        self, *, limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return immutable optimization report snapshots, newest first."""
        if limit < 0:
            raise ValueError("Report limit must be non-negative")
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT id, report_json, created_at FROM memory_optimization_reports "
            "ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,),
        )
        return [
            {"id": row["id"], "created_at": row["created_at"],
             "report": json.loads(row["report_json"])}
            for row in await cursor.fetchall()
        ]

    async def get_knowledge_maturity(
        self, *, as_of: datetime | None = None,
    ) -> dict[str, Any]:
        """Evaluate active facts using durable history, usage, and review evidence."""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT key, memory_type, confidence, source_conversation_id, "
            "source_message_id, created_at, updated_at FROM facts ORDER BY key"
        )
        memories = {row["key"]: dict(row) for row in await cursor.fetchall()}
        evidence: dict[str, list[str]] = {key: [f"fact:{key}"] for key in memories}

        cursor = await self._db.execute(
            "SELECT key, id FROM memory_fact_history WHERE event_type='superseded' "
            "ORDER BY id"
        )
        for row in await cursor.fetchall():
            key = row["key"]
            if key in memories:
                memories[key]["change_count"] = memories[key].get("change_count", 0) + 1
                evidence[key].append(f"history:{row['id']}")

        for table, field, alias in (
            ("memory_usage_events", "outcome", "usage"),
            ("memory_feedback", "signal", "feedback"),
            ("memory_evaluations", "rating", "evaluation"),
        ):
            cursor = await self._db.execute(
                f"SELECT memory_key, {field}, id FROM {table} ORDER BY id"
            )
            for row in await cursor.fetchall():
                key = row["memory_key"]
                if key not in memories:
                    continue
                count_field = f"{row[field]}_count"
                memories[key][count_field] = memories[key].get(count_field, 0) + 1
                evidence[key].append(f"{alias}:{row['id']}")

        for key, memory in memories.items():
            memory["evidence_refs"] = evidence[key]
        return evaluate_knowledge_maturity(list(memories.values()), as_of=as_of)

    async def create_knowledge_maturity_report(
        self, *, as_of: datetime | None = None,
    ) -> dict[str, Any]:
        """Persist an advisory maturity snapshot without changing active facts."""
        report = await self.get_knowledge_maturity(as_of=as_of)
        report_id = str(uuid.uuid4())
        created_at = datetime.now(UTC).isoformat()
        assert self._db is not None
        await self._db.execute(
            "INSERT INTO memory_maturity_reports (id, report_json, created_at) "
            "VALUES (?, ?, ?)",
            (report_id, json.dumps(report, ensure_ascii=False, sort_keys=True), created_at),
        )
        await self._db.commit()
        return {"id": report_id, "created_at": created_at, "report": report}

    async def list_knowledge_maturity_reports(
        self, *, limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return immutable maturity report snapshots, newest first."""
        if limit < 0:
            raise ValueError("Report limit must be non-negative")
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT id, report_json, created_at FROM memory_maturity_reports "
            "ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,),
        )
        return [
            {"id": row["id"], "created_at": row["created_at"],
             "report": json.loads(row["report_json"])}
            for row in await cursor.fetchall()
        ]

    async def create_knowledge_self_steering_report(self) -> dict[str, Any]:
        """Persist evidence-linked suggestions derived from advisory knowledge signals."""
        maturity = await self.create_knowledge_maturity_report()
        evaluations = await self.evaluate_goal_knowledge_evolution()
        report = evaluate_knowledge_self_steering(
            maturity["report"], evaluations, maturity_report_id=maturity["id"],
        )
        report_id = str(uuid.uuid4())
        created_at = datetime.now(UTC).isoformat()
        assert self._db is not None
        await self._db.execute(
            "INSERT INTO memory_self_steering_reports (id, report_json, created_at) "
            "VALUES (?, ?, ?)",
            (report_id, json.dumps(report, ensure_ascii=False, sort_keys=True), created_at),
        )
        await self._db.commit()
        return {
            "id": report_id, "created_at": created_at, "report": report,
            "status": "pending", "reviewed_at": None,
        }

    async def review_knowledge_self_steering_report(
        self, report_id: str, approved: bool,
    ) -> bool:
        """Explicitly approve or reject one immutable self-steering snapshot."""
        assert self._db is not None
        cursor = await self._db.execute(
            "UPDATE memory_self_steering_reports SET status = ?, reviewed_at = datetime('now') "
            "WHERE id = ? AND status = 'pending'",
            ("approved" if approved else "rejected", report_id),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def create_knowledge_optimization_candidates(self) -> list[dict[str, Any]]:
        """Create stable low-risk candidates only from explicitly approved reports."""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT id, report_json FROM memory_self_steering_reports "
            "WHERE status = 'approved' ORDER BY id"
        )
        approved_reports = [
            {"id": row["id"], "report": json.loads(row["report_json"])}
            for row in await cursor.fetchall()
        ]
        candidates = evaluate_knowledge_optimization_candidates(approved_reports)
        candidate_ids = {candidate["id"] for candidate in candidates}
        created_at = datetime.now(UTC).isoformat()
        for candidate in candidates:
            evaluation = evaluate_knowledge_optimization_candidate(candidate)
            await self._db.execute(
                "INSERT OR IGNORE INTO memory_optimization_candidates "
                "(id, source_report_id, candidate_json, evaluation_json, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    candidate["id"], candidate["source_report_id"],
                    json.dumps(candidate, ensure_ascii=False, sort_keys=True),
                    json.dumps(evaluation, ensure_ascii=False, sort_keys=True), created_at,
                ),
            )
        await self._db.commit()
        persisted = await self.list_knowledge_optimization_candidates()
        return [candidate for candidate in persisted if candidate["id"] in candidate_ids]

    async def list_knowledge_optimization_candidates(
        self, *, status: str | None = None, limit: int = 100,
    ) -> list[dict[str, Any]]:
        if status not in (None, "pending", "approved", "rejected"):
            raise ValueError("Unsupported knowledge optimization candidate status")
        if limit < 0:
            raise ValueError("Candidate limit must be non-negative")
        assert self._db is not None
        query = (
            "SELECT id, candidate_json, evaluation_json, status, reviewed_at, created_at "
            "FROM memory_optimization_candidates"
        )
        params: list[Any] = []
        if status is not None:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY id LIMIT ?"
        params.append(limit)
        cursor = await self._db.execute(query, params)
        results = []
        for row in await cursor.fetchall():
            item = json.loads(row["candidate_json"])
            item.update({
                "status": row["status"], "reviewed_at": row["reviewed_at"],
                "created_at": row["created_at"],
                "evaluation": json.loads(row["evaluation_json"]),
            })
            review_cursor = await self._db.execute(
                "SELECT decision, reviewed_at FROM memory_optimization_candidate_reviews "
                "WHERE candidate_id = ? ORDER BY id", (row["id"],),
            )
            item["review_history"] = [dict(review) for review in await review_cursor.fetchall()]
            results.append(item)
        return results

    async def review_knowledge_optimization_candidate(
        self, candidate_id: str, approved: bool,
    ) -> bool:
        """Record an explicit candidate decision; approval remains advisory only."""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT evaluation_json FROM memory_optimization_candidates "
            "WHERE id = ? AND status = 'pending'", (candidate_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return False
        evaluation = json.loads(row["evaluation_json"])
        if approved and not evaluation.get("eligible"):
            return False
        decision = "approved" if approved else "rejected"
        reviewed_at = datetime.now(UTC).isoformat()
        cursor = await self._db.execute(
            "UPDATE memory_optimization_candidates SET status = ?, reviewed_at = ? "
            "WHERE id = ? AND status = 'pending'",
            (decision, reviewed_at, candidate_id),
        )
        if cursor.rowcount == 0:
            await self._db.commit()
            return False
        await self._db.execute(
            "INSERT INTO memory_optimization_candidate_reviews "
            "(candidate_id, decision, reviewed_at) VALUES (?, ?, ?)",
            (candidate_id, decision, reviewed_at),
        )
        await self._db.commit()
        return True

    async def create_knowledge_consolidation_proposals(self) -> list[dict[str, Any]]:
        """Create deterministic advisory proposals from approved candidates only."""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT id, candidate_json FROM memory_optimization_candidates "
            "WHERE status = 'approved' ORDER BY id"
        )
        approved_candidates = []
        for row in await cursor.fetchall():
            candidate = json.loads(row["candidate_json"])
            candidate["id"] = row["id"]
            candidate["status"] = "approved"
            approved_candidates.append(candidate)

        proposals = evaluate_knowledge_consolidation_proposals(approved_candidates)
        proposal_ids = {proposal["id"] for proposal in proposals}
        created_at = datetime.now(UTC).isoformat()
        for proposal in proposals:
            await self._db.execute(
                "INSERT OR IGNORE INTO memory_consolidation_proposals "
                "(id, proposal_json, created_at) VALUES (?, ?, ?)",
                (
                    proposal["id"],
                    json.dumps(proposal, ensure_ascii=False, sort_keys=True),
                    created_at,
                ),
            )
        await self._db.commit()
        persisted = await self.list_knowledge_consolidation_proposals()
        return [proposal for proposal in persisted if proposal["id"] in proposal_ids]

    async def list_knowledge_consolidation_proposals(
        self, *, status: str | None = None, limit: int = 100,
    ) -> list[dict[str, Any]]:
        if status not in (None, "pending", "approved", "rejected"):
            raise ValueError("Unsupported knowledge consolidation proposal status")
        if limit < 0:
            raise ValueError("Proposal limit must be non-negative")
        assert self._db is not None
        query = (
            "SELECT id, proposal_json, status, reviewed_at, created_at "
            "FROM memory_consolidation_proposals"
        )
        params: list[Any] = []
        if status is not None:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY id LIMIT ?"
        params.append(limit)
        cursor = await self._db.execute(query, params)
        results = []
        for row in await cursor.fetchall():
            proposal = json.loads(row["proposal_json"])
            proposal.update({
                "status": row["status"], "reviewed_at": row["reviewed_at"],
                "created_at": row["created_at"],
            })
            review_cursor = await self._db.execute(
                "SELECT decision, reviewed_at FROM memory_consolidation_proposal_reviews "
                "WHERE proposal_id = ? ORDER BY id", (row["id"],),
            )
            proposal["review_history"] = [dict(review) for review in await review_cursor.fetchall()]
            results.append(proposal)
        return results

    async def review_knowledge_consolidation_proposal(
        self, proposal_id: str, approved: bool,
    ) -> bool:
        """Record one explicit proposal decision without promoting or mutating facts."""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT 1 FROM memory_consolidation_proposals "
            "WHERE id = ? AND status = 'pending'", (proposal_id,),
        )
        if await cursor.fetchone() is None:
            return False
        decision = "approved" if approved else "rejected"
        reviewed_at = datetime.now(UTC).isoformat()
        cursor = await self._db.execute(
            "UPDATE memory_consolidation_proposals SET status = ?, reviewed_at = ? "
            "WHERE id = ? AND status = 'pending'",
            (decision, reviewed_at, proposal_id),
        )
        if cursor.rowcount == 0:
            await self._db.commit()
            return False
        await self._db.execute(
            "INSERT INTO memory_consolidation_proposal_reviews "
            "(proposal_id, decision, reviewed_at) VALUES (?, ?, ?)",
            (proposal_id, decision, reviewed_at),
        )
        await self._db.commit()
        return True

    async def activate_knowledge_consolidation_proposal(
        self, proposal_id: str,
    ) -> dict[str, Any] | None:
        """Create one advisory activation snapshot for an approved proposal."""
        assert self._db is not None
        activation_id = f"activation:{proposal_id}"
        cursor = await self._db.execute(
            "SELECT activation_json, created_at FROM memory_knowledge_activations "
            "WHERE proposal_id = ?", (proposal_id,),
        )
        existing = await cursor.fetchone()
        if existing is not None:
            activation = json.loads(existing["activation_json"])
            activation["created_at"] = existing["created_at"]
            history_cursor = await self._db.execute(
                "SELECT event, created_at FROM memory_knowledge_activation_history "
                "WHERE activation_id = ? ORDER BY id", (activation_id,),
            )
            activation["history"] = [dict(row) for row in await history_cursor.fetchall()]
            return activation

        cursor = await self._db.execute(
            "SELECT proposal_json, reviewed_at FROM memory_consolidation_proposals "
            "WHERE id = ? AND status = 'approved'", (proposal_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None

        proposal = json.loads(row["proposal_json"])
        proposal["status"] = "approved"
        proposal["reviewed_at"] = row["reviewed_at"]
        review_cursor = await self._db.execute(
            "SELECT decision, reviewed_at FROM memory_consolidation_proposal_reviews "
            "WHERE proposal_id = ? ORDER BY id", (proposal_id,),
        )
        approval_history = [dict(review) for review in await review_cursor.fetchall()]
        if not approval_history or approval_history[-1]["decision"] != "approved":
            return None

        created_at = datetime.now(UTC).isoformat()
        activation = {
            "id": activation_id,
            "proposal_id": proposal_id,
            "advisory_only": True,
            "activation_status": "active",
            "proposal": proposal,
            "approval_history": approval_history,
            "created_at": created_at,
            "history": [{"event": "activated", "created_at": created_at}],
        }
        await self._db.execute(
            "INSERT INTO memory_knowledge_activations "
            "(id, proposal_id, activation_json, created_at) VALUES (?, ?, ?, ?)",
            (
                activation_id, proposal_id,
                json.dumps(activation, ensure_ascii=False, sort_keys=True), created_at,
            ),
        )
        await self._db.execute(
            "INSERT INTO memory_knowledge_activation_history "
            "(activation_id, event, created_at) VALUES (?, 'activated', ?)",
            (activation_id, created_at),
        )
        await self._db.commit()
        return activation

    async def list_knowledge_activations(
        self, *, limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return advisory activation snapshots with their immutable audit history."""
        if limit < 0:
            raise ValueError("Activation limit must be non-negative")
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT id, activation_json, created_at FROM memory_knowledge_activations "
            "ORDER BY id LIMIT ?", (limit,),
        )
        results = []
        for row in await cursor.fetchall():
            activation = json.loads(row["activation_json"])
            activation["created_at"] = row["created_at"]
            history_cursor = await self._db.execute(
                "SELECT event, created_at FROM memory_knowledge_activation_history "
                "WHERE activation_id = ? ORDER BY id", (row["id"],),
            )
            activation["history"] = [dict(item) for item in await history_cursor.fetchall()]
            results.append(activation)
        return results

    async def verify_knowledge_activation_usage(
        self,
        activation_id: str,
        *,
        candidate_id: str,
        evidence_refs: list[str],
        usage_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Record whether a claimed advisory use is backed by activation provenance."""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT activation_json FROM memory_knowledge_activations WHERE id = ?",
            (activation_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None

        activation = json.loads(row["activation_json"])
        proposal = activation.get("proposal", {})
        candidate_snapshot = next((
            item for item in proposal.get("candidate_snapshots", [])
            if item.get("candidate_id") == candidate_id
        ), None)
        checks = {
            "activation_active": (
                activation.get("activation_status") == "active"
                and activation.get("advisory_only") is True
                and proposal.get("status") == "approved"
                and proposal.get("advisory_only") is True
                and bool(activation.get("approval_history"))
                and activation["approval_history"][-1].get("decision") == "approved"
            ),
            "candidate_in_provenance": (
                candidate_id in proposal.get("source_candidate_ids", [])
                and candidate_snapshot is not None
            ),
            "evidence_supported": bool(evidence_refs) and candidate_snapshot is not None and (
                set(evidence_refs).issubset(set(candidate_snapshot.get("evidence_refs", [])))
            ),
        }
        created_at = datetime.now(UTC).isoformat()
        verification = {
            "id": str(uuid.uuid4()),
            "activation_id": activation_id,
            "status": "verified" if all(checks.values()) else "unverified",
            "advisory_only": True,
            "usage": {
                "usage_id": usage_id,
                "candidate_id": candidate_id,
                "evidence_refs": sorted(set(evidence_refs)),
            },
            "checks": checks,
            "activation_snapshot": activation,
            "created_at": created_at,
            "history": [{"event": "verification_recorded", "created_at": created_at}],
        }
        await self._db.execute(
            "INSERT INTO memory_knowledge_verifications "
            "(id, activation_id, status, verification_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (
                verification["id"], activation_id, verification["status"],
                json.dumps(verification, ensure_ascii=False, sort_keys=True), created_at,
            ),
        )
        await self._db.execute(
            "INSERT INTO memory_knowledge_verification_history "
            "(verification_id, event, created_at) VALUES (?, 'verification_recorded', ?)",
            (verification["id"], created_at),
        )
        await self._db.commit()
        return verification

    async def list_knowledge_verifications(
        self, *, activation_id: str | None = None, limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return immutable verification snapshots and their append-only history."""
        if limit < 0:
            raise ValueError("Verification limit must be non-negative")
        assert self._db is not None
        query = (
            "SELECT id, verification_json FROM memory_knowledge_verifications"
        )
        params: list[Any] = []
        if activation_id is not None:
            query += " WHERE activation_id = ?"
            params.append(activation_id)
        query += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
        params.append(limit)
        cursor = await self._db.execute(query, params)
        results = []
        for row in await cursor.fetchall():
            verification = json.loads(row["verification_json"])
            history_cursor = await self._db.execute(
                "SELECT event, created_at FROM memory_knowledge_verification_history "
                "WHERE verification_id = ? ORDER BY id", (row["id"],),
            )
            verification["history"] = [dict(item) for item in await history_cursor.fetchall()]
            results.append(verification)
        return results

    async def get_knowledge_health(
        self, *, as_of: datetime | None = None,
    ) -> dict[str, Any]:
        """Evaluate active advisory knowledge from approval, verification, use, and feedback."""
        activations = await self.list_knowledge_activations(limit=1_000_000)
        assert self._db is not None
        for activation in activations:
            proposal = activation.get("proposal", {})
            knowledge_id = str(proposal.get("area", ""))
            activation_id = activation["id"]
            activation["verifications"] = await self.list_knowledge_verifications(
                activation_id=activation_id, limit=1_000_000,
            )
            if not knowledge_id:
                activation["usage_events"] = []
                activation["feedback_events"] = []
                continue

            cursor = await self._db.execute(
                "SELECT usage.id, usage.knowledge_id, usage.source_outcome_id, "
                "usage.context_type, usage.conversation_id, usage.source_run_id, "
                "usage.recorded_at FROM goal_knowledge_usage_events AS usage "
                "JOIN goal_knowledge AS knowledge ON knowledge.id = usage.knowledge_id "
                "JOIN goal_outcomes AS source ON source.id = usage.source_outcome_id "
                "WHERE usage.knowledge_id = ? AND knowledge.source_approval_status = 'approved' "
                "AND source.experience_status = 'approved' ORDER BY usage.id",
                (knowledge_id,),
            )
            activation["usage_events"] = [dict(row) for row in await cursor.fetchall()]
            cursor = await self._db.execute(
                "SELECT feedback.id, feedback.usage_event_id, feedback.knowledge_id, "
                "feedback.source_outcome_id, feedback.execution_outcome_id, "
                "feedback.conversation_id, feedback.source_run_id, feedback.signal, "
                "feedback.recorded_at FROM goal_knowledge_feedback_events AS feedback "
                "JOIN goal_knowledge_usage_events AS usage "
                "ON usage.id = feedback.usage_event_id "
                "JOIN goal_outcomes AS source ON source.id = feedback.source_outcome_id "
                "JOIN goal_outcomes AS execution ON execution.id = feedback.execution_outcome_id "
                "JOIN goal_knowledge AS knowledge ON knowledge.id = feedback.knowledge_id "
                "WHERE feedback.knowledge_id = ? "
                "AND usage.knowledge_id = feedback.knowledge_id "
                "AND usage.source_outcome_id = feedback.source_outcome_id "
                "AND usage.conversation_id = feedback.conversation_id "
                "AND (usage.source_run_id = feedback.source_run_id OR usage.source_run_id IS NULL) "
                "AND source.experience_status = 'approved' "
                "AND knowledge.source_approval_status = 'approved' "
                "AND execution.source_conversation_id = feedback.conversation_id "
                "AND execution.source_run_id = feedback.source_run_id "
                "ORDER BY feedback.id",
                (knowledge_id,),
            )
            activation["feedback_events"] = [dict(row) for row in await cursor.fetchall()]
        return evaluate_knowledge_health(activations, as_of=as_of)

    async def create_knowledge_health_report(
        self, *, as_of: datetime | None = None,
    ) -> dict[str, Any]:
        """Persist a deterministic advisory health snapshot without changing activated knowledge."""
        report = await self.get_knowledge_health(as_of=as_of)
        identity = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        report_id = "knowledge-health:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
        created_at = datetime.now(UTC).isoformat()
        assert self._db is not None
        await self._db.execute(
            "INSERT OR IGNORE INTO memory_knowledge_health_reports "
            "(id, report_json, created_at) VALUES (?, ?, ?)",
            (report_id, json.dumps(report, ensure_ascii=False, sort_keys=True), created_at),
        )
        await self._db.commit()
        cursor = await self._db.execute(
            "SELECT created_at FROM memory_knowledge_health_reports WHERE id = ?",
            (report_id,),
        )
        row = await cursor.fetchone()
        review_cursor = await self._db.execute(
            "SELECT decision, reviewed_at FROM memory_knowledge_health_report_reviews "
            "WHERE report_id = ? ORDER BY id", (report_id,),
        )
        review_history = [dict(item) for item in await review_cursor.fetchall()]
        return {
            "id": report_id, "created_at": row["created_at"], "report": report,
            "status": review_history[-1]["decision"] if review_history else "pending",
            "review_history": review_history,
        }

    async def list_knowledge_health_reports(
        self, *, limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List immutable advisory knowledge health snapshots, newest first."""
        if limit < 0:
            raise ValueError("Knowledge health report limit must be non-negative")
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT id, report_json, created_at FROM memory_knowledge_health_reports "
            "ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,),
        )
        reports = []
        for row in await cursor.fetchall():
            item = {"id": row["id"], "created_at": row["created_at"],
                    "report": json.loads(row["report_json"])}
            review_cursor = await self._db.execute(
                "SELECT decision, reviewed_at FROM memory_knowledge_health_report_reviews "
                "WHERE report_id = ? ORDER BY id", (row["id"],),
            )
            item["review_history"] = [dict(review) for review in await review_cursor.fetchall()]
            item["status"] = item["review_history"][-1]["decision"] \
                if item["review_history"] else "pending"
            reports.append(item)
        return reports

    async def review_knowledge_health_report(self, report_id: str, approved: bool) -> bool:
        """Append one explicit approval decision for an immutable health snapshot."""
        assert self._db is not None
        cursor = await self._db.execute(
            "INSERT INTO memory_knowledge_health_report_reviews "
            "(report_id, decision, reviewed_at) "
            "SELECT ?, ?, ? WHERE EXISTS ("
            "SELECT 1 FROM memory_knowledge_health_reports WHERE id = ?) "
            "AND NOT EXISTS (SELECT 1 FROM memory_knowledge_health_report_reviews "
            "WHERE report_id = ?)",
            (report_id, "approved" if approved else "rejected", datetime.now(UTC).isoformat(),
             report_id, report_id),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def create_knowledge_consolidated_insights(self) -> list[dict[str, Any]]:
        """Persist deterministic advisory insights from explicitly approved health snapshots."""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT report.id, report.report_json, review.decision AS status "
            "FROM memory_knowledge_health_reports AS report "
            "JOIN memory_knowledge_health_report_reviews AS review "
            "ON review.report_id = report.id AND review.decision = 'approved' "
            "ORDER BY report.id"
        )
        approved_reports = [
            {"id": row["id"], "report": json.loads(row["report_json"]),
             "status": row["status"]}
            for row in await cursor.fetchall()
        ]
        insights = evaluate_consolidated_knowledge_insights(approved_reports)
        created_at = datetime.now(UTC).isoformat()
        for insight in insights:
            await self._db.execute(
                "INSERT OR IGNORE INTO memory_knowledge_consolidated_insights "
                "(id, insight_json, created_at) VALUES (?, ?, ?)",
                (
                    insight["id"],
                    json.dumps(insight, ensure_ascii=False, sort_keys=True),
                    created_at,
                ),
            )
        await self._db.commit()
        return insights

    async def list_knowledge_consolidated_insights(
        self, *, limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List immutable advisory insight snapshots newest first."""
        if limit < 0:
            raise ValueError("Consolidated insight limit must be non-negative")
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT insight_json FROM memory_knowledge_consolidated_insights "
            "ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,),
        )
        return [json.loads(row["insight_json"]) for row in await cursor.fetchall()]

    async def apply_knowledge_consolidated_insights(
        self,
        query: str,
        *,
        purpose: str,
        conversation_id: str | None = None,
        source_run_id: str | None = None,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        """Return relevant approved insights as advisory context and persist the decision."""
        if purpose not in {"planning", "execution"}:
            raise ValueError("Insight application purpose must be planning or execution")
        if limit < 0:
            raise ValueError("Insight application limit must be non-negative")
        assert self._db is not None

        query_terms = {
            token.casefold() for token in _MEMORY_TOKEN.findall(query)
            if len(token) > 1 and token.casefold() not in _MEMORY_STOP_WORDS
        }
        cursor = await self._db.execute(
            "SELECT id, insight_json FROM memory_knowledge_consolidated_insights "
            "ORDER BY id"
        )
        rows = await cursor.fetchall()
        decisions: list[dict[str, Any]] = []
        matches: list[tuple[int, str, dict[str, Any], list[str]]] = []
        for row in rows:
            insight = json.loads(row["insight_json"])
            source_ids = sorted({
                str(item) for item in insight.get("source_health_report_ids", ()) if item
            })
            evidence_refs = sorted({
                str(item) for item in insight.get("evidence_refs", ()) if item
            })
            approved_ids: set[str] = set()
            for source_id in source_ids:
                approval = await self._db.execute(
                    "SELECT decision FROM memory_knowledge_health_report_reviews "
                    "WHERE report_id = ? ORDER BY id DESC LIMIT 1", (source_id,),
                )
                review = await approval.fetchone()
                if review and review["decision"] == "approved":
                    approved_ids.add(source_id)

            valid_snapshot = (
                insight.get("id") == row["id"]
                and insight.get("advisory_only") is True
                and bool(source_ids)
                and approved_ids == set(source_ids)
                and bool(evidence_refs)
            )
            if not valid_snapshot:
                decisions.append({
                    "insight_id": row["id"], "decision": "filtered",
                    "reason": "source_snapshot_not_approved_or_invalid",
                    "source_health_report_ids": source_ids,
                    "evidence_refs": evidence_refs,
                })
                continue

            searchable = " ".join(str(insight.get(field, "")) for field in (
                "knowledge_id", "decision", "recommendation",
            ))
            matched_terms = sorted(query_terms & {
                token.casefold() for token in _MEMORY_TOKEN.findall(searchable)
                if len(token) > 1 and token.casefold() not in _MEMORY_STOP_WORDS
            })
            if not matched_terms:
                decisions.append({
                    "insight_id": row["id"], "decision": "filtered",
                    "reason": "not_relevant_to_query",
                    "source_health_report_ids": source_ids,
                    "evidence_refs": evidence_refs,
                })
                continue
            matches.append((len(matched_terms), row["id"], insight, matched_terms))

        matches.sort(key=lambda item: (-item[0], item[1]))
        selected = matches[:limit]
        selected_ids = {item[1] for item in selected}
        for _, insight_id, insight, matched_terms in matches:
            decisions.append({
                "insight_id": insight_id,
                "decision": "applied" if insight_id in selected_ids else "filtered",
                "reason": "relevant_approved_advisory_insight" if insight_id in selected_ids
                else "application_limit",
                "matched_terms": matched_terms,
                "source_health_report_ids": sorted(insight["source_health_report_ids"]),
                "evidence_refs": sorted(insight["evidence_refs"]),
            })
        decisions.sort(key=lambda item: item["insight_id"])

        query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()
        source_report_ids = sorted({
            source_id for _, _, insight, _ in selected
            for source_id in insight["source_health_report_ids"]
        })
        applied_evidence_refs = sorted({
            ref for _, _, insight, _ in selected for ref in insight["evidence_refs"]
        })
        application = {
            "purpose": purpose,
            "conversation_id": conversation_id,
            "source_run_id": source_run_id,
            "query_sha256": query_hash,
            "applied_insight_ids": [item[1] for item in selected],
            "source_health_report_ids": source_report_ids,
            "evidence_refs": applied_evidence_refs,
            "decisions": decisions,
            "advisory_only": True,
        }
        identity = json.dumps(
            application, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        application["id"] = "knowledge-insight-application:" + hashlib.sha256(
            identity.encode("utf-8")
        ).hexdigest()
        created_at = datetime.now(UTC).isoformat()
        await self._db.execute(
            "INSERT OR IGNORE INTO memory_knowledge_insight_applications "
            "(id, application_json, created_at) VALUES (?, ?, ?)",
            (
                application["id"],
                json.dumps(application, ensure_ascii=False, sort_keys=True),
                created_at,
            ),
        )
        await self._db.commit()
        return [
            {**insight, "application_id": application["id"], "matched_terms": matched_terms}
            for _, _, insight, matched_terms in selected
        ]

    async def list_knowledge_insight_applications(
        self, *, limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List immutable insight application decisions, newest first."""
        if limit < 0:
            raise ValueError("Insight application limit must be non-negative")
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT application_json, created_at FROM memory_knowledge_insight_applications "
            "ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,),
        )
        return [
            {**json.loads(row["application_json"]), "created_at": row["created_at"]}
            for row in await cursor.fetchall()
        ]

    async def list_knowledge_self_steering_reports(
        self, *, limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return immutable self-steering snapshots, newest first."""
        if limit < 0:
            raise ValueError("Report limit must be non-negative")
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT id, report_json, created_at, status, reviewed_at "
            "FROM memory_self_steering_reports "
            "ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,),
        )
        return [
            {"id": row["id"], "created_at": row["created_at"],
             "report": json.loads(row["report_json"]), "status": row["status"],
             "reviewed_at": row["reviewed_at"]}
            for row in await cursor.fetchall()
        ]

    async def get_agent_context(
        self, query: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Return validated facts and traceable knowledge views for an agent request."""
        if limit <= 0:
            return []
        views = await self.retrieve_user_knowledge(query, limit=1)
        facts = await self.get_active_context(query, limit=limit - len(views))
        return facts + views

    async def get_agent_context_with_trace(
        self, query: str, limit: int = 10
    ) -> dict[str, Any]:
        """Return agent context with the knowledge retrieval decisions that produced it."""
        trace = await self.retrieve_user_knowledge_with_trace(
            query, limit=1 if limit > 0 else limit
        )
        if limit <= 0:
            return {"memories": [], "knowledge_trace": trace}
        views = trace["results"]
        facts = await self.get_active_context(query, limit=limit - len(views))
        return {"memories": facts + views, "knowledge_trace": trace}

    async def generate_user_knowledge_with_trace(
        self,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Build knowledge views and explain lifecycle decisions deterministically."""
        facts = await self.list_facts()
        grouped: dict[str, list[dict[str, Any]]] = {}
        decisions: list[dict[str, Any]] = []
        for fact in facts:
            reason = None
            if fact["memory_type"] in {"identity", "commitment"}:
                if not await self._has_approved_user_evidence(
                    fact, fact["memory_type"]
                ):
                    reason = f"{fact['memory_type']}_evidence_missing"
            if reason is None and fact["memory_type"] == "commitment":
                if fact["commitment_status"] != "active":
                    reason = "commitment_inactive"
            category = fact["category"]
            if reason is None and category in {"general", "extracted"}:
                reason = "category_excluded"
            if reason:
                decisions.append({
                    "item_type": "fact", "item_key": fact["key"],
                    "decision": "filtered", "reason": reason,
                    "source_conversation_id": fact["source_conversation_id"],
                    "source_message_id": fact["source_message_id"],
                })
                continue
            grouped.setdefault(category, []).append(fact)

        views: list[dict[str, Any]] = []
        for category, memories in sorted(grouped.items()):
            memories.sort(key=lambda fact: fact["key"])
            if len(memories) < 2:
                fact = memories[0]
                decisions.append({
                    "item_type": "fact", "item_key": fact["key"],
                    "decision": "filtered", "reason": "category_has_fewer_than_two_items",
                    "source_conversation_id": fact["source_conversation_id"],
                    "source_message_id": fact["source_message_id"],
                })
                continue
            evidence = [
                {
                    "key": fact["key"],
                    "value": fact["value"],
                    "memory_type": fact["memory_type"],
                    "source_conversation_id": fact["source_conversation_id"],
                    "source_message_id": fact["source_message_id"],
                }
                for fact in memories
            ]
            content = "\n".join(
                f"{fact['key']}: {fact['value']}" for fact in memories
            )
            view = {
                "id": f"user-knowledge:{category}",
                "key": f"user_knowledge_{category}",
                "category": category,
                "memory_type": "knowledge_view",
                "value": content,
                "evidence": evidence,
            }
            views.append(view)
            decisions.append({
                "item_type": "knowledge_view", "item_key": view["key"],
                "decision": "eligible", "reason": "active_evidence_aggregated",
                "evidence_keys": [fact["key"] for fact in memories],
                "evidence": [
                    {
                        field: item[field]
                        for field in (
                            "key", "memory_type", "source_conversation_id",
                            "source_message_id",
                        )
                    }
                    for item in evidence
                ],
            })

        for candidate in await self.list_memory_candidates():
            if candidate["status"] == "approved":
                continue
            decisions.append({
                "item_type": "candidate", "item_key": candidate["key"],
                "candidate_id": candidate["id"],
                "decision": "filtered",
                "reason": f"candidate_{candidate['status']}",
                "memory_type": candidate["memory_type"],
                "source_conversation_id": candidate["source_conversation_id"],
                "source_message_id": candidate["source_message_id"],
            })
        decisions.sort(key=lambda item: (
            item["item_type"], item["item_key"], item.get("candidate_id", "")
        ))
        return views, decisions

    async def generate_user_knowledge(self) -> list[dict[str, Any]]:
        """Aggregate related active memories into deterministic, evidence-linked views."""
        views, _ = await self.generate_user_knowledge_with_trace()
        return views

    async def retrieve_user_knowledge_with_trace(
        self, query: str, limit: int = 5
    ) -> dict[str, Any]:
        """Return knowledge results with deterministic retrieval and lifecycle reasons."""
        terms = sorted({
            token.casefold()
            for token in _MEMORY_TOKEN.findall(query)
            if len(token) > 1 and token.casefold() not in _MEMORY_STOP_WORDS
        })
        if limit <= 0:
            decisions = [{
                "item_type": "query", "item_key": "query",
                "decision": "filtered", "reason": "non_positive_limit",
            }]
            return {"query_terms": terms, "results": [], "decisions": decisions}
        if not terms:
            decisions = [{
                "item_type": "query", "item_key": "query",
                "decision": "filtered", "reason": "no_query_terms",
            }]
            return {"query_terms": terms, "results": [], "decisions": decisions}
        views, decisions = await self.generate_user_knowledge_with_trace()

        ranked: list[tuple[float, int, str, dict[str, Any], set[str]]] = []
        for view in views:
            key_terms = {
                token for token in re.split(r"[\W_]+", view["key"].casefold()) if token
            }
            evidence_key_terms = {
                token.casefold()
                for item in view["evidence"]
                for token in re.split(r"[\W_]+", item["key"])
                if token
            }
            value_terms = {
                token.casefold() for token in _MEMORY_TOKEN.findall(view["value"])
            }
            matched_terms = set(terms) & (key_terms | evidence_key_terms | value_terms)
            coverage = len(matched_terms) / len(terms)
            score = sum(
                5 if term in evidence_key_terms else
                4 if term in key_terms else
                1 if term in value_terms else 0
                for term in terms
            )
            if coverage >= 0.5:
                ranked.append((coverage, score, view["key"], view, matched_terms))
            else:
                decisions.append({
                    "item_type": "knowledge_view", "item_key": view["key"],
                    "decision": "filtered", "reason": "coverage_below_threshold",
                    "coverage": coverage, "score": score,
                    "matched_terms": sorted(matched_terms),
                    "evidence_keys": [item["key"] for item in view["evidence"]],
                    "evidence": [
                        {
                            field: item[field]
                            for field in (
                                "key", "memory_type", "source_conversation_id",
                                "source_message_id",
                            )
                        }
                        for item in view["evidence"]
                    ],
                })
        ranked.sort(key=lambda item: item[2])
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        results = [view for _, _, _, view, _ in ranked[:limit]]
        for index, (coverage, score, key, view, matched_terms) in enumerate(ranked):
            selected = index < limit
            decisions.append({
                "item_type": "knowledge_view", "item_key": key,
                "decision": "selected" if selected else "filtered",
                "reason": "ranked_within_limit" if selected else "ranked_outside_limit",
                "coverage": coverage, "score": score,
                "matched_terms": sorted(matched_terms),
                "evidence_keys": [item["key"] for item in view["evidence"]],
                "evidence": [
                    {
                        field: item[field]
                        for field in (
                            "key", "memory_type", "source_conversation_id",
                            "source_message_id",
                        )
                    }
                    for item in view["evidence"]
                ],
            })
        decisions.sort(key=lambda item: (
            item["item_type"], item["item_key"], item.get("candidate_id", "")
        ))
        return {"query_terms": terms, "results": results, "decisions": decisions}

    async def retrieve_user_knowledge(
        self, query: str, limit: int = 5
    ) -> list[dict[str, Any]]:
        """Return deterministic query-matched knowledge views with their evidence."""
        trace = await self.retrieve_user_knowledge_with_trace(query, limit=limit)
        log.info(
            "memory.knowledge_retrieval",
            query_terms=trace["query_terms"],
            limit=limit,
            selected_keys=[view["key"] for view in trace["results"]],
            decisions=trace["decisions"],
        )
        return trace["results"]

    async def generate_knowledge_graph(self) -> dict[str, list[dict[str, Any]]]:
        """Build a deterministic, evidence-linked graph from recallable facts.

        Nodes and edges are derived from the existing facts table, so this does
        not change the memory schema or candidate approval lifecycle.
        """
        facts = await self.list_facts()
        eligible: list[dict[str, Any]] = []
        for fact in facts:
            sensitive_key = fact["key"].replace("_", " ")
            if _SENSITIVE_MEMORY.search(f"{sensitive_key} {fact['value']}"):
                continue
            if fact["memory_type"] in {"identity", "commitment"}:
                if not await self._has_approved_user_evidence(
                    fact, fact["memory_type"]
                ):
                    continue
            if (
                fact["memory_type"] == "commitment"
                and fact["commitment_status"] != "active"
            ):
                continue
            eligible.append(fact)

        nodes = []
        by_category: dict[str, list[dict[str, Any]]] = {}
        for fact in sorted(eligible, key=lambda item: item["key"]):
            node_id = "kn_" + hashlib.sha256(
                f"fact\0{fact['key']}".encode()
            ).hexdigest()
            nodes.append({
                "id": node_id,
                "kind": "fact",
                "key": fact["key"],
                "value": fact["value"],
                "category": fact["category"],
                "memory_type": fact["memory_type"],
                "source_conversation_id": fact["source_conversation_id"],
                "source_message_id": fact["source_message_id"],
            })
            by_category.setdefault(fact["category"], []).append({
                "node_id": node_id,
                "fact": fact,
            })

        edges = []
        for category, members in sorted(by_category.items()):
            for index, left in enumerate(members):
                for right in members[index + 1:]:
                    edge_key = (
                        f"same_category\0{left['node_id']}\0{right['node_id']}"
                    )
                    edge_id = "ke_" + hashlib.sha256(
                        edge_key.encode()
                    ).hexdigest()
                    evidence: list[dict[str, Any]] = []
                    for member in (left, right):
                        fact = member["fact"]
                        evidence.append({
                            "node_id": member["node_id"],
                            "fact_key": fact["key"],
                            "source_conversation_id": fact["source_conversation_id"],
                            "source_message_id": fact["source_message_id"],
                        })
                    edges.append({
                        "id": edge_id,
                        "source": left["node_id"],
                        "target": right["node_id"],
                        "relation": "same_category",
                        "category": category,
                        "evidence": evidence,
                    })
        return {"nodes": nodes, "edges": edges}

    async def get_relevant_knowledge_graph(
        self, query: str, limit: int = 10, hops: int = 1
    ) -> dict[str, list[dict[str, Any]] | list[str]]:
        """Return query-matched facts and bounded neighboring facts deterministically."""
        graph = await self.generate_knowledge_graph()
        terms = {
            token.casefold()
            for token in _MEMORY_TOKEN.findall(query)
            if len(token) > 1 and token.casefold() not in _MEMORY_STOP_WORDS
        }
        nodes_by_id = {node["id"]: node for node in graph["nodes"]}
        ranked: list[tuple[int, str]] = []
        for node in graph["nodes"]:
            key_terms = {
                token for token in re.split(r"[\W_]+", node["key"].casefold())
                if token
            }
            value_terms = {
                token.casefold() for token in _MEMORY_TOKEN.findall(node["value"])
            }
            category_terms = {
                token.casefold()
                for token in _MEMORY_TOKEN.findall(node["category"])
            }
            score = sum(
                4 if term in key_terms else
                2 if term in category_terms else
                1 if term in value_terms else 0
                for term in terms
            )
            if score:
                ranked.append((score, node["id"]))
        ranked.sort(key=lambda item: item[1])
        ranked.sort(key=lambda item: item[0], reverse=True)
        cap = max(0, limit)
        seed_ids = [node_id for _, node_id in ranked[:cap]]
        selected = set(seed_ids)
        frontier = set(seed_ids)
        adjacency: dict[str, set[str]] = {}
        for edge in graph["edges"]:
            adjacency.setdefault(edge["source"], set()).add(edge["target"])
            adjacency.setdefault(edge["target"], set()).add(edge["source"])
        for _ in range(max(0, min(hops, 3))):
            discovered = {
                neighbor
                for node_id in frontier
                for neighbor in adjacency.get(node_id, set())
                if neighbor not in selected
            }
            frontier = discovered
            selected.update(discovered)
        selected_nodes = [nodes_by_id[node_id] for node_id in sorted(selected)]
        selected_edges = [
            edge for edge in graph["edges"]
            if edge["source"] in selected and edge["target"] in selected
        ]
        return {
            "seed_ids": seed_ids,
            "nodes": selected_nodes,
            "edges": selected_edges,
        }

    async def get_task_knowledge_graph(
        self, query: str, purpose: str, limit: int = 10, hops: int = 1
    ) -> dict[str, Any]:
        """Integration hook for planning and autonomous task context builders."""
        if purpose not in {"planning", "autonomous"}:
            raise ValueError("purpose must be 'planning' or 'autonomous'")
        graph = await self.get_relevant_knowledge_graph(query, limit, hops)
        return {"purpose": purpose, **graph}

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
            "SELECT id, title, created_at, updated_at, metadata, pinned, archived, workspace "
            "FROM conversations WHERE id = ?",
            (conversation_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def update_conversation(
        self, conversation_id: str, *, title: str | None = None,
        pinned: bool | None = None, archived: bool | None = None,
        workspace: str | None = None,
    ) -> bool:
        """Update optional conversation fields. Returns True if found."""
        assert self._db is not None
        fields = {"title": title, "pinned": None if pinned is None else int(pinned),
                  "archived": None if archived is None else int(archived),
                  "workspace": workspace}
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
