from __future__ import annotations

import asyncio
import ast
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.fakes.fake_llm_provider import Error, FakeLLMServer, Hang, Text, ToolCall, write_atlas_home
from atlas.engine.atlas_runtime import AtlasRuntime
from atlas.agent import AgentOrchestrator, AgentRunContext
from atlas.models.router import ModelRouter
from atlas.tools.local_execution import LocalExecutionRuntime
from tests.test_engine_model_wiring import _NativeAnthropicManager, _ProviderKeyManager


def _disable_external_mcp(monkeypatch):
    monkeypatch.setattr("atlas.config.get_config", lambda: {
        "tools.servers": {}, "tools.auto_start": [],
    })


@pytest.mark.asyncio
async def test_notification_read_failure_is_visible_and_does_not_stop_turn(
    tmp_path, monkeypatch, caplog,
):
    from atlas.engine import notifications
    import atlas.engine.atlas_policy as atlas_policy
    import atlas.engine.tool_registry as tool_registry

    async def fail_read(_conversation_id):
        raise OSError("notification db unavailable")

    monkeypatch.setattr(notifications, "consume_notifications", fail_read)
    monkeypatch.setattr(atlas_policy, "install_atlas_policy_plugin", lambda: None)
    monkeypatch.setattr(tool_registry, "bind_atlas_tools", lambda *_args: None)
    with FakeLLMServer([Text("turn completed")]) as fake:
        home = tmp_path / "engine"
        write_atlas_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        manager = SimpleNamespace(
            current_model="fake-model", current_litellm_model="fake-model",
            gateway_base_url=fake.base_url, _api_key="sk-fake-e2e",
            list_models=lambda: [{"id": "fake-model", "max_output_tokens": 256}],
        )
        runtime = AtlasRuntime(data_dir=tmp_path, model_manager=manager)
        monkeypatch.setattr(runtime, "_ensure_atlas_mcp_registered", lambda: [])
        events = [event async for event in runtime.run_turn(
            message="continue despite notification failure", conversation_id="notice-failure",
            workspace=str(tmp_path), history=[], atlas_agent=SimpleNamespace(),
            atlas_context=SimpleNamespace(
                mode="act", todo_store=SimpleNamespace(snapshot=lambda: {"todos": []}),
            ),
        )]

    assert events[-1]["type"] == "atlas.result"
    notices = [event for event in events if event.get("type") == "run.recovery.notice"]
    assert any("通知读取失败" in event["data"]["message"] for event in notices)
    assert "notification db unavailable" in caplog.text


@pytest.mark.asyncio
async def test_budget_hook_exception_blocks_provider_http(tmp_path, monkeypatch):
    from atlas.usage import RunUsageBudget

    audit_path = tmp_path / "budget-hook-error.jsonl"
    monkeypatch.setenv("ATLAS_RUN_INPUT_TOKEN_LIMIT", "10000")
    monkeypatch.setenv("ATLAS_RUN_BUDGET_ID", "budget-hook-error")
    monkeypatch.setenv("ATLAS_RUN_USAGE_AUDIT_FILE", str(audit_path))

    def fail_reserve(*_args, **_kwargs):
        raise OSError("budget reservation unavailable")

    monkeypatch.setattr(RunUsageBudget, "reserve", fail_reserve)
    with FakeLLMServer([Text("must not be requested")]) as fake:
        home = tmp_path / "engine"
        write_atlas_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        manager = SimpleNamespace(
            current_model="fake-model", current_litellm_model="fake-model",
            gateway_base_url=fake.base_url, _api_key="sk-fake-e2e",
            list_models=lambda: [{"id": "fake-model", "max_output_tokens": 256}],
        )
        runtime = AtlasRuntime(data_dir=tmp_path, model_manager=manager)
        events = [event async for event in runtime.run_turn(
            message="reservation failure must stop before HTTP", conversation_id="budget-hook-error",
            workspace=str(tmp_path), history=[],
        )]
        await runtime.aclose()

    assert fake.main_requests() == []
    assert events[-1]["type"] == "atlas.result"


@pytest.mark.asyncio
async def test_budget_unknown_usage_disables_retries_and_audits_one_send(tmp_path, monkeypatch):
    audit_path = tmp_path / "budget-unknown.jsonl"
    monkeypatch.setenv("ATLAS_RUN_INPUT_TOKEN_LIMIT", "10000")
    monkeypatch.setenv("ATLAS_RUN_BUDGET_ID", "budget-unknown")
    monkeypatch.setenv("ATLAS_RUN_USAGE_AUDIT_FILE", str(audit_path))
    with FakeLLMServer([Error(500, "scripted unknown usage")]) as fake:
        home = tmp_path / "engine"
        write_atlas_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        manager = SimpleNamespace(
            current_model="fake-model", current_litellm_model="fake-model",
            gateway_base_url=fake.base_url, _api_key="sk-fake-e2e",
            list_models=lambda: [{"id": "fake-model", "max_output_tokens": 256}],
        )
        runtime = AtlasRuntime(data_dir=tmp_path, model_manager=manager)
        events = [event async for event in runtime.run_turn(
            message="provider error has unknown usage", conversation_id="budget-unknown",
            workspace=str(tmp_path), history=[],
        )]
        await runtime.aclose()

    import json

    rows = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert len(fake.main_requests()) == 1
    assert len(rows) == 1
    assert rows[0]["usage_available"] is False
    assert rows[0]["budget_usage_unknown"] is True
    assert events[-1]["type"] == "atlas.result"


