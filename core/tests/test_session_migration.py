from __future__ import annotations

import asyncio
import hashlib
import sqlite3
import threading
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from atlas.engine.session_sync import (
    capture_session,
    delete_session,
    fork_session_through_turn,
    list_branch_tree,
    migrate_legacy_sessions,
    read_session_all_messages,
    read_session_messages,
    restore_session,
    rewind_user_turn,
    begin_session_migration,
    finish_session_migration,
)
from atlas.memory import MemoryStore


def _configure(tmp_path: Path, monkeypatch):
    import atlas.config as config

    atlas_db = tmp_path / "atlas.sqlite3"
    monkeypatch.setattr(config, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(config, "get_config", lambda: SimpleNamespace(db_path=atlas_db))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "engine"))
    return atlas_db


def _file_hashes(path: Path) -> dict[str, str]:
    return {
        item.name: hashlib.sha256(item.read_bytes()).hexdigest()
        for item in (path, Path(f"{path}-wal"), Path(f"{path}-shm"))
        if item.exists()
    }


def _close_memory_at_teardown(memory: MemoryStore, request: pytest.FixtureRequest) -> None:
    def close() -> None:
        if memory._db is not None:
            asyncio.run(memory.close())

    request.addfinalizer(close)


def test_migration_imports_full_atlas_shape_idempotently_and_doctor_stays_clean(
    tmp_path: Path, monkeypatch, request: pytest.FixtureRequest,
) -> None:
    atlas_db = _configure(tmp_path, monkeypatch)
    home = tmp_path / "engine"
    memory = MemoryStore(db_path=atlas_db)
    _close_memory_at_teardown(memory, request)

    async def seed() -> tuple[str, str, list[str], list[str]]:
        await memory.init()
        source = await memory.create_conversation("中文分叉源")
        child = await memory.create_conversation("中文分叉源")
        await memory._db.execute(
            "UPDATE conversations SET created_at = ? WHERE id = ?",
            ("2026-10-01 12:34:56", source),
        )
        ids = [
            await memory.save_message(source, "user", "请保留中文与工具配对。"),
            await memory.save_message(source, "assistant", "", {
                "tool_calls": [{"id": "call-文件", "type": "function", "function": {
                    "name": "read_file", "arguments": "{\"path\":\"说明.md\"}",
                }}],
            }),
            await memory.save_message(source, "tool", "工具返回：已读取。", {
                "tool_name": "read_file", "tool_call_id": "call-文件",
            }),
            await memory.save_message(source, "user", '[{"type":"image_url","url":"data:image/png;base64,fixture"}]'),
            await memory.save_message(source, "assistant", "回退后保留的答复。"),
        ]
        await memory._db.execute(
            "UPDATE messages SET created_at = ? WHERE id = ?",
            ("2026-10-01T13:34:56+01:00", ids[0]),
        )
        await memory._db.execute(
            "UPDATE messages SET created_at = ? WHERE id = ?",
            ("1760000000.25", ids[1]),
        )
        await memory._db.commit()
        child_ids = [
            await memory.save_message(child, "user", "分叉里的中文问题。"),
            await memory.save_message(child, "assistant", "分叉回答。"),
        ]
        await memory.update_conversation(
            child, parent_conversation_id=source, fork_message_id=ids[0],
        )
        return source, child, ids, child_ids

    source_id, child_id, source_ids, child_ids = asyncio.run(seed())
    report = asyncio.run(migrate_legacy_sessions(home, memory))
    assert (report.status, report.imported_sessions, report.imported_messages) == (
        "ready", 2, 7,
    ), report.error
    source = read_session_all_messages(home, source_id)
    assert len(source) == 5
    assert [item["id"] for item in source] == source_ids
    assert source[0]["content"] == "请保留中文与工具配对。"
    assert source[0]["created_at"] == "2026-10-01T12:34:56+00:00"
    assert source[1]["created_at"] == datetime.fromtimestamp(1760000000.25, UTC).isoformat()
    assert capture_session(home, source_id)["started_at"] == datetime(
        2026, 10, 1, 12, 34, 56, tzinfo=UTC,
    ).timestamp()
    assert source[1]["metadata"]["tool_calls"][0]["id"] == "call-文件"
    assert source[2]["metadata"]["tool_call_id"] == "call-文件"
    assert source[3]["content"].startswith("[{\"type\":\"image_url\"")

    first_page = read_session_messages(home, source_id, limit=2)
    assert len(first_page) == 2
    assert read_session_messages(home, source_id, limit=2, before_id=source[-1]["id"]) == source[2:4]

    conversations = asyncio.run(memory.list_conversations(limit=None))
    assert len(conversations) == 2
    assert {item["title"] for item in conversations} == {"中文分叉源"}
    import atlas_state

    with atlas_state.SessionDB(db_path=home / "state.db") as db:
        imported_titles = [row[0] for row in db._read_all(
            "SELECT title FROM sessions WHERE id IN (?, ?)", (source_id, child_id),
        )]
    assert len(set(imported_titles)) == 2
    tree = list_branch_tree(home, child_id)
    assert [item["id"] for item in tree] == [source_id, child_id]
    assert tree[1]["branch_message_id"] == source_ids[0]
    assert [item["id"] for item in read_session_all_messages(home, child_id)] == child_ids

    again = asyncio.run(migrate_legacy_sessions(home, memory))
    assert again.status == "ready" and again.imported_sessions == 0
    assert again.ignored_existing_sessions == 2
    from atlas.cli import _check_sessions

    assert _check_sessions()["ok"] is True

    exported = capture_session(home, source_id)
    assert exported is not None
    delete_session(home, source_id)
    restore_session(home, exported)
    assert [item["id"] for item in read_session_all_messages(home, source_id)] == source_ids
    assert _check_sessions()["ok"] is True

    async def add_fork_metadata():
        fork_id = await memory.create_conversation("fork-after-migration")
        await memory.update_conversation(
            fork_id, parent_conversation_id=source_id, fork_message_id=source_ids[0],
        )
        return fork_id

    fork_id = asyncio.run(add_fork_metadata())
    fork_session_through_turn(home, source_id, fork_id, 1, branch_message_id=source_ids[0])
    assert _check_sessions()["ok"] is True
    snapshot = rewind_user_turn(home, source_id, 1)
    assert snapshot is not None
    assert _check_sessions()["ok"] is True
    restore_session(home, snapshot)
    assert _check_sessions()["ok"] is True
    assert asyncio.run(memory.delete_conversation(fork_id))
    assert _check_sessions()["ok"] is True
    asyncio.run(memory.close())


