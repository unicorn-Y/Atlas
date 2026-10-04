"""H3 concurrency & resource governance: reuse, bounds, cleanup.

Covers taskbook §5 测试 items:
- 20 turns register MCP exactly once (config-fingerprint cache);
- os.environ is not mutated while turns run (HERMES_HOME written once per runtime);
- one session across N turns builds ONE AIAgent; a model switch rebuilds and closes the old one;
- a 5s model wait no longer polls the event loop (>=90% below the H0 baseline of 197
  iterations recorded in tasks/results/ATLAS-H1-baseline.json);
- 100 automatic compactions leave the lifecycle-future set empty (no future leaks);
- LRU overflow closes the oldest cached agent; idle timeout reclaims agents;
- teardown (aclose) leaves no pending runtime tasks or live agents.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from collections.abc import MutableMapping
from types import SimpleNamespace

import pytest

from atlas.engine import hermes_runtime
from atlas.engine.hermes_runtime import HermesRuntime
from tests.fakes.fake_llm_provider import FakeLLMServer, Text, write_hermes_home


class FakeHermesAgent:
    """Minimal Hermes agent double exercising the runtime's resource surface."""

    def __init__(self, *, registry: list | None = None, **kwargs):
        self.kwargs = kwargs
        self.closed = False
        self.steered: list[str] = []
        self.interrupted = False
        if registry is not None:
            registry.append(self)

    def run_conversation(self, *, user_message, system_message, conversation_history):
        return {"final_response": f"reply:{user_message}", "messages": conversation_history}

    def steer(self, text: str) -> bool:
        self.steered.append(text)
        return True

    def interrupt(self, *, hard_cancel: bool = False) -> bool:
        self.interrupted = True
        return True

    def close(self) -> None:
        self.closed = True


def _models(fake, rows, current="main-model"):
    return SimpleNamespace(
        current_model=current,
        current_litellm_model=f"openai/{current}",
        gateway_base_url=fake.base_url,
        _api_key="sk-fake-e2e",
        list_models=lambda: rows,
    )


class _CountingEnviron(MutableMapping):
    """os.environ spy counting HERMES_HOME writes during a run."""

    def __init__(self, inner):
        self._inner = inner
        self.writes: list[str] = []

    def __getitem__(self, key):
        return self._inner[key]

    def __setitem__(self, key, value):
        self.writes.append(key)
        self._inner[key] = value

    def __delitem__(self, key):
        del self._inner[key]

    def __iter__(self):
        return iter(self._inner)

    def __len__(self):
        return len(self._inner)

    def copy(self):
        return dict(self._inner)


@pytest.fixture
def mcp_registration_probe(monkeypatch):
    """Reset the process MCP fingerprint and count real registration calls."""
    hermes_runtime.reset_runtime_registrations()
    calls: list[dict] = []

    def counting_register(_self):
        calls.append({})
        return []

    monkeypatch.setattr(HermesRuntime, "_register_atlas_mcp", counting_register)
    return calls


@pytest.mark.asyncio
async def test_mcp_registers_once_across_twenty_turns(tmp_path, monkeypatch, mcp_registration_probe):
    with FakeLLMServer(default_text="turn answer") as fake:
        models = _models(fake, [{"id": "main-model", "litellm_model": "openai/main-model"}])
        runtime = HermesRuntime(data_dir=tmp_path / "data", model_manager=models,
                                agent_factory=FakeHermesAgent)
        import atlas.engine.hermes_policy as hermes_policy
        import atlas.engine.tool_registry as tool_registry

        monkeypatch.setattr(hermes_policy, "install_atlas_policy_plugin", lambda: None)
        monkeypatch.setattr(tool_registry, "bind_atlas_tools", lambda *_args: None)
        monkeypatch.setattr(tool_registry, "activate_atlas_tool_context", lambda *_args: None)
        monkeypatch.setattr(tool_registry, "clear_atlas_tool_context", lambda: None)

        for index in range(20):
            events = [event async for event in runtime.run_turn(
                message=f"turn {index}", conversation_id="mcp-once",
                workspace=str(tmp_path), history=[],
                atlas_agent=SimpleNamespace(_delegation=object()),
                atlas_context=SimpleNamespace(mode="act"),
            )]
            assert events[-1]["type"] == "hermes.result"

        assert len(mcp_registration_probe) == 1