@pytest.mark.asyncio
@pytest.mark.parametrize("budgeted,expected_requests", [(True, 1), (False, 2)])
async def test_stream_fault_budget_disables_hidden_retry_only_when_opted_in(
    tmp_path, monkeypatch, budgeted, expected_requests,
):
    audit_path = tmp_path / "stream-budget.jsonl"
    if budgeted:
        monkeypatch.setenv("ATLAS_RUN_INPUT_TOKEN_LIMIT", "10000")
        monkeypatch.setenv("ATLAS_RUN_BUDGET_ID", "stream-budgeted")
        monkeypatch.setenv("ATLAS_RUN_USAGE_AUDIT_FILE", str(audit_path))
    else:
        for name in (
            "ATLAS_RUN_INPUT_TOKEN_LIMIT", "ATLAS_RUN_BUDGET_ID",
            "ATLAS_RUN_USAGE_AUDIT_FILE",
        ):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HERMES_STREAM_RETRIES", "1")
    with FakeLLMServer([Hang(seconds=0.1), Text("retry reached")]) as fake:
        home = tmp_path / "engine"
        write_atlas_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        manager = SimpleNamespace(
            current_model="fake-model", current_litellm_model="fake-model",
            gateway_base_url=fake.base_url, _api_key="sk-fake-e2e",
            list_models=lambda: [{"id": "fake-model", "max_output_tokens": 256}],
        )
        runtime = AtlasRuntime(data_dir=tmp_path, model_manager=manager)
        events = [event async for event in runtime.run_turn(
            message="exercise stream retry policy", conversation_id=f"stream-budget-{budgeted}",
            workspace=str(tmp_path), history=[],
        )]
        await runtime.aclose()

    assert len(fake.main_requests()) == expected_requests
    assert events[-1]["type"] == "atlas.result"
    if budgeted:
        import json

        rows = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
        assert len(rows) == 1 and rows[0]["budget_usage_unknown"] is True
    else:
        assert events[-1]["result"]["final_response"] == "retry reached"


@pytest.mark.asyncio
@pytest.mark.parametrize("budgeted,expected_requests", [(True, 1), (False, 2)])
async def test_stream_options_compat_retry_is_budgeted_only_when_opted_in(
    tmp_path, monkeypatch, budgeted, expected_requests,
):
    audit_path = tmp_path / "stream-options-budget.jsonl"
    if budgeted:
        monkeypatch.setenv("ATLAS_RUN_INPUT_TOKEN_LIMIT", "10000")
        monkeypatch.setenv("ATLAS_RUN_BUDGET_ID", "stream-options-budgeted")
        monkeypatch.setenv("ATLAS_RUN_USAGE_AUDIT_FILE", str(audit_path))
    else:
        for name in (
            "ATLAS_RUN_INPUT_TOKEN_LIMIT", "ATLAS_RUN_BUDGET_ID",
            "ATLAS_RUN_USAGE_AUDIT_FILE",
        ):
            monkeypatch.delenv(name, raising=False)

    with FakeLLMServer([
        Error(400, "stream_options is an unexpected extra field"),
        Text("compatibility retry reached"),
    ]) as fake:
        home = tmp_path / "engine"
        write_atlas_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        manager = SimpleNamespace(
            current_model="fake-model", current_litellm_model="fake-model",
            gateway_base_url=fake.base_url, _api_key="sk-fake-e2e",
            list_models=lambda: [{"id": "fake-model", "max_output_tokens": 256}],
        )
        runtime = AtlasRuntime(data_dir=tmp_path, model_manager=manager)
        events = [event async for event in runtime.run_turn(
            message="exercise stream_options compatibility retry",
            conversation_id=f"stream-options-budget-{budgeted}",
            workspace=str(tmp_path), history=[],
        )]
        await runtime.aclose()

    requests = fake.main_requests()
    assert len(requests) == expected_requests
    assert "stream_options" in requests[0]
    assert events[-1]["type"] == "atlas.result"
    if budgeted:
        import json

        rows = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
        assert len(rows) == 1 and rows[0]["budget_usage_unknown"] is True
    else:
        assert events[-1]["result"]["final_response"] == "compatibility retry reached"


@pytest.mark.asyncio
async def test_run_usage_reports_every_provider_request_without_accumulating_context(
    tmp_path, monkeypatch,
):
    with FakeLLMServer([
        ToolCall("todo_list", {"todos": []}),
        Text("first step", prompt_tokens=200, completion_tokens=20, cached_tokens=10),
        ToolCall("todo_list", {"todos": []}),
        Text("done", prompt_tokens=400, completion_tokens=30, cached_tokens=40),
    ]) as fake:
        home = tmp_path / "engine"
        write_atlas_home(home, fake.base_url, extra_config=(
            "auxiliary:\n"
            "  title_generation:\n"
            "    enabled: false\n"
        ))
        monkeypatch.setenv("HERMES_HOME", str(home))
        models = SimpleNamespace(
            current_model="fake-model", current_litellm_model="fake-model",
            gateway_base_url=fake.base_url, _api_key="sk-fake-e2e",
            list_models=lambda: [{"id": "fake-model", "max_output_tokens": 256}],
        )
        runtime = AtlasRuntime(data_dir=tmp_path, model_manager=models)
        events = []
        for message in ("run step one", "run step two"):
            events.extend([event async for event in runtime.run_turn(
                message=message, conversation_id="usage-four-requests",
                workspace=str(tmp_path), history=[],
            )])
        await runtime.aclose()

    emitted_rows = [event["usage"] for event in events if event.get("type") == "run_usage"]
    assert len(fake.main_requests()) == 4, [
        (request["messages"][-1]["role"], len(request.get("tools", [])))
        for request in fake.main_requests()
    ]
    # The latest request is re-emitted with post-run diagnostics. Request IDs
    # let the runner enrich the row without charging the same request twice.
    rows_by_id = {row["request_id"]: row for row in emitted_rows}
    rows = list(rows_by_id.values())
    assert len(rows) == 4
    assert sum(row["input_tokens"] for row in rows) == 800
    assert sum(row["uncached_input_tokens"] for row in rows) == 750
    assert sum(row["output_tokens"] for row in rows) == 70
    assert sum(row["cached_input_tokens"] for row in rows) == 50
    assert any(row["cache_usage_available"] for row in rows)
    assert any(not row["cache_usage_available"] for row in rows)
    assert any(
        "prompt_tokens_details.cached_tokens" in row["cache_usage_fields"]
        for row in rows
    )
    assert rows[-1]["context_tokens"] == 400
    assert len({row["request_id"] for row in rows}) == 4


