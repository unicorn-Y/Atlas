from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from atlas.agent import AgentOrchestrator
from atlas.memory import MemoryStore
from atlas.tools.local_execution import LocalExecutionRuntime
from tests.fakes.fake_llm_provider import FakeLLMServer, Text, write_atlas_home


@pytest.mark.asyncio
async def test_durable_process_notice_is_visible_to_next_atlas_turn(tmp_path, monkeypatch):
    from atlas.engine.notifications import consume_notifications, publish_notification

    with FakeLLMServer([Text("continued from notice")]) as fake:
        class FixtureConfig(dict):
            db_path = tmp_path / "atlas.db"

        data_root = tmp_path / "atlas-data"
        home = data_root / "engine"
        write_atlas_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        monkeypatch.setattr("atlas.config.get_config", lambda: FixtureConfig({
            "tools.servers": {}, "tools.auto_start": [],
            "agent.verify_before_stop": True,
        }))
        monkeypatch.setattr("atlas.config.DATA_ROOT", data_root)
        monkeypatch.setenv("ATLAS_DATA_DIR", str(data_root))
        memory = MemoryStore(db_path=tmp_path / "memory.sqlite3")
        await memory.init()
        conversation_id = await memory.create_conversation()
        publish_notification(
            conversation_id, kind="process.completed",
            content="process exit=0; output says READY", source_id="exec-1:completion:1",
        )
        models = SimpleNamespace(
            current_model="parent-model", current_litellm_model="openai/parent-model",
            gateway_base_url=fake.base_url, _api_key="sk-fake-e2e",
            list_models=lambda: [{
                "id": "parent-model", "litellm_model": "openai/parent-model",
                "max_output_tokens": 256,
            }],
        )
        mcp = MagicMock()
        mcp.get_tools_for_llm.return_value = []
        mcp.list_tools.return_value = []
        mcp.tool_count = 0
        local = LocalExecutionRuntime()
        agent = AgentOrchestrator(models, memory, mcp_client=mcp, local_execution=local)
        try:
            events = [event async for event in agent.run(
                "Continue now that the process completed", conversation_id,
                workspace=str(tmp_path),
            )]
            remaining = await consume_notifications(conversation_id)
        finally:
            await local.shutdown()
            await memory.close()

        request = fake.main_requests()[0]
        assert any(
            "process exit=0; output says READY" in str(item.get("content"))
            for item in request["messages"] if item.get("role") == "system"
        )
        assert remaining == []
        assert any(event.get("type") == "done" for event in events)
