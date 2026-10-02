from __future__ import annotations

import asyncio
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
from tests.fakes.fake_llm_provider import Error, FakeLLMServer, StallMidStream, Text, write_hermes_home


def _tiny_png_data_url():
    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
    png += chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def _models(fake, models, current="parent-model"):
    return SimpleNamespace(
        current_model=current,
        current_litellm_model="openai/parent-model",
        gateway_base_url=fake.base_url,
        _api_key="sk-fake-e2e",
        list_models=lambda: models,
        select=lambda _model: (_ for _ in ()).throw(AssertionError("run must not mutate selected model")),
    )


@pytest.mark.asyncio
async def test_parallel_runs_keep_model_snapshots_without_changing_selection(tmp_path, monkeypatch):
    with FakeLLMServer(default_text="model response") as fake:
        home = tmp_path / "engine"
        write_hermes_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        models = _models(fake, [
            {"id": "parent-model", "litellm_model": "openai/parent-model"},
            {"id": "worker-model", "litellm_model": "openai/worker-model"},
        ])
        runtime = HermesRuntime(data_dir=tmp_path, model_manager=models)

        async def run(model_id, conversation_id):
            return [event async for event in runtime.run_turn(
                message="identify the selected model", conversation_id=conversation_id,
                workspace=str(tmp_path), history=[], model_id=model_id,
            )]

        await asyncio.gather(run("parent-model", "parent-turn"), run("worker-model", "worker-turn"))

        assert {request["model"] for request in fake.main_requests()} == {
            "openai/parent-model", "openai/worker-model",
        }
        assert models.current_model == "parent-model"


@pytest.mark.asyncio
async def test_worker_done_event_reports_requested_model_without_mutating_selection(tmp_path, monkeypatch):
    with FakeLLMServer([Text("worker completed")]) as fake:
        class FixtureConfig(dict):
            db_path = tmp_path / "config.db"

        data_root = tmp_path / "atlas-data"
        home = data_root / "engine"
        write_hermes_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        monkeypatch.setattr("atlas.config.get_config", lambda: FixtureConfig({
            "tools.servers": {}, "tools.auto_start": [],
            "agent.verify_before_stop": True,
        }))
        monkeypatch.setattr("atlas.config.DATA_ROOT", data_root)
        monkeypatch.setenv("ATLAS_DATA_DIR", str(data_root))
        model_rows = [
            {"id": "parent-model", "litellm_model": "openai/parent-model"},
            {"id": "worker-model", "litellm_model": "openai/worker-model"},
        ]
        models = _models(fake, model_rows)
        memory = MemoryStore(db_path=tmp_path / "memory.sqlite3")
        await memory.init()
        conversation_id = await memory.create_conversation()
        mcp = MagicMock()
        mcp.get_tools_for_llm.return_value = []
        mcp.list_tools.return_value = []
        mcp.tool_count = 0
        local = LocalExecutionRuntime()
        agent = AgentOrchestrator(models, memory, mcp_client=mcp, local_execution=local)
        try:
            events = [event async for event in agent.run(
                "complete on the worker model", conversation_id,
                model="worker-model", workspace=str(tmp_path),
            )]
        finally:
            await local.shutdown()
            await memory.close()

        assert fake.main_requests()[0]["model"] == "openai/worker-model"
        done = next(event for event in events if event.get("type") == "done")
        assert done["model"] == "worker-model"
        assert models.current_model == "parent-model"


@pytest.mark.asyncio
async def test_durable_process_notice_is_visible_to_next_hermes_turn(tmp_path, monkeypatch):
    from atlas.engine.notifications import consume_notifications, publish_notification

    with FakeLLMServer([Text("continued from notice")]) as fake:
        class FixtureConfig(dict):
            db_path = tmp_path / "atlas.db"

        data_root = tmp_path / "atlas-data"
        home = data_root / "engine"
        write_hermes_home(home, fake.base_url)
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