@pytest.mark.asyncio
async def test_real_atlas_agent_uses_fake_service_and_sessiondb_across_turns(
    tmp_path, monkeypatch,
):
    with FakeLLMServer([
        ToolCall("read_file", {"path": str(tmp_path / "fixture.txt")}),
        Text("first answer"),
        Text("second answer"),
    ]) as fake:
        home = tmp_path / "engine"
        (tmp_path / "fixture.txt").write_text("fake file content", encoding="utf-8")
        write_atlas_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        models = SimpleNamespace(
            current_model="fake-model",
            current_litellm_model="fake-model",
            gateway_base_url=fake.base_url,
            _api_key="sk-fake-e2e",
            list_models=lambda: [{"id": "fake-model", "max_output_tokens": 256}],
        )
        runtime = AtlasRuntime(data_dir=tmp_path, model_manager=models)

        first = [event async for event in runtime.run_turn(
            message="first question", conversation_id="e2e-session", workspace=str(tmp_path),
            history=[], system_message="Atlas system prompt", volatile_context=["Atlas memory: frozen fact"],
            enabled_toolsets=["file"],
        )]
        second = [event async for event in runtime.run_turn(
            message="second question", conversation_id="e2e-session", workspace=str(tmp_path),
            history=[], system_message="Atlas system prompt", volatile_context=["Atlas memory: changed"],
            enabled_toolsets=["file"],
        )]

        requests = fake.main_requests()
        assert first[-1]["result"]["final_response"] == "first answer"
        assert second[-1]["result"]["final_response"] == "second answer"
        assert len(requests) == 3
        system_first = next(item["content"] for item in requests[0]["messages"] if item["role"] == "system")
        system_second = next(item["content"] for item in requests[2]["messages"] if item["role"] == "system")
        assert "Atlas session-start context" in system_first
        assert "You are Atlas, the AI assistant for this workspace." in system_first
        assert "Atlas memory: frozen fact" in system_first
        assert system_second == system_first
        assert "Atlas memory: changed" not in system_second
        assert any(
            item.get("role") == "tool"
            for item in requests[1]["messages"]
        )
        assert any(
            item.get("role") == "assistant" and item.get("content") == "first answer"
            for item in requests[2]["messages"]
        )
        assert any(
            item.get("role") == "user" and item.get("content") == "first question"
            for item in requests[2]["messages"]
        )
        assert any(
            item.get("role") == "tool"
            for item in requests[2]["messages"]
        )
        usage = next(event["usage"] for event in second if event["type"] == "run_usage")
        assert usage["context_limit"] == 128000


@pytest.mark.asyncio
async def test_real_atlas_agent_completes_more_than_ten_tool_rounds(tmp_path, monkeypatch):
    script = []
    for index in range(11):
        script.append(ToolCall("read_file", {"path": str(tmp_path / f"{index}.txt")}))
    script.append(Text("all eleven tools completed"))
    for index in range(11):
        (tmp_path / f"{index}.txt").write_text(f"fixture {index}", encoding="utf-8")

    with FakeLLMServer(script) as fake:
        home = tmp_path / "engine"
        write_atlas_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        models = SimpleNamespace(
            current_model="fake-model", current_litellm_model="fake-model",
            gateway_base_url=fake.base_url, _api_key="sk-fake-e2e",
            list_models=lambda: [{"id": "fake-model", "max_output_tokens": 256}],
        )
        runtime = AtlasRuntime(data_dir=tmp_path, model_manager=models)
        events = [event async for event in runtime.run_turn(
            message="read all fixtures", conversation_id="many-tools", workspace=str(tmp_path),
            history=[], enabled_toolsets=["file"],
        )]

        assert events[-1]["result"]["final_response"] == "all eleven tools completed"
        assert len(fake.main_requests()) == 12
        tool_results = [event for event in events if event["type"] == "tool_result"]
        assert len(tool_results) == 11
        assert all(not event["is_error"] for event in tool_results)


@pytest.mark.asyncio
async def test_real_manual_compression_uses_atlas_and_session_continues(tmp_path, monkeypatch):
    with FakeLLMServer([Text("done")], default_text="continued after compaction") as fake:
        home = tmp_path / "engine"
        write_atlas_home(
            home, fake.base_url,
            extra_config=(
                "auxiliary:\n"
                "  compression:\n"
                "    provider: custom\n"
                "    model: fake-model\n"
                f"    base_url: {fake.base_url}\n"
                "    api_key: sk-fake-e2e\n"
            ),
        )
        monkeypatch.setenv("HERMES_HOME", str(home))
        monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-e2e")
        models = SimpleNamespace(
            current_model="fake-model", current_litellm_model="fake-model",
            gateway_base_url=fake.base_url, _api_key="sk-fake-e2e",
            list_models=lambda: [{"id": "fake-model", "max_output_tokens": 256}],
        )
        runtime = AtlasRuntime(data_dir=tmp_path, model_manager=models)
        conversation_id = "manual-compression"
        for index in range(24):
            [event async for event in runtime.run_turn(
                message=f"work item {index}: " + ("retained detail " * 160),
                conversation_id=conversation_id, workspace=str(tmp_path), history=[],
                system_message="Atlas identity and stable rules",
            )]

        compressed = await runtime.compact_session(
            conversation_id=conversation_id, workspace=str(tmp_path), focus_topic="preserve work state",
        )
        assert compressed["compressed"] is True, compressed
        assert fake.aux_requests(), "Hermes ContextCompressor must call the fake summary service"

        continued = [event async for event in runtime.run_turn(
            message="continue", conversation_id=conversation_id, workspace=str(tmp_path),
            history=[], system_message="Atlas identity and stable rules",
        )]
        assert continued[-1]["result"]["final_response"] == "continued after compaction"


