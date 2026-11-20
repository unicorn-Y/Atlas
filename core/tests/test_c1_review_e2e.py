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
from tests.test_engine_model_wiring import _ProviderKeyManager


async def run_script(tmp_path, monkeypatch, script, *, history=None, hermes_config="", configure_agent=None, **options):
    class FixtureConfig(dict):
        db_path = tmp_path / "store.db"

        @property
        def raw(self):
            return self
    monkeypatch.setattr("atlas.config.get_config", lambda: FixtureConfig({
        "tools.servers": {}, "tools.auto_start": [], "agent.verify_before_stop": True,
    }))
    with FakeLLMServer(script) as fake:
        write_atlas_home(tmp_path / "engine", fake.base_url)
        if hermes_config:
            config_path = tmp_path / "engine/config.yaml"
            config_path.write_text(config_path.read_text().replace("api_max_retries: 1", hermes_config), encoding="utf-8")
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "engine"))
        models = _ProviderKeyManager(fake.base_url, current="fake-model")
        models._models = [{
            "id": "fake-model", "provider": "atlas-fixture", "atlas_provider": "atlas-fixture",
            "litellm_model": "openai/fake-model", "native_model": "fake-model",
            "max_output_tokens": 512,
        }]
        models._find_model = lambda model: next(
            (item for item in models._models if item["id"] == model), None,
        )
        mcp = MagicMock()
        mcp.get_tools_for_llm.return_value = []
        mcp.list_tools.return_value = []
        mcp.tool_count = 0
        local = LocalExecutionRuntime()
        agent = AgentOrchestrator(models, MagicMock(), mcp_client=mcp, local_execution=local)
        assert agent._model_mgr is models and callable(agent._model_mgr._find_model)
        if configure_agent:
            configure_agent(agent)
        ctx = AgentRunContext(cancel_event=asyncio.Event(), run_id="review-run",
            conversation_id="review-session", workspace=str(tmp_path), **options)
        runtime = AtlasRuntime(data_dir=tmp_path, model_manager=models)
        try:
            events = [item async for item in runtime.run_turn(
                message="Perform the fixture task", conversation_id=ctx.conversation_id,
                workspace=str(tmp_path), history=history or [], atlas_agent=agent, atlas_context=ctx,
            )]
            return events, fake.main_requests(), ctx
        finally:
            await runtime.aclose()
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


