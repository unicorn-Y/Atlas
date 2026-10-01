from __future__ import annotations

import base64
import copy
import struct
from types import SimpleNamespace
from unittest.mock import MagicMock
import zlib

import pytest

from atlas.agent import AgentOrchestrator
from atlas.engine.hermes_runtime import HermesRuntime
from atlas.memory import MemoryStore
from atlas.tools.local_execution import LocalExecutionRuntime
from tests.fakes.fake_llm_provider import FakeLLMServer, Text, write_hermes_home


def _tiny_png_data_url():
    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
    png += chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


@pytest.mark.asyncio
async def test_real_hermes_request_includes_transient_image_content(tmp_path, monkeypatch):
    with FakeLLMServer([Text("image received")]) as fake:
        data_root = tmp_path / "atlas-data"
        home = data_root / "engine"
        write_hermes_home(home, fake.base_url)
        config_path = home / "config.yaml"
        config = config_path.read_text(encoding="utf-8")
        config = config.replace("model:\n", "model:\n  supports_vision: true\n", 1)
        config = config.replace("agent:\n", "agent:\n  image_input_mode: native\n", 1)
        config_path.write_text(config, encoding="utf-8")
        monkeypatch.setenv("HERMES_HOME", str(home))
        from hermes_cli.config import load_config_readonly
        from agent.image_routing import _lookup_supports_vision

        assert _lookup_supports_vision("openai", "parent-model", load_config_readonly()) is True

        class FixtureConfig(dict):
            db_path = tmp_path / "config.db"

        monkeypatch.setattr("atlas.config.get_config", lambda: FixtureConfig({
            "tools.servers": {}, "tools.auto_start": [], "agent.engine": "hermes",
            "agent.verify_before_stop": True,
        }))
        monkeypatch.setattr("atlas.config.DATA_ROOT", data_root)
        monkeypatch.setattr("atlas.config.load_user_settings", lambda: {"agent_engine": "hermes"})
        monkeypatch.setenv("ATLAS_DATA_DIR", str(data_root))
        model_config = [{
            "id": "parent-model", "litellm_model": "openai/parent-model",
            "max_output_tokens": 256,
        }]
        models = SimpleNamespace(
            current_model="parent-model", current_litellm_model="openai/parent-model",
            gateway_base_url=fake.base_url, _api_key="sk-fake-e2e",
            list_models=lambda: model_config,
        )
        memory = MemoryStore(db_path=tmp_path / "atlas-memory.sqlite3")
        await memory.init()
        conversation_id = await memory.create_conversation()
        mcp = MagicMock()
        mcp.get_tools_for_llm.return_value = []
        mcp.list_tools.return_value = []
        mcp.tool_count = 0
        local = LocalExecutionRuntime()
        agent = AgentOrchestrator(models, memory, mcp_client=mcp, local_execution=local)
        prepared = []
        original_factory_method = HermesRuntime._agent_factory

        def capture_factory(runtime):
            base_factory = original_factory_method(runtime)

            def construct(**kwargs):
                hermes_agent = base_factory(**kwargs)
                original_prepare = hermes_agent._prepare_messages_for_non_vision_model

                def capture_prepare(messages):
                    before = copy.deepcopy(messages)
                    result = original_prepare(messages)
                    prepared.append({
                        "supports_vision": hermes_agent._model_supports_vision(),
                        "before": before, "after": copy.deepcopy(result),
                    })
                    return result

                hermes_agent._prepare_messages_for_non_vision_model = capture_prepare
                return hermes_agent

            return construct

        monkeypatch.setattr(HermesRuntime, "_agent_factory", capture_factory)
        try:
            events = [event async for event in agent.run(
                "What is in this image?", conversation_id,
                workspace=str(tmp_path), image_attachments=[_tiny_png_data_url()],
            )]
        finally:
            await local.shutdown()
            await memory.close()

        requests = fake.main_requests() + fake.aux_requests()
        user_message = next((
            item for request in fake.main_requests() for item in request["messages"]
            if item["role"] == "user" and isinstance(item.get("content"), list)
        ), None)
        if user_message is None:
            user_message = next((
                item for request in fake.aux_requests() for item in request["messages"]
                if item["role"] == "user" and isinstance(item.get("content"), list)
            ), None)
        assert user_message is not None, {"requests": requests, "prepared": prepared}
        assert user_message["content"][-1]["image_url"]["url"].startswith("data:image/png;base64,")
        assert prepared and prepared[-1]["supports_vision"] is True
        assert isinstance(prepared[-1]["after"][-1].get("content"), list)
        assert any(event.get("type") == "done" for event in events)