@pytest.mark.asyncio
async def test_manual_compression_uses_prefixed_routes_wire_models_without_gateway(
    tmp_path, monkeypatch,
):
    with FakeLLMServer([Text("done") for _ in range(24)], api_key="sk-main") as main_fake, \
            FakeLLMServer(api_key="sk-compression") as compression_fake:
        home = tmp_path / "engine"
        write_atlas_home(
            home, main_fake.base_url,
            extra_config=(
                "auxiliary:\n"
                "  compression:\n"
                "    provider: custom\n"
                "    model: main-model\n"
                f"    base_url: {main_fake.base_url}\n"
                "    api_key: sk-main\n"
            ),
        )
        monkeypatch.setenv("HERMES_HOME", str(home))
        monkeypatch.setattr("atlas.config.load_user_settings", lambda: {
            "compression_model": "ref-model",
        })
        manager = _ProviderKeyManager(main_fake.base_url)
        manager._models[1].update(
            provider="compression-fixture", hermes_provider="compression-fixture",
            native_model="wire-ref-model",
        )
        manager.provider_config = lambda provider: {
            "base_url": compression_fake.base_url if provider == "compression-fixture" else main_fake.base_url,
            "keys": [],
        }
        manager.resolve_api_key = lambda provider: "sk-compression" if provider == "compression-fixture" else "sk-main"
        manager.gateway_base_url = ""
        manager.gateway_api_key = ""
        runtime = AtlasRuntime(data_dir=tmp_path, model_manager=manager)

        conversation_id = "prefixed-independent-compression"
        for index in range(24):
            [event async for event in runtime.run_turn(
                message=f"work item {index}: " + ("retained detail " * 160),
                conversation_id=conversation_id, workspace=str(tmp_path), history=[],
                system_message="Atlas identity and stable rules",
            )]

        compressed = await runtime.compact_session(
            conversation_id=conversation_id, workspace=str(tmp_path),
        )

        assert compressed["compressed"] is True, compressed
        aux = compression_fake.aux_requests()
        assert aux, {"compression": compressed, "main_requests": len(main_fake.requests),
                     "compression_requests": len(compression_fake.requests)}
        assert {request["model"] for request in aux} == {"wire-ref-model"}
        assert main_fake.aux_requests() == []

        # The cached conversation agent must discard the old sidecar endpoint
        # when the setting is cleared on a later turn.
        monkeypatch.setattr("atlas.config.load_user_settings", lambda: {})
        [event async for event in runtime.run_turn(
            message="continue after clearing compression route",
            conversation_id=conversation_id, workspace=str(tmp_path), history=[],
        )]
        cached_agent = runtime._agent_cache[conversation_id]["agent"]
        compressor = cached_agent.context_compressor
        assert compressor.summary_model is None
        assert compressor.summary_model_id is None
        assert compressor.provider == cached_agent.provider
        assert compressor.base_url == main_fake.base_url
        assert compressor.api_key == cached_agent.api_key
        compressor._call_summary_llm("Summarize through the restored main route.", time.monotonic())
        assert main_fake.aux_requests()


@pytest.mark.asyncio
async def test_manual_compression_succeeds_with_native_only_model_configuration(
    tmp_path, monkeypatch,
):
    with FakeLLMServer(
        [Text("native turn completed") for _ in range(24)],
        default_text="native compression continued",
        api_key="sk-native-secret", anthropic_messages=True,
    ) as fake:
        home = tmp_path / "engine"
        write_atlas_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        monkeypatch.setattr("atlas.config.load_user_settings", lambda: {})
        manager = _NativeAnthropicManager(fake.base_url)
        assert manager.gateway_base_url == ""
        manager.model_router = ModelRouter(manager)
        runtime = AtlasRuntime(data_dir=tmp_path, model_manager=manager)

        conversation_id = "native-manual-compact"
        for index in range(24):
            events = [event async for event in runtime.run_turn(
                message=f"native item {index}: " + ("retain these details " * 600),
                conversation_id=conversation_id, workspace=str(tmp_path), history=[],
            )]
        assert events[-1]["type"] == "atlas.result"
        compressed = await runtime.compact_session(
            conversation_id=conversation_id, workspace=str(tmp_path),
        )

        assert compressed["compressed"] is True, compressed
        requests = fake.anthropic_requests()
        assert requests
        assert any(request["model"] == "claude-main" for request in requests)


def test_runtime_request_models_never_use_litellm_model_directly():
    source = Path(AtlasRuntime.__module__.replace(".", "/") + ".py")
    if not source.is_absolute():
        source = Path(__file__).resolve().parents[1] / "atlas" / "engine" / "hermes_runtime.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg == "model" and any(
                isinstance(part, ast.Name) and part.id == "litellm_model"
                for part in ast.walk(keyword.value)
            ):
                violations.append(node.lineno)
    assert violations == []


