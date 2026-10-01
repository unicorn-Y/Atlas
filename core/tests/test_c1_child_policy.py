import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from atlas.engine.tool_permissions import intersect_tool_allow, tool_allowed
from tests.test_c1_review_e2e import run_script
from tests.fakes.fake_llm_provider import Text, ToolCall


def test_child_whitelist_intersection_preserves_parent_and_aliases():
    allowed = intersect_tool_allow(["read_*", "local_file"], ["read_file", "terminal"])
    assert allowed == ["read_file"]
    assert intersect_tool_allow([], ["terminal"]) == []
    assert intersect_tool_allow(["read_file"], None) == ["read_file"]
    assert tool_allowed("write_file", ["local_file"])
    assert not tool_allowed("write_file", ["*"], ["local_*"])
    assert tool_allowed("delegate_parallel", ["delegate_task"])
    assert not tool_allowed("delegate_parallel", ["*"], ["delegate_task"])
    assert tool_allowed("todo", ["todo_list"])
    assert tool_allowed("todo_list", ["todo"])
    assert not tool_allowed("todo", ["*"], ["todo_list"])
    assert not tool_allowed("write_file", ["todo_list"])


@pytest.mark.asyncio
async def test_inline_delegate_dispatches_through_atlas_lifecycle(tmp_path, monkeypatch):
    delegate = AsyncMock(return_value={"status": "completed", "result": "child result"})
    def configure(agent):
        agent._delegation = SimpleNamespace(delegate_task=delegate)
    events, requests, _ = await run_script(tmp_path, monkeypatch, [
        ToolCall("delegate_task", {"goal": "fixture child", "background": False}),
        Text("parent completed"),
    ], configure_agent=configure, tool_allow=["delegate_task", "read_file"])
    assert delegate.await_count == 1
    child_options = delegate.call_args.kwargs["atlas_options"]
    assert child_options["tool_allow"] == ["delegate_task", "read_file"]
    assert not delegate.call_args.kwargs["background"]


@pytest.mark.asyncio
async def test_native_child_restrictions_block_direct_and_deferred_calls(tmp_path, monkeypatch):
    path = tmp_path / "restricted.txt"
    events, requests, _ = await run_script(tmp_path, monkeypatch, [
        ToolCall("write_file", {"path": str(path), "content": "forbidden"}),
        Text("blocked"),
    ], tool_allow=["read_file"])
    assert not path.exists()
    assert any("不允许" in str(row.get("content")) for row in requests[1]["messages"] if row["role"] == "tool")
