from __future__ import annotations

import asyncio
import os
import threading
from types import SimpleNamespace

import pytest

from atlas.engine.atlas_runtime import AtlasRuntime
from atlas.engine.tool_registry import _translate


class FakeAtlasAgent:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.interrupted = False
        self.closed = False
        self.model = "test-model"
        self._config_context_length = 4096
        self._last_turn_usage = {
            "prompt_tokens": 37,
            "completion_tokens": 12,
            "total_tokens": 49,
        }

    def run_conversation(self, *, user_message, system_message, conversation_history, task_id=None):
        assert user_message == "continue"
        assert system_message == "Atlas rules"
        assert conversation_history[-1]["role"] == "tool"
        self.kwargs["stream_delta_callback"]("reply")
        self.kwargs["stream_delta_callback"](None)
        self.kwargs["tool_start_callback"]("tc-1", "read_file", {"path": "a.py"})
        self.kwargs["tool_complete_callback"]("tc-1", "read_file", {}, "source")
        self.kwargs["event_callback"]("session:compress", {"compression_count": 1})
        return {"final_response": "reply", "messages": conversation_history}

    def interrupt(self, *, hard_cancel=False):
        self.interrupted = hard_cancel

    def close(self):
        self.closed = True


def test_atlas_tool_calls_translate_to_atlas_tools():
    assert _translate("read_file", {"path": "notes.txt"}) == (
        "local_file", {"path": "notes.txt", "action": "read"},
    )
    assert _translate("patch", {
        "path": "notes.txt", "old_string": "old", "new_string": "new",
    }) == ("local_edit", {
        "path": "notes.txt", "old_string": "old", "new_string": "new",
    })
    assert _translate("search_files", {"pattern": "needle", "path": "src"}) == (
        "local_file", {"path": "src", "action": "search", "query": "needle"},
    )
    assert _translate("terminal", {
        "command": "Get-Location", "workdir": "D:/Atlas", "background": True,
    }) == ("local_shell", {
        "command": "Get-Location", "shell": "auto", "cwd": "D:/Atlas",
        "detached": True, "keep_stdin": True, "_atlas_conversation_id": "",
    })
    assert _translate("terminal", {
        "command": "python -i", "workdir": "D:/Atlas", "background": True, "pty": True,
    }) == ("local_shell", {
        "command": "python -i", "shell": "auto", "cwd": "D:/Atlas",
        "detached": True, "keep_stdin": True, "pty": True,
        "_atlas_conversation_id": "",
    })
    assert _translate("process_manage", {"action": "poll", "session_id": "proc-1"}) == (
        "local_process", {
            "action": "status", "execution_id": "proc-1", "_native_poll": True,
            "_atlas_conversation_id": "",
        },
    )
    for source, target in (
        ("list", "list"), ("log", "read"), ("wait", "wait"),
        ("kill", "cancel"), ("write", "write_stdin"),
        ("submit", "submit_stdin"), ("close", "close_stdin"),
        ("handoff", "handoff"),
    ):
        args = {"action": source}
        expected = {"action": target}
        if source != "list":
            args["session_id"] = expected["execution_id"] = "proc-1"
        else:
            expected["execution_id"] = ""
        if source in {"write", "submit", "handoff"}:
            args["data"] = expected["data"] = "answer"
        if source == "log":
            expected["_line_offsets"] = True
        expected["_atlas_conversation_id"] = ""
        assert _translate("process_manage", {
            **args,
        }) == ("local_process", expected)


