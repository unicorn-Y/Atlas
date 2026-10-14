"""Tests for MemoryStore — SQLite + FTS5 conversation storage."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from atlas.memory import MemoryStore
from tests.fakes.session_store import (
    save_memory_fixture_message,
    seed_session_messages,
)


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

    async def test_branch_summary_is_upserted_after_its_fork_point(self, store: MemoryStore) -> None:
        parent = await store.create_conversation("parent")
        fork_point = await store.save_message(parent, "user", "fork here")
        await store.save_message(parent, "assistant", "later parent message")
        first = await store.save_branch_summary(parent, "child", fork_point, "first summary")
        second = await store.save_branch_summary(parent, "child", fork_point, "updated summary")
        messages = await store.get_conversation_messages(parent)
        summary = next(item for item in messages if item["id"] == first)
        assert first == second
        assert summary["content"] == "updated summary"
        assert summary["metadata"]["fork_message_id"] == fork_point

        # Non-existent conversation
        ok = await store.update_conversation_title("nonexistent", "X")
        assert ok is False

    async def test_delete_conversation(self, store: MemoryStore) -> None:
        conv_id = await store.create_conversation("To Delete")
        await store.save_message(conv_id, "user", "msg1")
        await store.save_message(conv_id, "assistant", "msg2")
        await seed_session_messages(conv_id, [
            ("user", "msg1"), ("assistant", "msg2"),
        ])

        ok = await store.delete_conversation(conv_id)
        assert ok is True

        # Conversation should be gone
        assert await store.get_conversation(conv_id) is None
        # Messages should be gone too
        msgs = await store.get_conversation_messages(conv_id)
        assert len(msgs) == 0
        from atlas.config import DATA_ROOT
        from atlas.engine.session_sync import read_session_all_messages

        assert read_session_all_messages(DATA_ROOT / "engine", conv_id) == []

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
        assert msgs[0]["metadata"] == {"model": "claude-sonnet-4"}

    async def test_invalid_legacy_message_metadata_becomes_empty_dict(
        self, store: MemoryStore
    ) -> None:
        conv_id = await store.create_conversation("Legacy metadata")
        msg_id = await store.save_message(conv_id, "assistant", "Response")
        assert store._db is not None
        await store._db.execute(
            "UPDATE messages SET metadata = ? WHERE id = ?", ("not-json", msg_id)
        )
        await store._db.commit()

        [message] = await store.get_conversation_messages(conv_id)
        assert message["metadata"] == {}

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

    async def test_session_search_returns_hits_with_context_and_title(
        self, store: MemoryStore,
    ) -> None:
        conv_id = await store.create_conversation("Bugfix session")
        await save_memory_fixture_message(
            store, conv_id, "user", "the login endpoint returns 500",
        )
        await save_memory_fixture_message(
            store, conv_id, "assistant", "fixed the token refresh order",
        )
        await save_memory_fixture_message(store, conv_id, "user", "great, thanks")
        other = await store.create_conversation("Other talk")
        await save_memory_fixture_message(
            store, other, "user", "completely unrelated chat about cookies",
        )

        hits = await store.session_search("login endpoint")
        assert hits, "expected at least one hit"
        top = hits[0]
        assert top["conversation_title"] == "Bugfix session"
        assert top["conversation_id"] == conv_id
        assert any("login" in message["content"] for message in top["context"])
        assert any(message["role"] == "assistant" for message in top["context"])

    async def test_session_search_chinese_and_hostile_queries(self, store: MemoryStore) -> None:
        conv_id = await store.create_conversation("中文会话")
        await save_memory_fixture_message(
            store, conv_id, "user", "目标寻址混合输入验证通过",
        )

        hits = await store.session_search("目标寻址")
        assert hits and any("目标寻址" in hit["content"] for hit in hits)

        garbage = await store.session_search("' AND 1=1 -- OR *(")
        assert isinstance(garbage, list)

    async def test_session_search_empty_query_returns_empty(self, store: MemoryStore) -> None:
        assert await store.session_search("") == []
        assert await store.session_search("   ") == []


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Retired memory tables
# ---------------------------------------------------------------------------


async def test_retired_memory_tables_are_dropped(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE facts (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("CREATE TABLE goal_knowledge (id TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO facts VALUES ('k', 'v')")
    store = MemoryStore(db_path=db_path)
    await store.init()
    await store.close()
    with sqlite3.connect(db_path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "facts" not in tables and "goal_knowledge" not in tables
    assert "conversations" in tables