@pytest.mark.asyncio
async def test_mcp_config_change_refreshes_registration(tmp_path, monkeypatch):
    class FixtureConfig(dict):
        pass

    config = FixtureConfig({"tools.servers": {}, "tools.auto_start": []})
    monkeypatch.setattr("atlas.config.get_config", lambda: config)
    calls: list[int] = []

    def counting_register(_self):
        calls.append(1)
        return ["mcp-files"] if config["tools.servers"] else []

    monkeypatch.setattr(HermesRuntime, "_register_atlas_mcp", counting_register)
    hermes_runtime.reset_runtime_registrations()
    models = SimpleNamespace(current_model="m", current_litellm_model="openai/m",
                             gateway_base_url="http://fake.invalid/v1", _api_key="k",
                             list_models=lambda: [])
    runtime = HermesRuntime(data_dir=tmp_path / "data", model_manager=models,
                            agent_factory=FakeHermesAgent)

    assert runtime._ensure_atlas_mcp_registered() == []
    assert len(calls) == 1
    # Unchanged fingerprint: no second registration pass.
    assert runtime._ensure_atlas_mcp_registered() == []
    assert len(calls) == 1
    # Changed [tools.servers]: incremental refresh runs exactly one more pass.
    config["tools.servers"] = {
        "files": {"transport": "stdio", "command": "echo", "args": [], "env": {}},
    }
    assert runtime._ensure_atlas_mcp_registered() == ["mcp-files"]
    assert len(calls) == 2
    assert runtime._ensure_atlas_mcp_registered() == ["mcp-files"]
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_os_environ_stable_during_runs_and_home_written_once(tmp_path, monkeypatch):
    with FakeLLMServer(default_text="env answer") as fake:
        home = tmp_path / "engine"
        write_hermes_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        models = _models(fake, [{"id": "main-model", "litellm_model": "openai/main-model"}])
        spy = _CountingEnviron(os.environ)
        monkeypatch.setattr(os, "environ", spy)
        runtime = HermesRuntime(data_dir=tmp_path / "data", model_manager=models,
                                agent_factory=FakeHermesAgent)
        snapshot = dict(os.environ)
        for index in range(3):
            events = [event async for event in runtime.run_turn(
                message=f"turn {index}", conversation_id="env-stable",
                workspace=str(tmp_path), history=[],
            )]
            assert events[-1]["type"] == "hermes.result"
        assert dict(os.environ) == snapshot
        # Construction stamps HERMES_HOME once; turns never rewrite it (H3 rule 1).
        assert spy.writes.count("HERMES_HOME") == 1


@pytest.mark.asyncio
async def test_same_session_reuses_one_agent_and_model_switch_rebuilds(tmp_path):
    with FakeLLMServer(default_text="cache answer") as fake:
        models = _models(fake, [
            {"id": "main-model", "litellm_model": "openai/main-model"},
            {"id": "other-model", "litellm_model": "openai/other-model"},
        ])
        agents: list[FakeHermesAgent] = []
        runtime = HermesRuntime(
            data_dir=tmp_path / "data", model_manager=models,
            agent_factory=lambda **kwargs: FakeHermesAgent(registry=agents, **kwargs),
        )
        for index in range(5):
            events = [event async for event in runtime.run_turn(
                message=f"turn {index}", conversation_id="reuse-session",
                workspace=str(tmp_path), history=[],
            )]
            assert events[-1]["type"] == "hermes.result"
        assert len(agents) == 1

        # Model switch invalidates the cache entry and closes the replaced agent.
        events = [event async for event in runtime.run_turn(
            message="after switch", conversation_id="reuse-session",
            workspace=str(tmp_path), history=[], model_id="other-model",
        )]
        assert events[-1]["type"] == "hermes.result"
        assert len(agents) == 2
        assert agents[0].closed is True
        assert agents[1].closed is False
        assert agents[1].kwargs["model"] == "openai/other-model"

        # Switching back builds a third agent (the cached entry was the other model).
        events = [event async for event in runtime.run_turn(
            message="back again", conversation_id="reuse-session",
            workspace=str(tmp_path), history=[], model_id="main-model",
        )]
        assert events[-1]["type"] == "hermes.result"
        assert len(agents) == 3
        assert agents[2].kwargs["model"] == "openai/main-model"
        await runtime.aclose()
        assert all(agent.closed for agent in agents)


