import pytest

from tests.test_c1_review_e2e import run_script
from tests.fakes.fake_llm_provider import Text, ToolCall


@pytest.mark.asyncio
async def test_native_write_emits_restorable_checkpoint_and_failed_read_is_error(tmp_path, monkeypatch):
    target = tmp_path / "fixture.txt"
    target.write_text("before", encoding="utf-8")
    events, _, ctx = await run_script(tmp_path, monkeypatch, [
        ToolCall("write_file", {"path": str(target), "content": "after"}),
        ToolCall("read_file", {"path": str(tmp_path / "absent.txt")}),
        Text("finished"),
    ])
    queued = []
    while not ctx.event_queue.empty():
        queued.append(ctx.event_queue.get_nowait())
    checkpoints = [item for item in queued if item["type"] == "checkpoint_created"]
    assert checkpoints
    from atlas.agent.checkpoints import ShadowGitCheckpointStore
    store = ShadowGitCheckpointStore()
    store.restore_checkpoint(checkpoints[0]["checkpoint"]["id"])
    assert target.read_text(encoding="utf-8") == "before"
    failed = [item for item in events if item["type"] == "tool_result" and item["name"] == "read_file"]
    assert failed and failed[0]["is_error"], [(item.get("type"), item.get("name"), item.get("is_error")) for item in events]