@pytest.mark.asyncio
async def test_small_context_auto_compresses_and_keeps_active_todo(tmp_path, monkeypatch):
    target = tmp_path / "compression-write.txt"
    large_tool_content = "retain active requirements " * 900
    with FakeLLMServer(
        [
            ToolCall("todo_list", {"todos": [{
                "id": "todo-e2e", "content": "preserve this active todo through compression",
                "status": "in_progress",
            }]}),
            *[
                ToolCall("write_file", {"path": str(target), "content": large_tool_content})
                for _ in range(12)
            ],
            Text("work continued after automatic compression"),
        ],
        context_length=64000,
        prompt_tokens_fn=lambda body: len(json.dumps(body, ensure_ascii=False)) // 5,
    ) as fake:
        home = tmp_path / "engine"
        write_atlas_home(
            home, fake.base_url,
            extra_config=(
                "auxiliary:\n"
                "  compression:\n"
                "    provider: custom\n"
                "    model: fake-model\n"
                f"    base_url: {fake.base_url}\n"
                "    api_key: sk-fake-e2e\n"
            ),
            context_length=64000,
        )
        monkeypatch.setenv("HERMES_HOME", str(home))
        models = SimpleNamespace(
            current_model="fake-model", current_litellm_model="fake-model",
            gateway_base_url=fake.base_url, _api_key="sk-fake-e2e",
            list_models=lambda: [{"id": "fake-model", "max_output_tokens": 256}],
        )
        runtime = AtlasRuntime(data_dir=tmp_path, model_manager=models)
        original_factory = runtime._agent_factory

        def agent_factory():
            HermesAgent = original_factory()

            def create_agent(**kwargs):
                instance = HermesAgent(**kwargs)
                instance._todo_store.write([{
                    "id": "todo-e2e", "content": "preserve this active todo through compression",
                    "status": "in_progress",
                }])
                return instance

            return create_agent

        monkeypatch.setattr(runtime, "_agent_factory", agent_factory)
        all_events = [event async for event in runtime.run_turn(
            message="keep the current todo while updating the fixture",
            conversation_id="small-context-compression", workspace=str(tmp_path), history=[],
        )]
        assert fake.aux_requests(), "64K real model context must trigger Hermes' automatic summary client"
        assert any(item.get("type") == "run.compaction.progress" for item in all_events)
        assert any(
            item.get("type") == "run_usage" and item.get("usage", {}).get("context_limit") == 64000
            for item in all_events
        ), "Atlas must surface Hermes' actual model context window"
        captured_requests = fake.main_requests()
        all_requests = json.dumps(captured_requests, ensure_ascii=False)
        request_outline = [
            {
                "request": index,
                "tools": [
                    tool.get("function", {}).get("name")
                    for message in request.get("messages", [])
                    for tool in message.get("tool_calls", [])
                ],
                "messages": [
                    {"role": message.get("role"), "content": str(message.get("content", ""))[:220]}
                    for message in request.get("messages", [])
                    if message.get("role") in {"user", "tool"}
                ],
            }
            for index, request in enumerate(captured_requests)
        ]
        relevant_messages = [
            {"role": message.get("role"), "content": str(message.get("content", ""))[:500]}
            for request in fake.main_requests() for message in request.get("messages", [])
            if "todo" in str(message.get("content", "")).casefold()
            or "active task" in str(message.get("content", "")).casefold()
        ]
        assert "[Your active task list was preserved across context compression]" in all_requests, request_outline
        assert "preserve this active todo through compression" in all_requests, relevant_messages
        assert target.read_text(encoding="utf-8") == large_tool_content
        assert "work continued after automatic compression" in all_events[-1]["result"]["final_response"]


@pytest.mark.asyncio
async def test_real_atlas_file_tools_preserve_lf_and_crlf(tmp_path, monkeypatch):
    lf_path = tmp_path / "lf.txt"
    crlf_path = tmp_path / "crlf.txt"
    lf_path.write_bytes(b"one\ntwo\n")
    crlf_path.write_bytes(b"one\r\ntwo\r\n")
    with FakeLLMServer([
        ToolCall("read_file", {"path": str(lf_path)}),
        ToolCall("patch", {"path": str(lf_path), "old_string": "two", "new_string": "TWO"}),
        Text("lf edited"),
        ToolCall("read_file", {"path": str(crlf_path)}),
        ToolCall("patch", {"path": str(crlf_path), "old_string": "two", "new_string": "TWO"}),
        Text("crlf edited"),
    ]) as fake:
        home = tmp_path / "engine"
        write_atlas_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        models = SimpleNamespace(
            current_model="fake-model", current_litellm_model="fake-model",
            gateway_base_url=fake.base_url, _api_key="sk-fake-e2e",
            list_models=lambda: [{"id": "fake-model", "max_output_tokens": 256}],
        )
        runtime = AtlasRuntime(data_dir=tmp_path, model_manager=models)
        for index, message in enumerate(("edit lf", "edit crlf")):
            events = [event async for event in runtime.run_turn(
                message=message, conversation_id=f"line-endings-{index}",
                workspace=str(tmp_path), history=[], enabled_toolsets=["file"],
            )]
            assert not events[-1].get("error")
        assert lf_path.read_bytes() == b"one\nTWO\n"
        assert crlf_path.read_bytes() == b"one\r\nTWO\r\n"