@pytest.mark.asyncio
async def test_abandoned_stream_closes_agent_and_skips_cache(tmp_path):
    """aclose()/cancellation must not leave a half-turn agent in the reuse cache."""
    with FakeLLMServer(default_text="unused") as fake:
        agents: list[FakeHermesAgent] = []

        class BlockingAgent(FakeHermesAgent):
            def run_conversation(self, **kwargs):
                time.sleep(0.2)
                return {"final_response": "late", "messages": []}

        runtime = HermesRuntime(
            data_dir=tmp_path / "data", model_manager=_models(fake, []),
            agent_factory=lambda **kwargs: BlockingAgent(registry=agents, **kwargs),
        )
        stream = runtime.run_turn(message="x", conversation_id="abandoned",
                                  workspace=None, history=[])
        async for _event in stream:
            break  # abandon after the first event
        await stream.aclose()
        assert agents[0].closed is True
        assert "abandoned" not in runtime._agent_cache
        await runtime.aclose()


@pytest.mark.asyncio
async def test_lru_overflow_closes_oldest_agent(tmp_path, monkeypatch):
    class FixtureConfig(dict):
        pass

    monkeypatch.setattr("atlas.config.get_config", lambda: FixtureConfig({
        "agent.agent_cache_size": 2, "agent.agent_cache_idle_seconds": 1800.0,
    }))
    with FakeLLMServer(default_text="lru answer") as fake:
        agents: list[FakeHermesAgent] = []
        runtime = HermesRuntime(
            data_dir=tmp_path / "data", model_manager=_models(fake, []),
            agent_factory=lambda **kwargs: FakeHermesAgent(registry=agents, **kwargs),
        )
        for conversation in ("c1", "c2", "c3"):
            events = [event async for event in runtime.run_turn(
                message="x", conversation_id=conversation, workspace=None, history=[],
            )]
            assert events[-1]["type"] == "hermes.result"
        assert set(runtime._agent_cache) == {"c2", "c3"}
        assert [agent.closed for agent in agents] == [True, False, False]
        await runtime.aclose()


@pytest.mark.asyncio
async def test_idle_timeout_reclaims_agents(tmp_path, monkeypatch):
    class FixtureConfig(dict):
        pass

    monkeypatch.setattr("atlas.config.get_config", lambda: FixtureConfig({
        "agent.agent_cache_size": 16, "agent.agent_cache_idle_seconds": 0.05,
    }))
    with FakeLLMServer(default_text="idle answer") as fake:
        agents: list[FakeHermesAgent] = []
        runtime = HermesRuntime(
            data_dir=tmp_path / "data", model_manager=_models(fake, []),
            agent_factory=lambda **kwargs: FakeHermesAgent(registry=agents, **kwargs),
        )
        events = [event async for event in runtime.run_turn(
            message="x", conversation_id="idle-1", workspace=None, history=[],
        )]
        assert events[-1]["type"] == "hermes.result"
        await asyncio.sleep(0.15)
        events = [event async for event in runtime.run_turn(
            message="y", conversation_id="idle-2", workspace=None, history=[],
        )]
        assert events[-1]["type"] == "hermes.result"
        deadline = time.monotonic() + 5
        while agents[0].closed is False and time.monotonic() < deadline:
            await asyncio.sleep(0.02)
        assert agents[0].closed is True
        assert set(runtime._agent_cache) == {"idle-2"}
        await runtime.aclose()


@pytest.mark.asyncio
async def test_automatic_compaction_futures_do_not_leak(tmp_path):
    """100 automatic compactions leave the lifecycle-future set empty (H3 rule 6)."""
    hermes_runtime._LIFECYCLE_FUTURES.clear()
    with FakeLLMServer(default_text="ok") as fake:
        agents: list[FakeHermesAgent] = []

        class CompressingAgent(FakeHermesAgent):
            def run_conversation(self, *, user_message, system_message, conversation_history):
                self.kwargs["event_callback"]("session:compress", {"compression_count": 1})
                return {"final_response": "compressed", "messages": []}

        hook_calls: list[dict] = []

        async def lifecycle_hook(event_name, payload):
            hook_calls.append({"event": event_name, **payload})
            return {}

        runtime = HermesRuntime(
            data_dir=tmp_path / "data", model_manager=_models(fake, []),
            agent_factory=lambda **kwargs: CompressingAgent(registry=agents, **kwargs),
        )
        for _ in range(100):
            events = [event async for event in runtime.run_turn(
                message="grow the context", conversation_id="compact-session",
                workspace=None, history=[], lifecycle_hook_callback=lifecycle_hook,
            )]
            assert events[-1]["type"] == "hermes.result"
        deadline = time.monotonic() + 5
        while hermes_runtime._LIFECYCLE_FUTURES and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
        assert hermes_runtime._LIFECYCLE_FUTURES == set()
        assert len(hook_calls) == 100
        await runtime.aclose()


