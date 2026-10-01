from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.fakes.fake_llm_provider import FakeLLMServer, Text, ToolCall, write_hermes_home
from atlas.engine.hermes_runtime import HermesRuntime


@pytest.mark.asyncio
async def test_real_hermes_agent_uses_fake_service_and_sessiondb_across_turns(
    tmp_path, monkeypatch,
):
    with FakeLLMServer([
        ToolCall("read_file", {"path": str(tmp_path / "fixture.txt")}),
        Text("first answer"),
        Text("second answer"),
    ]) as fake:
        home = tmp_path / "engine"
        (tmp_path / "fixture.txt").write_text("fake file content", encoding="utf-8")
        write_hermes_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        models = SimpleNamespace(
            current_model="fake-model",
            current_litellm_model="fake-model",
            gateway_base_url=fake.base_url,
            _api_key="sk-fake-e2e",
            list_models=lambda: [{"id": "fake-model", "max_output_tokens": 256}],
        )
        runtime = HermesRuntime(data_dir=tmp_path, model_manager=models)

        first = [event async for event in runtime.run_turn(
            message="first question", conversation_id="e2e-session", workspace=str(tmp_path),
            history=[], system_message="Atlas system prompt", enabled_toolsets=["file"],
        )]
        second = [event async for event in runtime.run_turn(
            message="second question", conversation_id="e2e-session", workspace=str(tmp_path),
            history=[], system_message="Atlas system prompt", enabled_toolsets=["file"],
        )]

        requests = fake.main_requests()
        assert first[-1]["result"]["final_response"] == "first answer"
        assert second[-1]["result"]["final_response"] == "second answer"
        assert len(requests) == 3
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
async def test_real_hermes_agent_completes_more_than_ten_tool_rounds(tmp_path, monkeypatch):
    script = []
    for index in range(11):
        script.append(ToolCall("read_file", {"path": str(tmp_path / f"{index}.txt")}))
    script.append(Text("all eleven tools completed"))
    for index in range(11):
        (tmp_path / f"{index}.txt").write_text(f"fixture {index}", encoding="utf-8")

    with FakeLLMServer(script) as fake:
        home = tmp_path / "engine"
        write_hermes_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        models = SimpleNamespace(
            current_model="fake-model", current_litellm_model="fake-model",
            gateway_base_url=fake.base_url, _api_key="sk-fake-e2e",
            list_models=lambda: [{"id": "fake-model", "max_output_tokens": 256}],
        )
        runtime = HermesRuntime(data_dir=tmp_path, model_manager=models)
        events = [event async for event in runtime.run_turn(
            message="read all fixtures", conversation_id="many-tools", workspace=str(tmp_path),
            history=[], enabled_toolsets=["file"],
        )]

        assert events[-1]["result"]["final_response"] == "all eleven tools completed"
        assert len(fake.main_requests()) == 12
        tool_results = [event for event in events if event["type"] == "tool_result"]
        assert len(tool_results) == 11
        assert all(not event["is_error"] for event in tool_results)
