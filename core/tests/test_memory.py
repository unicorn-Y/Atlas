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
        store = MemoryStore(db_path=db_path)
        await store.init()
        try:
            facts = await store.list_facts()
            assert facts == []
            columns = await store._db.execute("PRAGMA table_info(facts)")
            assert "source_conversation_id" in {
                row["name"] for row in await columns.fetchall()
            }
        finally:
            await store.close()