@pytest.mark.asyncio
async def test_event_driven_notifications_reach_running_turn(tmp_path, monkeypatch):
    """A notification published mid-run steers the agent without any polling timer."""
    from atlas.engine.notifications import publish_notification

    class FixtureConfig(dict):
        db_path = tmp_path / "config.db"

    monkeypatch.setattr("atlas.config.get_config", lambda: FixtureConfig({
        "tools.servers": {}, "tools.auto_start": [],
    }))
    import atlas.engine.hermes_policy as hermes_policy
    import atlas.engine.tool_registry as tool_registry

    monkeypatch.setattr(hermes_policy, "install_atlas_policy_plugin", lambda: None)
    monkeypatch.setattr(tool_registry, "bind_atlas_tools", lambda *_args: None)
    with FakeLLMServer(default_text="notified") as fake:
        agents: list[FakeHermesAgent] = []

        class SlowAgent(FakeHermesAgent):
            def run_conversation(self, *, user_message, system_message, conversation_history):
                started.set()
                release.wait(timeout=5)
                return {"final_response": "done", "messages": []}

        started, release = threading.Event(), threading.Event()
        runtime = HermesRuntime(
            data_dir=tmp_path / "data", model_manager=_models(fake, []),
            agent_factory=lambda **kwargs: SlowAgent(registry=agents, **kwargs),
        )
        stream = runtime.run_turn(
            message="long turn", conversation_id="notify-session", workspace=None,
            history=[], atlas_agent=SimpleNamespace(),
            atlas_context=SimpleNamespace(mode="act"),
        )
        consume = asyncio.create_task(_drain(stream))
        await asyncio.to_thread(started.wait, 5)
        publish_notification("notify-session", kind="process.completed",
                             content="process exit=0; output READY", source_id="s1")
        deadline = time.monotonic() + 5
        while not agents[0].steered and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
        assert agents[0].steered == ["后台通知（process.completed）：\nprocess exit=0; output READY"]
        release.set()
        events = await consume
        assert events[-1]["type"] == "hermes.result"
        await runtime.aclose()


async def _drain(stream) -> list[dict]:
    return [event async for event in stream]


@pytest.mark.asyncio
async def test_waiting_on_model_no_longer_polls_event_loop(tmp_path, monkeypatch):
    """A 5s real model HTTP wait must cut loop wakeups >=90% vs the H0 baseline (197)."""
    def slow_responder(_request):
        time.sleep(5.0)
        return Text("slow model answered")

    with FakeLLMServer(slow_responder) as fake:
        home = tmp_path / "engine"
        write_hermes_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        models = _models(fake, [{"id": "main-model", "litellm_model": "openai/main-model"}])
        runtime = HermesRuntime(data_dir=tmp_path / "data", model_manager=models)

        loop = asyncio.get_running_loop()
        iterations = 0
        original_run_once = loop._run_once

        def counted_run_once() -> None:
            nonlocal iterations
            original_run_once()
            iterations += 1

        loop._run_once = counted_run_once
        try:
            async def consume():
                first_chunk: dict | None = None
                async for event in runtime.run_turn(
                    message="wait on the model", conversation_id="wait-session",
                    workspace=str(tmp_path), history=[],
                ):
                    if event.get("type") == "chunk":
                        first_chunk = event
                        return iterations
                return iterations

            await asyncio.to_thread(lambda: None)  # settle startup tasks
            iterations_before = iterations
            waited_iterations = await asyncio.wait_for(consume(), timeout=30)
            assert waited_iterations is not None
        finally:
            loop._run_once = original_run_once

        # H0 baseline: 197 iterations for a 5s wait (50ms queue poll + 250ms DB poll).
        # Event-driven consumption: the consumer blocks on queue.get() with no timers.
        assert iterations - iterations_before < 20, iterations
        await runtime.aclose()
