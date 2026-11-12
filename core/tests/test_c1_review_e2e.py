"""Independent C1 regressions through the real Hermes loop and scripted HTTP."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from atlas.agent import AgentOrchestrator, AgentRunContext
from atlas.engine.atlas_runtime import AtlasRuntime
from atlas.tools.local_execution import LocalExecutionRuntime
from tests.fakes.fake_llm_provider import FakeLLMServer, Text, ToolCall, write_atlas_home


async def run_script(tmp_path, monkeypatch, script, *, history=None, hermes_config="", configure_agent=None, **options):
    class FixtureConfig(dict):
        db_path = tmp_path / "store.db"
    monkeypatch.setattr("atlas.config.get_config", lambda: FixtureConfig({
        "tools.servers": {}, "tools.auto_start": [], "agent.verify_before_stop": True,
    }))
    with FakeLLMServer(script) as fake:
        write_atlas_home(tmp_path / "engine", fake.base_url)
        if hermes_config:
            config_path = tmp_path / "engine/config.yaml"
            config_path.write_text(config_path.read_text().replace("api_max_retries: 1", hermes_config), encoding="utf-8")
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "engine"))
        models = SimpleNamespace(
            current_model="fake-model", current_litellm_model="fake-model",
            gateway_base_url=fake.base_url, _api_key="sk-fake-e2e",
            list_models=lambda: [{"id": "fake-model", "max_output_tokens": 512}],
        )
        mcp = MagicMock()
        mcp.get_tools_for_llm.return_value = []
        mcp.list_tools.return_value = []
        mcp.tool_count = 0
        local = LocalExecutionRuntime()
        agent = AgentOrchestrator(models, MagicMock(), mcp_client=mcp, local_execution=local)
        if configure_agent:
            configure_agent(agent)
        ctx = AgentRunContext(cancel_event=asyncio.Event(), run_id="review-run",
            conversation_id="review-session", workspace=str(tmp_path), **options)
        try:
            events = [item async for item in AtlasRuntime(data_dir=tmp_path, model_manager=models).run_turn(
                message="Perform the fixture task", conversation_id=ctx.conversation_id,
                workspace=str(tmp_path), history=history or [], atlas_agent=agent, atlas_context=ctx,
            )]
            return events, fake.main_requests(), ctx
        finally:
            await local.shutdown()


@pytest.mark.asyncio
async def test_bound_file_tools_keep_pagination_regex_and_replace_all(tmp_path, monkeypatch):
    target = tmp_path / "sample.txt"
    target.write_bytes(b"first\ncat cat\nthird\n")
    events, requests, _ = await run_script(tmp_path, monkeypatch, [
        ToolCall("read_file", {"path": str(target), "offset": 2, "limit": 1}),
        ToolCall("search_files", {"path": str(tmp_path), "pattern": "c.t", "target": "content"}),
        ToolCall("patch", {"path": str(target), "old_string": "cat", "new_string": "dog", "replace_all": True}),
        Text("done"),
    ])
    assert target.read_bytes() == b"first\ndog dog\nthird\n"
    first_read = [row for row in requests[1]["messages"] if row["role"] == "tool"][-1]["content"]
    assert "cat cat" in first_read and "first" not in first_read and "third" not in first_read
    search = [row for row in requests[2]["messages"] if row["role"] == "tool"][-1]["content"]
    assert "cat cat" in search


