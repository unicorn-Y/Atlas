"""Tests for MemoryStore — SQLite + FTS5 conversation and fact storage."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from atlas.memory import MemoryStore


@pytest.fixture
async def store(tmp_path: Path) -> MemoryStore:
    """Create a fresh MemoryStore backed by a temp SQLite file."""
    db_path = tmp_path / "test.db"
    s = MemoryStore(db_path=db_path)
    await s.init()
    yield s
    await s.close()


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------

class TestConversations:
    async def test_create_and_list(self, store: MemoryStore) -> None:
        conv_id = await store.create_conversation("Hello World")
        assert conv_id
        convs = await store.list_conversations()
        assert len(convs) == 1
        assert convs[0]["id"] == conv_id
        assert convs[0]["title"] == "Hello World"

    async def test_auto_create_on_save_message(self, store: MemoryStore) -> None:
        msg_id = await store.save_message("conv-auto", "user", "Hi there, auto-create")
        assert msg_id
        convs = await store.list_conversations()
        assert any(c["id"] == "conv-auto" for c in convs)

    async def test_get_conversation(self, store: MemoryStore) -> None:
        conv_id = await store.create_conversation("Test Conv")
        conv = await store.get_conversation(conv_id)
        assert conv is not None
        assert conv["title"] == "Test Conv"

        missing = await store.get_conversation("nonexistent")
        assert missing is None

    async def test_update_title(self, store: MemoryStore) -> None:
        conv_id = await store.create_conversation("Old Title")
        ok = await store.update_conversation_title(conv_id, "New Title")
        assert ok is True

        conv = await store.get_conversation(conv_id)
        assert conv["title"] == "New Title"

        # Non-existent conversation
        ok = await store.update_conversation_title("nonexistent", "X")
        assert ok is False

    async def test_delete_conversation(self, store: MemoryStore) -> None:
        conv_id = await store.create_conversation("To Delete")
        await store.save_message(conv_id, "user", "msg1")
        await store.save_message(conv_id, "assistant", "msg2")

        ok = await store.delete_conversation(conv_id)
        assert ok is True

        # Conversation should be gone
        assert await store.get_conversation(conv_id) is None
        # Messages should be gone too
        msgs = await store.get_conversation_messages(conv_id)
        assert len(msgs) == 0

        # Deleting again returns False
        ok = await store.delete_conversation(conv_id)
        assert ok is False


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

class TestMessages:
    async def test_save_and_get(self, store: MemoryStore) -> None:
        conv_id = await store.create_conversation("Chat")
        await store.save_message(conv_id, "user", "Hello")
        await store.save_message(conv_id, "assistant", "Hi!")

        msgs = await store.get_conversation_messages(conv_id)
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "Hello"
        assert msgs[1]["role"] == "assistant"
        assert msgs[1]["content"] == "Hi!"

    async def test_message_with_metadata(self, store: MemoryStore) -> None:
        conv_id = await store.create_conversation("Meta")
        await store.save_message(
            conv_id, "assistant", "Response",
            metadata={"model": "claude-sonnet-4"},
        )
        msgs = await store.get_conversation_messages(conv_id)
        assert len(msgs) == 1
        # metadata is stored as JSON string
        import json
        meta = json.loads(msgs[0]["metadata"])
        assert meta["model"] == "claude-sonnet-4"

    async def test_message_limit(self, store: MemoryStore) -> None:
        conv_id = await store.create_conversation("Limit")
        for i in range(10):
            await store.save_message(conv_id, "user", f"msg-{i}")
        msgs = await store.get_conversation_messages(conv_id, limit=3)
        assert len(msgs) == 3


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

class TestSearch:
    async def test_fts_search(self, store: MemoryStore) -> None:
        conv_id = await store.create_conversation("Search Test")
        await store.save_message(conv_id, "user", "Tell me about quantum computing")
        await store.save_message(conv_id, "assistant", "Quantum computing uses qubits")
        await store.save_message(conv_id, "user", "What about classical computing?")

        results = await store.search("quantum")
        assert len(results) >= 1
        assert any("quantum" in r["content"].lower() for r in results)

    async def test_search_no_results(self, store: MemoryStore) -> None:
        conv_id = await store.create_conversation("Empty")
        await store.save_message(conv_id, "user", "Hello")
        results = await store.search("xyznonexistent123")
        assert len(results) == 0


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------

class TestFacts:
    async def test_set_and_get(self, store: MemoryStore) -> None:
        await store.set_fact("user_name", "Atlas User")
        val = await store.get_fact("user_name")
        assert val == "Atlas User"

    async def test_upsert(self, store: MemoryStore) -> None:
        await store.set_fact("key1", "value1")
        await store.set_fact("key1", "value2")
        val = await store.get_fact("key1")
        assert val == "value2"

    async def test_get_missing(self, store: MemoryStore) -> None:
        val = await store.get_fact("nonexistent")
        assert val is None

    async def test_list_facts(self, store: MemoryStore) -> None:
        await store.set_fact("a", "1", category="prefs")
        await store.set_fact("b", "2", category="prefs")
        await store.set_fact("c", "3", category="project")

        all_facts = await store.list_facts()
        assert len(all_facts) == 3

        prefs = await store.list_facts(category="prefs")
        assert len(prefs) == 2

    async def test_delete_fact(self, store: MemoryStore) -> None:
        await store.set_fact("temp", "value")
        ok = await store.delete_fact("temp")
        assert ok is True
        assert await store.get_fact("temp") is None

        ok = await store.delete_fact("nonexistent")
        assert ok is False


class TestExtractedMemories:
    async def test_explicit_memory_is_stored_and_retrievable(self, store: MemoryStore) -> None:
        extracted = await store.extract_memories(
            "conversation-1",
            "Please keep this in mind.\nremember: timezone = Asia/Hong_Kong",
        )

        assert extracted == [{
            "key": "timezone",
            "value": "Asia/Hong_Kong",
            "category": "extracted",
            "source_conversation_id": "conversation-1",
        }]
        assert await store.get_fact("timezone") == "Asia/Hong_Kong"
        context = await store.get_agent_context("What timezone do I use?")
        assert len(context) == 1
        assert context[0]["key"] == "timezone"
        assert context[0]["value"] == "Asia/Hong_Kong"
        assert context[0]["source_conversation_id"] == "conversation-1"


class TestAgentContextRanking:
    async def test_active_context_is_bounded_and_deterministic(
        self, store: MemoryStore
    ) -> None:
        await store.set_fact("preferred_editor_language", "TypeScript")
        await store.set_fact("preferred_spoken_language", "Spanish")
        await store.set_fact("user_timezone", "Asia/Hong_Kong")

        first = await store.get_active_context("Which language for the editor?", limit=1)
        second = await store.get_active_context("Which language for the editor?", limit=1)

        assert first == second
        assert [fact["key"] for fact in first] == ["preferred_editor_language"]

    async def test_active_context_carries_approved_fact_across_conversations(
        self, store: MemoryStore
    ) -> None:
        source_conversation = await store.create_conversation("First session")
        source_message = await store.save_message(
            source_conversation, "user", "We decided to use Python."
        )
        [candidate] = await store.extract_conversation_candidates(source_conversation)
        assert await store.get_active_context("Which language should the project use?") == []
        assert await store.promote_memory_candidate(candidate["id"])

        later_conversation = await store.create_conversation("Later session")
        await store.save_message(
            later_conversation, "user", "Continue work on the project."
        )
        await store.close()
        reopened = MemoryStore(db_path=store._db_path)
        await reopened.init()
        try:
            context = await reopened.get_active_context(
                "Which language should the project use?"
            )
        finally:
            await reopened.close()

        assert [fact["key"] for fact in context] == ["project_decision"]
        assert context[0]["value"] == "Python"
        assert context[0]["source_conversation_id"] == source_conversation
        assert context[0]["source_message_id"] == source_message

    async def test_active_context_excludes_unrelated_and_pending_memories(
        self, store: MemoryStore
    ) -> None:
        await store.set_fact("user_timezone", "Asia/Hong_Kong")
        conversation_id = await store.create_conversation()
        await store.save_message(conversation_id, "user", "Our project uses Python")
        [candidate] = await store.extract_conversation_candidates(conversation_id)

        context = await store.get_active_context("What is my timezone?")

        assert [fact["key"] for fact in context] == ["user_timezone"]
        assert candidate["status"] == "pending"

    async def test_context_ranks_fact_keys_above_value_matches(
        self, store: MemoryStore
    ) -> None:
        await store.set_fact("language", "Spanish")
        await store.set_fact("preferred_editor_language", "English")

        context = await store.get_agent_context(
            "What language should I use in the editor?"
        )

        assert [fact["key"] for fact in context] == [
            "preferred_editor_language", "language"
        ]

    async def test_context_ignores_request_boilerplate_without_memory_terms(
        self, store: MemoryStore
    ) -> None:
        await store.set_fact("timezone", "Asia/Hong_Kong")
        await store.set_fact("generic_note", "I should use it")

        context = await store.get_agent_context("What should I do with it?")

        assert context == []

    async def test_context_ranks_request_terms_above_boilerplate_matches(
        self, store: MemoryStore
    ) -> None:
        await store.set_fact("meeting_notes", "I should use this")
        await store.set_fact("favorite_language", "TypeScript")

        context = await store.get_agent_context("What language should I use?")

        assert [fact["key"] for fact in context] == ["favorite_language"]

    async def test_unmarked_text_is_not_extracted(self, store: MemoryStore) -> None:
        extracted = await store.extract_memories(
            "conversation-1", "My timezone is Asia/Hong_Kong."
        )
        assert extracted == []
        assert await store.list_facts() == []

    async def test_existing_fact_table_is_migrated(self, tmp_path: Path) -> None:
        db_path = tmp_path / "legacy.db"
        with sqlite3.connect(db_path) as db:
            db.execute(
                "CREATE TABLE facts (key TEXT PRIMARY KEY, value TEXT NOT NULL, "
                "category TEXT NOT NULL DEFAULT 'general', "
                "created_at TEXT NOT NULL DEFAULT (datetime('now')), "
                "updated_at TEXT NOT NULL DEFAULT (datetime('now')))"
            )
            db.execute(
                "INSERT INTO facts (key, value, category) "
                "VALUES ('user_timezone', 'Europe/Paris', 'personal')"
            )
        store = MemoryStore(db_path=db_path)
        await store.init()
        try:
            columns = await store._db.execute("PRAGMA table_info(facts)")
            column_names = {row["name"] for row in await columns.fetchall()}
            assert "source_conversation_id" in column_names
            assert "memory_type" in column_names
            [legacy_identity] = await store.list_facts()
            assert legacy_identity["memory_type"] == "identity"
            assert await store.get_agent_context("What timezone do I use?") == []
        finally:
            await store.close()

    async def test_existing_candidate_table_is_migrated_for_superseded_status(
        self, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "legacy-candidates.db"
        with sqlite3.connect(db_path) as db:
            db.execute(
                "CREATE TABLE memory_candidates ("
                "id TEXT PRIMARY KEY, key TEXT NOT NULL, value TEXT NOT NULL, "
                "category TEXT NOT NULL, confidence REAL NOT NULL, "
                "status TEXT NOT NULL DEFAULT 'pending' "
                "CHECK(status IN ('pending', 'approved', 'rejected')), "
                "source_conversation_id TEXT NOT NULL, source_message_id TEXT NOT NULL, "
                "created_at TEXT NOT NULL DEFAULT (datetime('now')), "
                "updated_at TEXT NOT NULL DEFAULT (datetime('now')), "
                "UNIQUE(source_message_id, key, value))"
            )
            db.execute(
                "INSERT INTO memory_candidates (id, key, value, category, confidence, "
                "source_conversation_id, source_message_id) "
                "VALUES ('candidate-1', 'user_timezone', 'UTC', 'personal', 0.9, 'c1', 'm1')"
            )
        store = MemoryStore(db_path=db_path)
        await store.init()
        try:
            [candidate] = await store.list_memory_candidates()
            assert candidate["id"] == "candidate-1"
            await store._db.execute(
                "UPDATE memory_candidates SET status = 'superseded' WHERE id = ?",
                (candidate["id"],),
            )
            await store._db.commit()
            [migrated] = await store.list_memory_candidates()
            assert migrated["status"] == "superseded"
            assert migrated["memory_type"] == "fact"
        finally:
            await store.close()


class TestAutomaticMemoryCandidates:
    async def test_conversation_creates_pending_candidates_without_promoting(
        self, store: MemoryStore
    ) -> None:
        conversation_id = await store.create_conversation()
        await store.save_message(
            conversation_id, "user", "I prefer concise answers."
        )
        await store.save_message(
            conversation_id, "assistant", "I will keep that in mind."
        )

        candidates = await store.extract_conversation_candidates(conversation_id)

        assert len(candidates) == 1
        assert candidates[0]["key"] == "user_preference"
        assert candidates[0]["value"] == "concise answers"
        assert candidates[0]["status"] == "pending"
        assert await store.get_fact("user_preference") is None
        assert await store.list_memory_candidates(status="pending") == candidates

    async def test_explicit_project_decision_becomes_review_candidate(
        self, store: MemoryStore
    ) -> None:
        conversation_id = await store.create_conversation()
        await store.save_message(
            conversation_id, "user", "We decided to use PostgreSQL."
        )

        [candidate] = await store.extract_conversation_candidates(conversation_id)

        assert candidate["key"] == "project_decision"
        assert candidate["value"] == "PostgreSQL"
        assert candidate["category"] == "decision"
        assert candidate["status"] == "pending"
        assert await store.get_fact("project_decision") is None

    async def test_uncertain_and_secret_statements_are_rejected(
        self, store: MemoryStore
    ) -> None:
        conversation_id = await store.create_conversation()
        await store.save_message(
            conversation_id,
            "user",
            "I might prefer concise answers.\nMy API key is sk-secret-value.",
        )

        candidates = await store.extract_conversation_candidates(conversation_id)

        assert candidates == []
        assert await store.list_memory_candidates() == []
        assert await store.list_facts() == []

    async def test_candidate_promotion_requires_explicit_approval_and_persists(
        self, store: MemoryStore
    ) -> None:
        conversation_id = await store.create_conversation()
        await store.save_message(conversation_id, "user", "My timezone is Asia/Hong_Kong.")
        [candidate] = await store.extract_conversation_candidates(conversation_id)

        promoted = await store.promote_memory_candidate(candidate["id"])

        assert promoted is True
        await store.close()
        await store.init()
        assert await store.get_fact(candidate["key"]) == "Asia/Hong_Kong"
        assert (await store.list_memory_candidates())[0]["status"] == "approved"
        assert await store.promote_memory_candidate(candidate["id"]) is False

    async def test_rejected_candidate_never_becomes_fact(self, store: MemoryStore) -> None:
        conversation_id = await store.create_conversation()
        await store.save_message(conversation_id, "user", "Our project uses FastAPI.")
        [candidate] = await store.extract_conversation_candidates(conversation_id)

        assert await store.reject_memory_candidate(candidate["id"])
        assert await store.get_fact(candidate["key"]) is None
        assert (await store.list_memory_candidates())[0]["status"] == "rejected"

    async def test_pending_candidate_conflict_is_reported_without_promotion(
        self, store: MemoryStore
    ) -> None:
        await store.set_fact("project_stack", "Django", confidence=0.95)
        conversation_id = await store.create_conversation()
        await store.save_message(conversation_id, "user", "Our project uses FastAPI.")

        [candidate] = await store.extract_conversation_candidates(conversation_id)
        conflicts = await store.list_memory_conflicts()

        assert len(conflicts) == 1
        assert conflicts[0]["candidate_id"] == candidate["id"]
        assert conflicts[0]["current_value"] == "Django"
        assert conflicts[0]["candidate_value"] == "FastAPI"
        assert await store.get_fact("project_stack") == "Django"

    async def test_older_approved_candidate_cannot_replace_newer_fact(
        self, store: MemoryStore
    ) -> None:
        old_conversation = await store.create_conversation()
        old_message = await store.save_message(
            old_conversation, "user", "My timezone is Europe/Paris."
        )
        new_conversation = await store.create_conversation()
        new_message = await store.save_message(
            new_conversation, "user", "My timezone is Asia/Hong_Kong."
        )
        await store._db.execute(
            "UPDATE messages SET created_at = '2026-01-01 00:00:00' WHERE id = ?",
            (old_message,),
        )
        await store._db.execute(
            "UPDATE messages SET created_at = '2026-02-01 00:00:00' WHERE id = ?",
            (new_message,),
        )
        await store._db.commit()
        [old_candidate] = await store.extract_conversation_candidates(old_conversation)
        [new_candidate] = await store.extract_conversation_candidates(new_conversation)

        assert await store.promote_memory_candidate(new_candidate["id"])
        assert not await store.promote_memory_candidate(old_candidate["id"])
        assert await store.get_fact("user_timezone") == "Asia/Hong_Kong"
        assert (await store.list_memory_candidates())[0]["status"] == "superseded"
        [fact] = await store.list_facts()
        assert fact["source_message_id"] == new_message
        assert fact["confidence"] == 0.9

    async def test_newer_candidate_preserves_superseded_fact_and_provenance(
        self, store: MemoryStore
    ) -> None:
        old_conversation = await store.create_conversation()
        old_message = await store.save_message(
            old_conversation, "user", "Our project uses Django."
        )
        new_conversation = await store.create_conversation()
        new_message = await store.save_message(
            new_conversation, "user", "Our project uses FastAPI."
        )
        await store._db.execute(
            "UPDATE messages SET created_at = '2026-01-01 00:00:00' WHERE id = ?",
            (old_message,),
        )
        await store._db.execute(
            "UPDATE messages SET created_at = '2026-02-01 00:00:00' WHERE id = ?",
            (new_message,),
        )
        await store._db.commit()
        [old_candidate] = await store.extract_conversation_candidates(old_conversation)
        [new_candidate] = await store.extract_conversation_candidates(new_conversation)

        assert await store.promote_memory_candidate(old_candidate["id"])
        assert await store.promote_memory_candidate(new_candidate["id"])
        [old_version] = await store.list_memory_fact_history("project_stack")
        assert old_version["event_type"] == "superseded"
        assert old_version["value"] == "Django"
        assert old_version["source_message_id"] == old_message
        [current] = await store.list_facts()
        assert current["value"] == "FastAPI"
        assert current["source_message_id"] == new_message

    async def test_duplicate_approved_value_is_consolidated(self, store: MemoryStore) -> None:
        first_conversation = await store.create_conversation()
        await store.save_message(first_conversation, "user", "My timezone is Asia/Hong_Kong.")
        second_conversation = await store.create_conversation()
        await store.save_message(second_conversation, "user", "My timezone is Asia/Hong_Kong.")
        [first] = await store.extract_conversation_candidates(first_conversation)
        [second] = await store.extract_conversation_candidates(second_conversation)

        assert await store.promote_memory_candidate(first["id"])
        assert await store.promote_memory_candidate(second["id"])
        [history] = await store.list_memory_fact_history("user_timezone")
        assert history["event_type"] == "duplicate"
        assert history["candidate_id"] == second["id"]
        assert await store.get_fact("user_timezone") == "Asia/Hong_Kong"

    async def test_identity_requires_approval_and_source_evidence_for_context(
        self, store: MemoryStore
    ) -> None:
        conversation_id = await store.create_conversation()
        message_id = await store.save_message(
            conversation_id, "user", "My language is Mandarin."
        )
        [candidate] = await store.extract_conversation_candidates(conversation_id)

        assert candidate["memory_type"] == "identity"
        assert await store.get_agent_context("What language do I use?") == []
        assert await store.promote_memory_candidate(candidate["id"])
        [fact] = await store.get_agent_context("What language do I use?")
        assert fact["memory_type"] == "identity"
        assert fact["source_message_id"] == message_id

        await store.close()
        await store.init()
        [persisted] = await store.get_agent_context("What language do I use?")
        assert persisted["source_message_id"] == message_id

    async def test_identity_candidate_without_original_user_evidence_is_not_promoted(
        self, store: MemoryStore
    ) -> None:
        conversation_id = await store.create_conversation()
        message_id = await store.save_message(
            conversation_id, "user", "My timezone is UTC."
        )
        [candidate] = await store.extract_conversation_candidates(conversation_id)
        await store._db.execute("DELETE FROM messages WHERE id = ?", (message_id,))
        await store._db.commit()

        assert await store.promote_memory_candidate(candidate["id"]) is False
        assert await store.get_fact("user_timezone") is None
        assert (await store.list_memory_candidates())[0]["status"] == "pending"

    async def test_commitment_lifecycle_requires_evidence_and_leaves_active_context(
        self, store: MemoryStore
    ) -> None:
        conversation_id = await store.create_conversation()
        commitment_message = await store.save_message(
            conversation_id, "user", "I commit to deliver the report."
        )
        [candidate] = await store.extract_conversation_candidates(conversation_id)

        assert candidate["memory_type"] == "commitment"
        assert candidate["category"] == "commitment"
        assert await store.get_agent_context("When should I deliver the report?") == []
        assert await store.promote_memory_candidate(candidate["id"])
        [active] = await store.get_agent_context("When should I deliver the report?")
        assert active["commitment_status"] == "active"
        assert active["source_message_id"] == commitment_message

        assert await store.set_commitment_status(
            candidate["key"], "fulfilled", "missing-user-message"
        ) is False
        completion_message = await store.save_message(
            conversation_id, "user", "I completed the report."
        )
        assert await store.set_commitment_status(
            candidate["key"], "fulfilled", completion_message
        )
        assert await store.get_agent_context("When should I deliver the report?") == []
        [event] = await store.list_commitment_history(candidate["key"])
        assert event["previous_status"] == "active"
        assert event["status"] == "fulfilled"
        assert event["source_message_id"] == completion_message