def test_session_search_reads_sessiondb_when_legacy_messages_are_empty(
    tmp_path: Path, monkeypatch,
) -> None:
    atlas_db = _configure(tmp_path, monkeypatch)
    home = tmp_path / "engine"
    memory = MemoryStore(db_path=atlas_db)

    async def seed_and_verify():
        await memory.init()
        try:
            conversation_id = await memory.create_conversation("canonical-only")
            import atlas_state

            with atlas_state.SessionDB(db_path=home / "state.db") as db:
                db.ensure_session(conversation_id, "api_server")
                db.append_message(
                    conversation_id, "user", content="I prefer short answers.",
                )
                message_id = str(db.get_messages(conversation_id)[-1]["message_uid"])
            hits = await memory.session_search(
                "short answers", conversation_ids=[conversation_id],
            )
            assert len(hits) == 1
            assert hits[0]["id"] == message_id
            assert hits[0]["context"][0]["id"] == message_id
        finally:
            await memory.close()

    asyncio.run(seed_and_verify())
def test_existing_sessiondb_history_is_authoritative_and_counted_as_ignored(
    tmp_path: Path, monkeypatch,
) -> None:
    atlas_db = _configure(tmp_path, monkeypatch)
    home = tmp_path / "engine"
    memory = MemoryStore(db_path=atlas_db)

    async def seed():
        await memory.init()
        conversation_id = await memory.create_conversation("existing")
        await memory.save_message(conversation_id, "user", "Atlas legacy content")
        return conversation_id

    conversation_id = asyncio.run(seed())
    import atlas_state

    with atlas_state.SessionDB(db_path=home / "state.db") as db:
        db.ensure_session(conversation_id, "api_server")
        db.append_message(conversation_id, "user", content="Canonical Hermes content")
    report = asyncio.run(migrate_legacy_sessions(home, memory))
    assert report.status == "ready"
    assert report.imported_sessions == 0
    assert report.ignored_existing_sessions == 1
    assert [item["content"] for item in read_session_all_messages(home, conversation_id)] == [
        "Canonical Hermes content",
    ]
    from atlas.cli import _check_sessions

    assert _check_sessions()["ok"] is True
    asyncio.run(memory.close())