@pytest.mark.asyncio
async def test_atlas_policy_plugin_enforces_read_only_approval_and_workspace(tmp_path, monkeypatch):
    _disable_external_mcp(monkeypatch)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    targets = [
        workspace / "readonly.txt", workspace / "denied.txt",
        workspace / "allowed.txt", tmp_path / "outside.txt",
    ]
    cases = [
        ("read_only", "deny", targets[0], []),
        ("ask_writes", "deny", targets[1], []),
        ("ask_writes", "allow", targets[2], []),
        ("full_access", "allow", targets[3], [str(workspace)]),
    ]
    script = []
    for index, (_mode, _choice, target, _paths) in enumerate(cases):
        script.extend([
            ToolCall("write_file", {"path": str(target), "content": f"case {index}"}),
            Text(f"finished {index}"),
        ])
    with FakeLLMServer(script) as fake:
        home = tmp_path / "engine"
        write_atlas_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        models = SimpleNamespace(
            current_model="fake-model", current_litellm_model="fake-model",
            gateway_base_url=fake.base_url, _api_key="sk-fake-e2e",
            list_models=lambda: [{"id": "fake-model", "max_output_tokens": 256}],
        )
        mcp = MagicMock()
        mcp.get_tools_for_llm.return_value = []
        mcp.list_tools.return_value = []
        mcp.tool_count = 0
        agent = AgentOrchestrator(
            models, MagicMock(), mcp_client=mcp, local_execution=LocalExecutionRuntime(),
        )
        runtime = AtlasRuntime(data_dir=tmp_path, model_manager=models)
        approval_calls = []
        hook_calls = []

        async def approve(event_id, name, args, selected):
            approval_calls.append((event_id, name))
            return selected

        for index, (mode, choice, target, allowed_paths) in enumerate(cases):
            ctx = AgentRunContext(
                cancel_event=asyncio.Event(), run_id=f"policy-{index}",
                conversation_id=f"policy-session-{index}", workspace=str(workspace),
                permission_mode=mode, allowed_paths=allowed_paths,
                approval_callback=lambda event_id, name, args, selected=choice: approve(
                    event_id, name, args, selected,
                ),
                user_hook_callback=lambda event, payload: hook_calls.append((event, payload)) or {},
            )
            events = [event async for event in runtime.run_turn(
                message=f"write policy case {index}", conversation_id=ctx.conversation_id,
                workspace=str(workspace), history=[], atlas_agent=agent, atlas_context=ctx,
            )]
            assert events[-1]["result"]["final_response"] == f"finished {index}"
            assert target.exists() is (index == 2)
        assert len(approval_calls) == 2
        assert {item[0] for item in hook_calls} >= {"tool.before", "tool.after"}


@pytest.mark.asyncio
async def test_write_snapshot_and_rewind_restore_file_and_atlas_session(tmp_path, monkeypatch):
    _disable_external_mcp(monkeypatch)
    from atlas.engine.session_sync import rewind_user_turn

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "created-by-run.txt"
    with FakeLLMServer([
        ToolCall("write_file", {"path": str(target), "content": "written by Hermes"}),
        Text("file created"),
    ]) as fake:
        home = tmp_path / "engine"
        write_atlas_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        models = SimpleNamespace(
            current_model="fake-model", current_litellm_model="fake-model",
            gateway_base_url=fake.base_url, _api_key="sk-fake-e2e",
            list_models=lambda: [{"id": "fake-model", "max_output_tokens": 256}],
        )
        mcp = MagicMock()
        mcp.get_tools_for_llm.return_value = []
        mcp.list_tools.return_value = []
        mcp.tool_count = 0
        agent = AgentOrchestrator(
            models, MagicMock(), mcp_client=mcp, local_execution=LocalExecutionRuntime(),
        )
        context = AgentRunContext(
            cancel_event=asyncio.Event(), run_id="rewind-run", conversation_id="rewind-session",
            workspace=str(workspace), permission_mode="full_access",
        )
        runtime = AtlasRuntime(data_dir=tmp_path, model_manager=models)
        events = [event async for event in runtime.run_turn(
            message="create the fixture", conversation_id="rewind-session",
            workspace=str(workspace), history=[], atlas_agent=agent, atlas_context=context,
        )]
        assert events[-1]["result"]["final_response"] == "file created"
        assert target.read_text(encoding="utf-8") == "written by Hermes"
        checkpoints = agent.checkpoints.list_checkpoints(workspace, run_id="rewind-run")
        assert checkpoints and checkpoints[0]["files"][0]["exists"] is False

        # The fixture turn has exactly one user message: rewind just before it.
        rewind_user_turn(runtime.home, "rewind-session", 0)
        agent.checkpoints.restore_checkpoint(checkpoints[0]["id"])
        assert not target.exists()
        from atlas.engine.session_sync import capture_session

        restored = capture_session(runtime.home, "rewind-session")
        assert restored and restored.get("messages")
        from hermes_state import SessionDB

        with SessionDB(db_path=runtime.home / "state.db") as db:
            assert not db.get_messages_as_conversation("rewind-session")


@pytest.mark.asyncio
async def test_atlas_plan_mode_uses_plan_prompt_and_read_only_tools(tmp_path, monkeypatch):
    _disable_external_mcp(monkeypatch)
    target = tmp_path / "must-not-be-created.txt"
    with FakeLLMServer([
        ToolCall("write_file", {"path": str(target), "content": "blocked in plan"}),
        Text("plan finished"),
    ]) as fake:
        home = tmp_path / "engine"
        write_atlas_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        models = SimpleNamespace(
            current_model="fake-model", current_litellm_model="fake-model",
            gateway_base_url=fake.base_url, _api_key="sk-fake-e2e",
            list_models=lambda: [{"id": "fake-model", "max_output_tokens": 256}],
        )
        mcp = MagicMock()
        mcp.get_tools_for_llm.return_value = []
        mcp.list_tools.return_value = []
        mcp.tool_count = 0
        agent = AgentOrchestrator(models, MagicMock(), mcp_client=mcp)
        context = AgentRunContext(
            cancel_event=asyncio.Event(), run_id="plan-run", conversation_id="plan-session",
            workspace=str(tmp_path), mode="plan",
        )
        events = [event async for event in AtlasRuntime(
            data_dir=tmp_path, model_manager=models,
        ).run_turn(
            message="plan only", conversation_id="plan-session", workspace=str(tmp_path),
            history=[], atlas_agent=agent, atlas_context=context,
        )]
        assert events[-1]["result"]["final_response"] == "plan finished"
        assert not target.exists()
        request = fake.main_requests()[0]
        tools = {tool["function"]["name"] for tool in request["tools"]}
        assert tools <= {"read_file", "search_files", "terminal", "web_fetch", "web_search", "web_extract"}
        assert "terminal" in tools
        prompt = next(item["content"] for item in request["messages"] if item["role"] == "system")
        assert "[/plan — plan mode]" in prompt




