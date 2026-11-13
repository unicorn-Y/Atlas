import pytest

from atlas.agent.todo_state import TodoStore
from atlas.engine.session_sync import read_session_events


@pytest.mark.unit
def test_todo_writes_emit_durable_snapshots_and_restore_without_rewriting():
    recorded = []
    store = TodoStore()
    store.bind_durable_writer(recorded.append)

    snapshot = store.write([{"id": "a", "content": "ship", "status": "in_progress"}])

    assert recorded == [snapshot]
    restored = TodoStore()
    restored.restore(recorded[0])
    assert restored.snapshot() == snapshot
    assert restored.snapshot()["revision"] == snapshot["revision"]


@pytest.mark.unit
def test_todo_write_rolls_back_in_memory_if_durable_append_fails():
    store = TodoStore()
    store.write([{"id": "a", "content": "old", "status": "pending"}])
    before = store.snapshot()
    store.bind_durable_writer(lambda _snapshot: (_ for _ in ()).throw(OSError("disk full")))

    with pytest.raises(OSError, match="disk full"):
        store.write([{"id": "b", "content": "new", "status": "pending"}])

    assert store.snapshot() == before


@pytest.mark.unit
@pytest.mark.asyncio
async def test_todo_store_round_trips_session_event_log(tmp_path):
    store = TodoStore()
    await store.bind_session_events(tmp_path / "engine", "todo-session")
    expected = store.write([{"id": "persisted", "content": "finish", "status": "pending"}])

    events = read_session_events(tmp_path / "engine", "todo-session")
    restored = TodoStore()
    await restored.bind_session_events(tmp_path / "engine", "todo-session")

    assert events[-1]["event_type"] == "todo.updated"
    assert restored.snapshot() == expected