@pytest.mark.asyncio
async def test_runtime_bridges_thread_callbacks_and_uses_atlas_session_home(tmp_path, monkeypatch):
    captured = {}

    class UsageReportingFakeAtlasAgent(FakeAtlasAgent):
        def run_conversation(self, **kwargs):
            result = super().run_conversation(**kwargs)
            self.kwargs["hooks"].on_usage({
                "input_tokens": 37, "uncached_input_tokens": 37,
                "output_tokens": 12, "cached_input_tokens": 0,
                "cache_write_tokens": 0, "context_tokens": 49,
                "context_limit": 4096, "request_count": 1,
            })
            return result

    def factory(**kwargs):
        captured.update(kwargs)
        captured["home"] = os.environ.get("HERMES_HOME")
        return UsageReportingFakeAtlasAgent(**kwargs)

    models = SimpleNamespace(
        current_model="test-model",
        current_litellm_model="openai/test-model",
        gateway_base_url="http://fake.invalid/v1",
        _api_key="fake-key",
        list_models=lambda: [{"id": "test-model", "max_output_tokens": 1024}],
    )
    runtime = AtlasRuntime(data_dir=tmp_path / "atlas-data", model_manager=models,
                            agent_factory=factory)
    events = [event async for event in runtime.run_turn(
        message="continue",
        conversation_id="conversation-1",
        workspace=str(tmp_path),
        history=[{"role": "user", "content": "first"},
                 {"role": "assistant", "content": "reply"},
                 {"role": "tool", "content": "source"}],
        system_message="Atlas rules",
    )]

    assert [event["type"] for event in events] == [
        "chunk", "tool_call", "tool_result", "run.compaction.progress",
        "run_usage", "run_usage", "atlas.result",
    ]
    assert captured["home"] == str((tmp_path / "atlas-data" / "engine").resolve())
    assert captured["session_id"] == "conversation-1"
    assert captured["skip_memory"] is True
    assert captured["checkpoints_enabled"] is False
    assert captured["enabled_toolsets"] == [
        "file", "terminal", "todo", "clarify", "code_execution",
        "session_search", "delegation", "atlas",
    ]
    assert events[-1]["result"]["final_response"] == "reply"
    assert events[-2]["usage"]["context_tokens"] == 49
    assert events[-2]["usage"]["context_limit"] == 4096
    assert events[-3]["usage"]["request_id"] == events[-2]["usage"]["request_id"]
    assert "fake-key" not in repr(events)


@pytest.mark.asyncio
async def test_runtime_interrupts_atlas_when_atlas_cancel_is_set(tmp_path):
    started = threading.Event()
    release = threading.Event()
    agents = []

    class BlockingAgent(FakeAtlasAgent):
        def run_conversation(self, **_kwargs):
            started.set()
            release.wait(timeout=2)
            return {"final_response": "stopped", "messages": []}

        def interrupt(self, *, hard_cancel=False):
            super().interrupt(hard_cancel=hard_cancel)
            release.set()

    def factory(**kwargs):
        agent = BlockingAgent(**kwargs)
        agents.append(agent)
        return agent

    models = SimpleNamespace(
        current_model="test-model", current_litellm_model="openai/test-model",
        gateway_base_url="http://fake.invalid/v1", _api_key="fake-key",
        list_models=lambda: [{"id": "test-model"}],
    )
    cancel = asyncio.Event()
    runtime = AtlasRuntime(data_dir=tmp_path / "atlas-data", model_manager=models,
                            agent_factory=factory)
    stream = runtime.run_turn(message="x", conversation_id="c", workspace=None,
                              history=[], cancel_event=cancel)
    pending = asyncio.create_task(anext(stream))
    await asyncio.to_thread(started.wait, 1)
    cancel.set()
    events = [await pending]
    while events[-1]["type"] != "atlas.result":
        events.append(await anext(stream))
    assert events[-1]["type"] == "atlas.result"
    assert agents[0].interrupted
    await stream.aclose()
    assert agents[0].closed


@pytest.mark.asyncio
async def test_runtime_moa_uses_atlas_models_and_fake_reference_consult(tmp_path, monkeypatch):
    captured = {}

    class CapturingAgent(FakeAtlasAgent):
        def run_conversation(self, *, user_message, system_message, conversation_history, task_id=None):
            captured["system_message"] = system_message
            return {"final_response": "primary answer", "messages": conversation_history}

    async def consult(model, messages, api_key, api_base):
        captured.update({"model": model, "messages": messages,
                         "api_key": api_key, "api_base": api_base})
        return "reference says check the migration boundary"

    models = SimpleNamespace(
        current_model="primary",
        current_litellm_model="openai/primary",
        gateway_base_url="http://fake.invalid/v1",
        _api_key="fake-key",
        list_models=lambda: [
            {"id": "primary", "litellm_model": "openai/primary"},
            {"id": "reference", "litellm_model": "openai/reference"},
        ],
    )
    monkeypatch.setattr("atlas.config.get_config", lambda: {
        "moa.reference_models": ["reference"], "moa.max_references": 2,
    })
    runtime = AtlasRuntime(
        data_dir=tmp_path / "atlas-data", model_manager=models,
        agent_factory=CapturingAgent, reference_consult=consult,
    )
    events = [event async for event in runtime.run_turn(
        message="review this migration", conversation_id="moa-session", workspace=None,
        history=[], system_message="Atlas rules", moa_enabled=True,
    )]

    moa = next(event for event in events if event["type"] == "moa_references")
    assert moa["models"] == ["reference"]
    assert "migration boundary" in moa["references"][0]["text"]
    assert captured["model"] == "openai/reference"
    assert captured["api_key"] == "fake-key"
    assert captured["api_base"] == "http://fake.invalid/v1"
    assert captured["messages"][-1] == {
        "role": "user", "content": "review this migration",
    }
    assert "reference says check the migration boundary" in captured["system_message"]
    assert events[-1]["result"]["final_response"] == "primary answer"