@pytest.mark.asyncio
async def test_real_atlas_turn_delivers_queued_steer_after_tool_batch(tmp_path, monkeypatch):
    fixture = tmp_path / "steer-fixture.txt"
    fixture.write_text("read before the follow-up", encoding="utf-8")
    with FakeLLMServer([
        ToolCall("read_file", {"path": str(fixture)}),
        Text("finished after the queued correction"),
    ]) as fake:
        home = tmp_path / "engine"
        write_atlas_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        models = SimpleNamespace(
            current_model="fake-model", current_litellm_model="fake-model",
            gateway_base_url=fake.base_url, _api_key="sk-fake-e2e",
            list_models=lambda: [{"id": "fake-model", "max_output_tokens": 256}],
        )
        queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        queue.put_nowait({"content": "switch to the saved plan", "event_id": "steer-e2e"})
        runtime = AtlasRuntime(data_dir=tmp_path, model_manager=models)
        turn = asyncio.create_task(_collect_turn(runtime, tmp_path, queue))
        events = await turn
        assert any(item.get("type") == "run_steered" and item.get("event_id") == "steer-e2e"
                   for item in events)
        assert "switch to the saved plan" in json.dumps(fake.main_requests(), ensure_ascii=False)


async def _collect_turn(runtime, tmp_path, queue):
    return [event async for event in runtime.run_turn(
        message="start", conversation_id="steering", workspace=str(tmp_path), history=[],
        steer_queue=queue,
    )]


@pytest.mark.asyncio
async def test_real_atlas_turn_stops_when_atlas_cancel_is_set(tmp_path, monkeypatch):
    with FakeLLMServer([Hang(seconds=8)]) as fake:
        home = tmp_path / "engine"
        write_atlas_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        models = SimpleNamespace(
            current_model="fake-model", current_litellm_model="fake-model",
            gateway_base_url=fake.base_url, _api_key="sk-fake-e2e",
            list_models=lambda: [{"id": "fake-model", "max_output_tokens": 256}],
        )
        cancel = asyncio.Event()
        runtime = AtlasRuntime(data_dir=tmp_path, model_manager=models)
        started = asyncio.get_running_loop().time()
        turn = asyncio.create_task(_collect_cancelled_turn(runtime, tmp_path, cancel))
        await asyncio.sleep(0.15)
        cancel.set()
        events = await asyncio.wait_for(turn, timeout=3)
        assert asyncio.get_running_loop().time() - started < 3
        assert events[-1].get("type") == "atlas.result"


async def _collect_cancelled_turn(runtime, tmp_path, cancel):
    return [event async for event in runtime.run_turn(
        message="stop this", conversation_id="cancel", workspace=str(tmp_path), history=[],
        cancel_event=cancel,
    )]


@pytest.mark.asyncio
async def test_atlas_mcp_client_calls_local_stdio_fake_server(tmp_path, monkeypatch):
    from tools.mcp_tool_lifecycle import shutdown_mcp_servers

    server_path = Path(__file__).parent / "fakes" / "fake_mcp_server.py"
    marker_path = tmp_path / "fake-mcp-called.txt"
    monkeypatch.setenv("ATLAS_FAKE_MCP_MARKER", str(marker_path))
    monkeypatch.setattr("atlas.config.get_config", lambda: {
        "tools.servers": {"fake": {
            "transport": "stdio", "command": sys.executable,
            "args": [str(server_path)], "cwd": str(tmp_path), "enabled": True,
            "env": {"ATLAS_FAKE_MCP_MARKER": str(marker_path)},
        }},
        "tools.auto_start": [],
    })
    with FakeLLMServer([
        ToolCall("tool_search", {"queries": ["fake ping"]}),
        ToolCall("tool_call", {"calls": [{"name": "mcp__fake__ping", "arguments": {}}]}),
        Text("MCP replied pong"),
    ]) as fake:
        home = tmp_path / "engine"
        write_atlas_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        models = SimpleNamespace(
            current_model="fake-model", current_litellm_model="fake-model",
            gateway_base_url=fake.base_url, _api_key="sk-fake-e2e",
            list_models=lambda: [{"id": "fake-model", "max_output_tokens": 256}],
        )
        mcp = MagicMock()
        mcp.get_tools_for_llm.return_value = []
        mcp.list_tools.return_value = []
        mcp.tool_count = 0
        agent = AgentOrchestrator(
            models, MagicMock(), mcp_client=mcp, local_execution=LocalExecutionRuntime(),
        )
        approval_calls = []
        hook_calls = []
        ctx = AgentRunContext(
            cancel_event=asyncio.Event(), run_id="mcp-run", conversation_id="mcp-session",
            workspace=str(tmp_path), permission_mode="ask_writes",
            approval_callback=lambda event_id, name, args: (
                approval_calls.append((event_id, name, args)) or "allow"
            ),
            user_hook_callback=lambda event, payload: hook_calls.append((event, payload)) or {},
        )
        try:
            events = [event async for event in AtlasRuntime(
                data_dir=tmp_path, model_manager=models,
            ).run_turn(
                message="call the MCP fixture", conversation_id="mcp-session",
                workspace=str(tmp_path), history=[], atlas_agent=agent, atlas_context=ctx,
            )]
        finally:
            shutdown_mcp_servers(names={"fake"})
        assert events[-1]["result"]["final_response"] == "MCP replied pong"
        assert len(approval_calls) == 1 and approval_calls[0][1] == "mcp__fake__ping", {
            "marker_exists": marker_path.exists(),
            "approval_calls": approval_calls,
            "hook_calls": [item[0] for item in hook_calls],
            "messages": [
                (item.get("role"), str(item.get("name") or ""), str(item.get("content", ""))[:100])
                for item in events[-1]["result"].get("messages", [])
            ],
            "events": [(item.get("type"), item.get("name")) for item in events],
        }
        mcp_calls = [item for item in events if item.get("type") == "tool_result"
                     and item.get("name") == "mcp__fake__ping"]
        assert len(mcp_calls) == 1, events
        assert "pong from local fake MCP" in mcp_calls[0]["content"][0]["text"]
        assert marker_path.exists(), "Hermes must execute the local fake MCP server tool"
        assert [item[0] for item in hook_calls] == [
            "tool.before", "tool.after", "tool.before", "tool.after",
        ]
        assert [item[1]["tool_name"] for item in hook_calls] == [
            "tool_search", "tool_search", "mcp__fake__ping", "mcp__fake__ping",
        ]


