import pytest

from tests.test_c1_review_e2e import run_script
from tests.fakes.fake_llm_provider import Text, ToolCall


@pytest.mark.asyncio
async def test_real_inline_todos_update_atlas_store_and_frontend_event(tmp_path, monkeypatch):
    events, _, ctx = await run_script(tmp_path, monkeypatch, [
        ToolCall("tool_call", {"calls": [{"name": "todo_list", "arguments": {"todos": [{"id": "task", "content": "fixture task", "status": "in_progress"}]}}]}),
        Text("todo saved"),
    ])
    assert ctx.todo_store.snapshot()["todos"], [row.get("content") for row in events[-1]["result"]["messages"] if row.get("role") == "tool"]
    assert ctx.todo_store.snapshot()["todos"][0]["text"] == "fixture task"
    assert ctx.hermes_agent._todo_store.read()[0]["content"] == "fixture task"
    queued = []
    while not ctx.event_queue.empty():
        queued.append(ctx.event_queue.get_nowait())
    assert any(item["type"] == "run_todos" for item in queued)


@pytest.mark.asyncio
async def test_eager_inline_todo_updates_atlas(tmp_path, monkeypatch):
    _, _, ctx = await run_script(tmp_path, monkeypatch, [
        ToolCall("todo_list", {"todos": [{"id": "eager", "content": "inline fixture", "status": "pending"}]}),
        Text("saved"),
    ], hermes_config="api_max_retries: 1\ntools:\n  tool_search:\n    defer: []")
    assert ctx.todo_store.snapshot()["todos"][0]["text"] == "inline fixture"