@pytest.mark.asyncio
async def test_runtime_bridges_atlas_run_budget_reminders(tmp_path, monkeypatch):
    monkeypatch.setattr("atlas.config.get_config", lambda: {
        "agent.run_budget_seconds": 120,
        "agent.budget_warning_ratio": 0.8,
    })
    models = SimpleNamespace(
        current_model="test-model",
        current_litellm_model="openai/test-model",
        gateway_base_url="http://fake.invalid/v1",
        _api_key="fake-key",
        list_models=lambda: [{"id": "test-model", "max_output_tokens": 1024}],
    )
    agents = []

    class BudgetAgent(FakeAtlasAgent):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            agents.append(self)

        def run_conversation(self, *, user_message, system_message, conversation_history, task_id=None):
            return {"final_response": "budget answer", "messages": conversation_history}

    runtime = AtlasRuntime(
        data_dir=tmp_path / "atlas-data", model_manager=models, agent_factory=BudgetAgent,
    )
    events = [event async for event in runtime.run_turn(
        message="continue", conversation_id="budget-session", workspace=str(tmp_path),
        history=[], system_message="Atlas rules",
    )]
    assert agents[0].run_budget_seconds == 120
    assert agents[0].budget_warning_ratio == 0.8
    assert events[-1]["result"]["final_response"] == "budget answer"


@pytest.mark.asyncio
async def test_slow_agent_construction_does_not_block_the_event_loop(tmp_path):
    """Building the Hermes agent (imports, tool discovery) used to run on the event
    loop; on a busy machine that stalled WebSocket keepalive past its timeout."""
    import time

    class QuietAgent(FakeAtlasAgent):
        def run_conversation(self, **_kwargs):
            return {"final_response": "ok", "messages": []}

    def slow_factory(**kwargs):
        time.sleep(1.0)  # stands in for the multi-second first Hermes import/build
        return QuietAgent(**kwargs)

    models = SimpleNamespace(
        current_model="test-model", current_litellm_model="openai/test-model",
        gateway_base_url="http://fake.invalid/v1", _api_key="fake-key",
        list_models=lambda: [{"id": "test-model"}],
    )
    runtime = AtlasRuntime(data_dir=tmp_path / "atlas-data", model_manager=models,
                            agent_factory=slow_factory)
    gaps: list[float] = []
    stop = asyncio.Event()

    async def ticker() -> None:
        last = time.perf_counter()
        while not stop.is_set():
            await asyncio.sleep(0.02)
            now = time.perf_counter()
            gaps.append(now - last)
            last = now

    ticking = asyncio.create_task(ticker())
    while not gaps:  # the ticker must already be running before the turn starts
        await asyncio.sleep(0.01)
    stream = runtime.run_turn(message="x", conversation_id="c", workspace=None, history=[])
    async for event in stream:
        if event["type"] == "atlas.result":
            break
    await stream.aclose()
    stop.set()
    await ticking
    assert max(gaps) < 0.5, f"event loop stalled for {max(gaps):.2f}s"


@pytest.mark.asyncio
async def test_budget_stopped_turn_is_reported_as_failed(tmp_path, monkeypatch):
    """A turn the input-token budget stopped must not look completed (exit 0)."""
    monkeypatch.setenv("ATLAS_RUN_INPUT_TOKEN_LIMIT", "100")
    monkeypatch.setenv("ATLAS_RUN_BUDGET_ID", f"budget-stop-{tmp_path.name}")

    class BudgetedAgent(FakeAtlasAgent):
        def run_conversation(self, **_kwargs):
            blocked = self.kwargs["hooks"].before_provider_request(10_000, "req-1")
            assert blocked is True
            return {"final_response": "", "messages": []}

    models = SimpleNamespace(
        current_model="test-model", current_litellm_model="openai/test-model",
        gateway_base_url="http://fake.invalid/v1", _api_key="fake-key",
        list_models=lambda: [{"id": "test-model"}],
    )
    runtime = AtlasRuntime(data_dir=tmp_path / "atlas-data", model_manager=models,
                            agent_factory=BudgetedAgent)
    result = None
    async for event in runtime.run_turn(message="x", conversation_id="c", workspace=None,
                                        history=[]):
        if event["type"] == "atlas.result":
            result = event["result"]
    assert result is not None and result["failed"] is True
    assert "预算" in result["error"]