@pytest.mark.asyncio
async def test_real_atlas_parallel_child_agents_use_fake_model(tmp_path, monkeypatch):
    with FakeLLMServer() as fake:
        def responder(record):
            body = record["body"]
            request_messages = body.get("messages", [])
            messages = json.dumps(request_messages, ensure_ascii=False)
            if "delegate both summaries" in messages and not any(
                item.get("role") == "tool" for item in request_messages
            ):
                return ToolCall("delegate_task", {"tasks": [
                    {"goal": "summarize fixture alpha"},
                    {"goal": "summarize fixture beta"},
                ]})
            if "delegate both summaries" in messages:
                return Text("both child summaries were dispatched")
            if "summarize fixture alpha" in messages:
                return Text("alpha child complete")
            if "summarize fixture beta" in messages:
                return Text("beta child complete")
            return Text("unexpected fake child prompt")

        fake._responder = responder
        home = tmp_path / "engine"
        write_atlas_home(
            home, fake.base_url,
            extra_config="delegation:\n  max_concurrent_children: 2\n  max_spawn_depth: 2\n",
        )
        monkeypatch.setenv("HERMES_HOME", str(home))
        models = SimpleNamespace(
            current_model="fake-model", current_litellm_model="fake-model",
            gateway_base_url=fake.base_url, _api_key="sk-fake-e2e",
            list_models=lambda: [{"id": "fake-model", "max_output_tokens": 256}],
        )
        runtime = AtlasRuntime(data_dir=tmp_path, model_manager=models)
        events = [event async for event in runtime.run_turn(
            message="delegate both summaries", conversation_id="parallel-children",
            workspace=str(tmp_path), history=[], enabled_toolsets=["delegation"],
        )]
        dispatch = next(
            item for item in events
            if item.get("type") == "tool_result" and item.get("name") == "delegate_task"
        )
        payload = ast.literal_eval(dispatch["content"][0]["text"])
        assert payload["status"] == "dispatched"
        delegation_id = payload["delegation_id"]
        from tools.async_delegation import get_durable_delegation

        deadline = asyncio.get_running_loop().time() + 60
        record = None
        while asyncio.get_running_loop().time() < deadline:
            record = await asyncio.to_thread(get_durable_delegation, delegation_id)
            if record and record.get("state") not in {"running", "finalizing"}:
                break
            await asyncio.sleep(0.1)
        assert record and record.get("state") == "completed", record
        assert record.get("result") and len(record["result"].get("results", [])) == 2, record
        requests = fake.main_requests()
        assert len(requests) >= 3
        child_prompts = json.dumps(requests[1:], ensure_ascii=False)
        assert "summarize fixture alpha" in child_prompts
        assert "summarize fixture beta" in child_prompts
        child_summaries = {
            item.get("summary") for item in record["result"].get("results", [])
        }
        assert child_summaries == {"alpha child complete", "beta child complete"}, record


@pytest.mark.asyncio
async def test_reasoning_stages_first_turn_planning_then_execution(tmp_path, monkeypatch):
    """L8：stages enabled 时首轮走 planning 档、后续轮走 execution 档。"""
    with FakeLLMServer([Text("planned"), Text("done")]) as fake:
        home = tmp_path / "engine"
        write_atlas_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        monkeypatch.setattr(
            "atlas.models.reasoning_stages.load_user_settings", lambda: {
                "reasoning_stages": {"enabled": True, "planning": "high",
                                     "execution": "low", "verification": "high"},
            })
        models = SimpleNamespace(
            current_model="fake-model", current_litellm_model="fake-model",
            gateway_base_url=fake.base_url, _api_key="sk-fake-e2e",
            list_models=lambda: [{"id": "fake-model", "max_output_tokens": 256}],
        )
        captured: list[dict] = []

        def agent_factory(**kwargs):
            from run_agent import AIAgent

            agent = AIAgent(**kwargs)
            original = agent._build_api_kwargs

            def spy(api_messages, tools_for_api=None):
                captured.append(dict(getattr(agent, "reasoning_config", None) or {}))
                return original(api_messages, tools_for_api)

            agent._build_api_kwargs = spy
            return agent

        runtime = AtlasRuntime(data_dir=tmp_path, model_manager=models,
                                agent_factory=agent_factory)
        first = [event async for event in runtime.run_turn(
            message="plan this", conversation_id="stage-first", workspace=str(tmp_path),
            history=[], system_message="Atlas system prompt", enabled_toolsets=["file"],
        )]
        later = [event async for event in runtime.run_turn(
            message="go on", conversation_id="stage-second", workspace=str(tmp_path),
            history=[{"role": "user", "content": "plan this"},
                     {"role": "assistant", "content": "planned"}],
            system_message="Atlas system prompt", enabled_toolsets=["file"],
        )]

        assert first[-1]["result"]["final_response"] == "planned"
        assert later[-1]["result"]["final_response"] == "done"
        assert captured == [{"effort": "high"}, {"effort": "low"}]