def test_failed_mid_import_leaves_both_original_databases_byte_identical(tmp_path: Path, monkeypatch) -> None:
    atlas_db = _configure(tmp_path, monkeypatch)
    home = tmp_path / "engine"
    home.mkdir()
    memory = MemoryStore(db_path=atlas_db)

    async def seed():
        await memory.init()
        conversation = await memory.create_conversation("注入失败")
        await memory.save_message(conversation, "user", "此正文不得出现在错误中。")
        return conversation

    conversation_id = asyncio.run(seed())
    import atlas_state

    with atlas_state.SessionDB(db_path=home / "state.db") as db:
        db.ensure_session("preexisting", "api_server")
    atlas_before = _file_hashes(atlas_db)
    hermes_before = _file_hashes(home / "state.db")
    original = atlas_state.SessionDB._import_session_row

    def fail_after_staging_row(self, conn, raw, messages, session_id):
        original(self, conn, raw, messages, session_id)
        raise RuntimeError("injected import failure")

    monkeypatch.setattr(atlas_state.SessionDB, "_import_session_row", fail_after_staging_row)
    report = asyncio.run(migrate_legacy_sessions(home, memory))
    assert report.status == "failed"
    assert "此正文不得出现在错误中" not in (report.error or "")
    assert _file_hashes(atlas_db) == atlas_before
    assert _file_hashes(home / "state.db") == hermes_before
    with closing(sqlite3.connect(f"file:{(home / 'state.db').as_posix()}?mode=ro", uri=True)) as conn:
        ids = {row[0] for row in conn.execute("SELECT id FROM sessions")}
    assert ids == {"preexisting"}
    try:
        read_session_all_messages(home, conversation_id)
    except RuntimeError as exc:
        assert "历史记录已保护" in str(exc)
    else:
        raise AssertionError("failed migration must hold transcript reads closed")
    asyncio.run(memory.close())


def test_invalid_legacy_timestamp_fails_closed_without_mutating_either_database(
    tmp_path: Path, monkeypatch, request: pytest.FixtureRequest,
) -> None:
    atlas_db = _configure(tmp_path, monkeypatch)
    home = tmp_path / "engine"
    memory = MemoryStore(db_path=atlas_db)
    _close_memory_at_teardown(memory, request)

    async def seed() -> str:
        await memory.init()
        conversation_id = await memory.create_conversation("invalid timestamp")
        message_id = await memory.save_message(conversation_id, "user", "test fixture body")
        await memory._db.execute(
            "UPDATE messages SET created_at = ? WHERE id = ?",
            ("not-a-timestamp", message_id),
        )
        await memory._db.commit()
        return conversation_id

    conversation_id = asyncio.run(seed())
    import atlas_state

    with atlas_state.SessionDB(db_path=home / "state.db") as db:
        db.ensure_session("preexisting", "api_server")
    atlas_before = _file_hashes(atlas_db)
    state_before = _file_hashes(home / "state.db")
    report = asyncio.run(migrate_legacy_sessions(home, memory))
    assert report.status == "failed" and "import" in (report.error or "")
    assert _file_hashes(atlas_db) == atlas_before
    assert _file_hashes(home / "state.db") == state_before
    with pytest.raises(RuntimeError, match="历史记录已保护"):
        read_session_all_messages(home, conversation_id)