@pytest.mark.asyncio
async def test_real_hermes_request_includes_transient_image_content(tmp_path, monkeypatch):
    with FakeLLMServer([Text("image received")]) as fake:
        data_root = tmp_path / "atlas-data"
        home = data_root / "engine"
        write_hermes_home(home, fake.base_url)
        config_path = home / "config.yaml"
        config = config_path.read_text(encoding="utf-8")
        config = config.replace("model:\n", "model:\n  supports_vision: true\n", 1)
        config = config.replace(
            "agent:\n", "agent:\n  image_input_mode: native\n", 1,
        )
        config_path.write_text(config, encoding="utf-8")
        monkeypatch.setenv("HERMES_HOME", str(home))
        from hermes_cli.config import load_config_readonly
        from agent.image_routing import _lookup_supports_vision

        assert _lookup_supports_vision(
            "openai", "parent-model", load_config_readonly(),
        ) is True
        class FixtureConfig(dict):
            db_path = tmp_path / "config.db"

        monkeypatch.setattr("atlas.config.get_config", lambda: FixtureConfig({
            "tools.servers": {}, "tools.auto_start": [],
            "agent.verify_before_stop": True,
        }))
        monkeypatch.setattr("atlas.config.DATA_ROOT", data_root)
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


@pytest.mark.asyncio
async def test_real_sdk_stream_timeout_retries_through_fake_http_service(tmp_path, monkeypatch):
    with FakeLLMServer([StallMidStream(seconds=1.0)], default_text="recovered after timeout") as fake:
        home = tmp_path / "engine"
        write_hermes_home(
            home, fake.base_url,
            extra_config="providers:\n  openai:\n    request_timeout_seconds: 0.2\n",
        )
        monkeypatch.setenv("HERMES_HOME", str(home))
        runtime = HermesRuntime(data_dir=tmp_path, model_manager=_models(fake, [
            {"id": "parent-model", "litellm_model": "openai/parent-model"},
        ]))

        events = [event async for event in runtime.run_turn(
            message="complete after transport timeout", conversation_id="timeout-turn",
            workspace=str(tmp_path), history=[], model_id="parent-model",
        )]

        assert len(fake.main_requests()) >= 2
        assert events[-1]["result"]["final_response"].endswith("recovered after timeout")


@pytest.mark.asyncio
async def test_provider_context_overflow_recovers_and_continues(tmp_path, monkeypatch):
    with FakeLLMServer([
        Error(400, "maximum context length is 64 tokens; request had 1024 tokens"),
        Text("continued after provider overflow"),
    ]) as fake:
        home = tmp_path / "engine"
        write_hermes_home(
            home, fake.base_url, context_length=512,
            extra_config=(
                "auxiliary:\n"
                "  compression:\n"
                "    provider: custom\n"
                "    model: openai/parent-model\n"
                f"    base_url: {fake.base_url}\n"
                "    api_key: sk-fake-e2e\n"
            ),
        )
        monkeypatch.setenv("HERMES_HOME", str(home))
        runtime = HermesRuntime(data_dir=tmp_path, model_manager=_models(fake, [
            {"id": "parent-model", "litellm_model": "openai/parent-model"},
        ]))

        events = [event async for event in runtime.run_turn(
            message="continue the task", conversation_id="overflow-turn",
            workspace=str(tmp_path), history=[
                {"role": role, "content": f"history {index} " + ("retain this detail " * 400)}
                for index, role in enumerate(
                    ["user", "assistant", "user", "assistant", "user", "assistant", "user", "assistant"]
                )
            ], model_id="parent-model",
        )]

        assert len(fake.main_requests()) >= 2
        assert events[-1]["result"]["final_response"] == "continued after provider overflow"


@pytest.mark.asyncio
async def test_fallback_request_uses_configured_model_identity(tmp_path, monkeypatch):
    with FakeLLMServer([
        Error(401, "primary model unavailable"),
        Text("fallback model response"),
    ]) as fake:
        home = tmp_path / "engine"
        write_hermes_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        runtime = HermesRuntime(data_dir=tmp_path, model_manager=_models(fake, [
            {
                "id": "parent-model", "litellm_model": "openai/parent-model",
                "fallback": [{
                    "provider": "custom", "model": "fallback-model",
                    "base_url": fake.base_url, "api_key": "sk-fake-e2e",
                }],
            },
        ]))

        events = [event async for event in runtime.run_turn(
            message="continue on fallback", conversation_id="fallback-turn",
            workspace=str(tmp_path), history=[], model_id="parent-model",
        )]

        assert [request["model"] for request in fake.main_requests()[:2]] == [
            "openai/parent-model", "fallback-model",
        ]
        assert events[-1]["result"]["final_response"] == "fallback model response"