def test_cancelled_migration_releases_only_its_home_barrier(tmp_path: Path, monkeypatch) -> None:
    atlas_db = _configure(tmp_path, monkeypatch)
    home = tmp_path / "engine"
    other_home = tmp_path / "other-engine"
    memory = MemoryStore(db_path=atlas_db)

    async def run_case():
        await memory.init()
        conversation_id = await memory.create_conversation("cancel gate")
        await memory.save_message(conversation_id, "user", "pending migration")
        import atlas_state

        with atlas_state.SessionDB(db_path=other_home / "state.db") as db:
            db.create_session("other-home", "api_server")
        started = asyncio.Event()

        async def wait_inside_migration(*, limit=None):
            started.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(memory, "list_conversations", wait_inside_migration)
        begin_session_migration(home)
        task = asyncio.create_task(migrate_legacy_sessions(home, memory))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run_case())
    try:
        read_session_all_messages(home, "any-session")
    except RuntimeError as exc:
        assert "历史记录已保护" in str(exc)
    else:
        raise AssertionError("cancelled migration must fail closed for its own home")
    assert read_session_all_messages(other_home, "other-home") == []
    asyncio.run(memory.close())


def test_second_begin_reuses_event_held_by_waiting_reader(tmp_path: Path) -> None:
    import atlas.session_migration_gate as gate

    class ObservedEvent:
        def __init__(self):
            self.waiting = threading.Event()
            self.released = threading.Event()

        def wait(self):
            self.waiting.set()
            self.released.wait()

        def set(self):
            self.released.set()

    home = tmp_path / "shared-engine"
    begin_session_migration(home)
    key = gate._migration_key(home)
    observed = ObservedEvent()
    with gate._states_lock:
        gate._states[key] = (observed, "running")
    reader = threading.Thread(target=gate.require_migration_settled, args=(home,))
    reader.start()
    assert observed.waiting.wait(timeout=2)

    begin_session_migration(home)
    with gate._states_lock:
        assert gate._states[key][0] is observed
    finish_session_migration(home, "ready")
    reader.join(timeout=2)
    assert not reader.is_alive()


def test_publish_failure_restores_original_main_and_sidecars_and_fails_gate(
    tmp_path: Path, monkeypatch, request: pytest.FixtureRequest,
) -> None:
    atlas_db = _configure(tmp_path, monkeypatch)
    home = tmp_path / "engine"
    memory = MemoryStore(db_path=atlas_db)
    _close_memory_at_teardown(memory, request)

    async def seed():
        await memory.init()
        conversation_id = await memory.create_conversation("publish failure")
        await memory.save_message(conversation_id, "user", "new legacy transcript")
        return conversation_id

    conversation_id = asyncio.run(seed())
    import atlas_state
    import atlas.engine.session_sync as session_sync

    state_db = home / "state.db"
    with atlas_state.SessionDB(db_path=state_db) as db:
        db.ensure_session("preexisting", "api_server")
    original_hash = hashlib.sha256(state_db.read_bytes()).hexdigest()
    real_replace = session_sync.os.replace
    sidecars = {"-wal": b"old-wal-sidecar", "-shm": b"old-shm-sidecar"}
    created_sidecars = False

    def fail_final_publish(source, destination):
        nonlocal created_sidecars
        source_path, destination_path = Path(source), Path(destination)
        if source_path == state_db and destination_path.name == "original.db" and not created_sidecars:
            for suffix, content in sidecars.items():
                Path(f"{state_db}{suffix}").write_bytes(content)
            created_sidecars = True
        if (source_path.name == "state.db" and destination_path == state_db
                and ".session-migration-" in str(source_path.parent)):
            raise OSError("injected final publish failure")
        return real_replace(source, destination)

    monkeypatch.setattr(session_sync.os, "replace", fail_final_publish)
    report = asyncio.run(migrate_legacy_sessions(home, memory))
    assert report.status == "failed" and "publish" in (report.error or "")
    assert created_sidecars
    assert hashlib.sha256(state_db.read_bytes()).hexdigest() == original_hash
    assert {suffix: Path(f"{state_db}{suffix}").read_bytes() for suffix in sidecars} == sidecars
    try:
        read_session_all_messages(home, conversation_id)
    except RuntimeError as exc:
        assert "历史记录已保护" in str(exc)
    else:
        raise AssertionError("failed publish must close transcript access")
    asyncio.run(memory.close())
