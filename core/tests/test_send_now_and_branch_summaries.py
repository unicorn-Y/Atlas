"""I7 send-now steering + S2 branch summaries (core-refresh-map 2026-10-03)."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from atlas.engine import branch_summaries as bs
from atlas.engine.steer_dispatch import (
    apply_send_now,
    apply_steer_payload,
    is_send_now,
    queue_run_steer,
)
from tools.interrupt import consume_yield, is_thread_yield_requested


class SteerableAgent:
    """Fake Hermes agent with the steer/redirect/tool-worker control surface."""

    def __init__(self, *, executing_tools: bool = False, worker_tids: set[int] | None = None):
        self.steered: list[str] = []
        self.redirected: list[str] = []
        self._pending_steer: str | None = None
        self._executing_tools = executing_tools
        self._tool_worker_threads = worker_tids if worker_tids is not None else set()
        self._tool_worker_threads_lock = threading.Lock()

    def steer(self, text: str) -> bool:
        if not text or not text.strip():
            return False
        cleaned = text.strip()
        self.steered.append(cleaned)
        self._pending_steer = (self._pending_steer + "\n" + cleaned
                               if self._pending_steer else cleaned)
        return True

    def redirect(self, text: str) -> bool:
        if not text or not text.strip():
            return False
        self.redirected.append(text.strip())
        return True

    def drain(self) -> str | None:
        """Hermes' next-turn injection point: the pending steer becomes context."""
        text, self._pending_steer = self._pending_steer, None
        return text


# ---------------------------------------------------------------- I7: send-now


def test_send_now_backgrounds_running_tool_and_queues_message():
    agent = SteerableAgent(executing_tools=True, worker_tids={7_711_001})
    outcome = apply_send_now(agent, "先检查测试文件")
    assert outcome == {"accepted": True, "yield_requested": True}
    assert agent.steered == ["先检查测试文件"]
    # The running terminal tool is asked to yield: it hands its process to the
    # background registry and returns, so the tool CONTINUES in background.
    assert is_thread_yield_requested(7_711_001)
    assert consume_yield(7_711_001) is True
    assert consume_yield(7_711_001) is False  # bit consumed exactly once
    # The queued message is injected on the next model turn.
    assert agent.drain() == "先检查测试文件"
    assert agent.drain() is None


def test_send_now_without_backgroundable_tool_falls_back_to_queue():
    agent = SteerableAgent(executing_tools=True, worker_tids=set())  # e.g. a file tool
    outcome = apply_send_now(agent, "换个方向")
    assert outcome == {"accepted": True, "yield_requested": False}
    assert agent.steered == ["换个方向"]  # queued: existing steer behavior
    assert agent.redirected == []  # nothing was cancelled
    assert agent.drain() == "换个方向"


def test_send_now_with_no_tools_running_only_queues():
    agent = SteerableAgent(executing_tools=False, worker_tids={7_711_002})
    outcome = apply_send_now(agent, "继续")
    assert outcome == {"accepted": True, "yield_requested": False}
    assert is_thread_yield_requested(7_711_002) is False
    consume_yield(7_711_002)


def test_apply_steer_payload_flag_dispatch():
    send_now = SteerableAgent(executing_tools=True, worker_tids={7_711_003})
    outcome = apply_steer_payload(send_now, {"content": "a", "send_now": True, "immediate": True})
    assert outcome["send_now"] is True and outcome["immediate"] is False
    assert send_now.redirected == []  # send-now wins: never cancels
    consume_yield(7_711_003)

    immediate = SteerableAgent()
    outcome = apply_steer_payload(immediate, {"content": "b", "immediate": True})
    assert outcome == {"text": "b", "accepted": True, "immediate": True,
                       "send_now": False, "yield_requested": False}
    assert immediate.redirected == ["b"]

    plain = SteerableAgent()
    outcome = apply_steer_payload(plain, {"text": "c"})
    assert outcome["accepted"] is True and plain.steered == ["c"]
    assert is_send_now({"send_now": True}) and not is_send_now({})


def test_queue_run_steer_validation_and_legacy_payloads():
    run = SimpleNamespace(status="running", steer_queue=asyncio.Queue())
    assert queue_run_steer(run, {"content": "  ", "send_now": True}) == "invalid_content"
    assert queue_run_steer(run, {"content": "x", "immediate": "yes"}) == "invalid_immediate"
    assert queue_run_steer(run, {"content": "x", "send_now": 1}) == "invalid_send_now"
    done = SimpleNamespace(status="completed", steer_queue=asyncio.Queue())
    assert queue_run_steer(done, {"content": "x"}) == "run_not_active"

    assert queue_run_steer(run, {"content": "now", "send_now": True, "event_id": "e1"}) is None
    assert run.steer_queue.get_nowait() == {
        "content": "now", "event_id": "e1", "immediate": False, "send_now": True,
    }
    # Legacy payload without the field keeps the exact old shape plus send_now=False.
    assert queue_run_steer(run, {"content": "old"}) is None
    assert run.steer_queue.get_nowait()["send_now"] is False
    assert queue_run_steer(run, "not-a-dict") == "invalid_content"


# --------------------------------------------------- I7: runtime wiring (e2e)


class _RuntimeSteerableAgent:
    def __init__(self, *, started: threading.Event, release: threading.Event, **kwargs):
        self.steered: list[str] = []
        self._pending_steer: str | None = None
        self._executing_tools = False
        self._tool_worker_threads: set[int] = set()
        self._tool_worker_threads_lock = threading.Lock()
        self.worker_tid = threading.get_ident() + 7_711_000
        self._started, self._release = started, release

    def run_conversation(self, *, user_message, system_message, conversation_history,
                         task_id=None):
        # Simulate one long-running (backgroundable terminal) tool execution.
        self._executing_tools = True
        with self._tool_worker_threads_lock:
            self._tool_worker_threads.add(self.worker_tid)
        self._started.set()
        if not self._release.wait(timeout=5):
            raise AssertionError("tool was never released")
        with self._tool_worker_threads_lock:
            self._tool_worker_threads.discard(self.worker_tid)
        self._executing_tools = False
        return {"final_response": "done", "messages": []}

    def steer(self, text: str) -> bool:
        if not text or not text.strip():
            return False
        cleaned = text.strip()
        self.steered.append(cleaned)
        self._pending_steer = cleaned
        return True

    def drain(self) -> str | None:
        text, self._pending_steer = self._pending_steer, None
        return text

    def interrupt(self, *, hard_cancel=False):
        pass

    def close(self):
        pass


@pytest.mark.asyncio
async def test_runtime_send_now_yields_tool_and_steers_next_turn(tmp_path):
    from tools.interrupt import request_yield  # noqa: F401  (module import sanity)

    from atlas.engine.hermes_runtime import HermesRuntime

    started, release = threading.Event(), threading.Event()
    agents: list[_RuntimeSteerableAgent] = []

    def factory(**kwargs):
        agent = _RuntimeSteerableAgent(started=started, release=release, **kwargs)
        agents.append(agent)
        return agent

    models = SimpleNamespace(
        current_model="test-model", current_litellm_model="openai/test-model",
        gateway_base_url="http://fake.invalid/v1", _api_key="fake-key",
        list_models=lambda: [{"id": "test-model"}],
    )
    steer_queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
    runtime = HermesRuntime(data_dir=tmp_path / "atlas-data", model_manager=models,
                            agent_factory=factory)
    stream = runtime.run_turn(message="x", conversation_id="c", workspace=None,
                              history=[], steer_queue=steer_queue)
    pending = asyncio.create_task(anext(stream))
    await asyncio.to_thread(started.wait, 2)
    steer_queue.put_nowait({"content": "先看测试文件", "send_now": True})
    for _ in range(200):
        if agents[0].steered:
            break
        await asyncio.sleep(0.01)
    assert agents[0].steered == ["先看测试文件"]
    assert is_thread_yield_requested(agents[0].worker_tid)  # tool asked to background
    assert consume_yield(agents[0].worker_tid) is True

    events = [await pending]
    release.set()
    while events[-1]["type"] != "hermes.result":
        events.append(await anext(stream))
    steered = [event for event in events if event["type"] == "run_steered"]
    assert steered == [{
        "type": "run_steered", "content": "先看测试文件", "event_id": "",
        "immediate": False, "send_now": True, "yield_requested": True,
    }]
    assert agents[0].drain() == "先看测试文件"  # injected on the next model turn
    await stream.aclose()


# -------------------------------------------------------------- S2: summaries


@pytest.fixture(autouse=True)
def _reset_branch_summary_caches():
    bs._completed.clear()
    bs._inflight.clear()
    yield
    bs._completed.clear()
    bs._inflight.clear()


async def _seed_fork(tmp_path, name: str):
    from atlas.memory import MemoryStore

    memory = MemoryStore(db_path=tmp_path / f"{name}.db")
    await memory.init()
    from tests.fakes.session_store import save_memory_fixture_message

    parent = await memory.create_conversation("base")
    fork_point = await save_memory_fixture_message(memory, parent, "user", "start the refactor")
    await save_memory_fixture_message(memory, parent, "assistant", "refactored the engine half-way")
    child = str((await memory.fork_conversation(parent, fork_point))["id"])
    await memory.update_conversation(child, parent_conversation_id=parent,
                                     fork_message_id=fork_point)
    await save_memory_fixture_message(memory, child, "user", "switch to sqlite for the branch")
    await save_memory_fixture_message(memory, child, "assistant", "branch done: sqlite migration landed")
    return memory, parent, child, fork_point


@pytest.mark.asyncio
async def test_branch_summary_requested_once_and_cached(tmp_path):
    memory, parent, child, fork_point = await _seed_fork(tmp_path, "once")
    calls: list[tuple[str, list[dict[str, str]]]] = []
    mirrored: list[tuple[str, str, str, str]] = []

    async def fake_complete(model, messages):
        calls.append((model, messages))
        return "把引擎迁移到 SQLite 并验证通过"

    async def fake_mirror(parent_id, child_id, fork_id, content):
        mirrored.append((parent_id, child_id, fork_id, content))

    # First switch: nothing cached yet -> returns instantly without the model,
    # generation is scheduled in the background (never blocks the switch).
    first = await bs.branch_summaries(memory, parent, complete=fake_complete,
                                      mirror=fake_mirror)
    assert first == {}
    assert calls == []
    task = bs._inflight.get(child)
    assert task is not None
    assert await task == "分支摘要：把引擎迁移到 SQLite 并验证通过"
    assert len(calls) == 1
    assert mirrored == [(parent, child, fork_point,
                         "分支摘要：把引擎迁移到 SQLite 并验证通过")]

    # Second switch (and a memory-cache miss): served from cache, no new call.
    bs._completed.clear()
    second = await bs.branch_summaries(memory, parent, complete=fake_complete,
                                       mirror=fake_mirror)
    assert second == {child: "分支摘要：把引擎迁移到 SQLite 并验证通过"}
    assert len(calls) == 1
    persisted = await memory.get_conversation_messages(parent, limit=1000)
    summary_rows = [item for item in persisted
                    if item["metadata"].get("kind") == "branch_summary"]
    assert [row["content"] for row in summary_rows] == [
        "分支摘要：把引擎迁移到 SQLite 并验证通过",
    ]
    assert summary_rows[0]["metadata"]["child_conversation_id"] == child


@pytest.mark.asyncio
async def test_branch_summary_concurrent_switches_share_one_generation(tmp_path):
    memory, parent, child, _ = await _seed_fork(tmp_path, "singleflight")
    calls: list[tuple[str, list[dict[str, str]]]] = []

    async def fake_complete(model, messages):
        calls.append((model, messages))
        await asyncio.sleep(0.01)
        return "single flight summary"

    async def fake_mirror(*_args):
        return None

    await asyncio.gather(
        bs.branch_summaries(memory, parent, complete=fake_complete, mirror=fake_mirror),
        bs.branch_summaries(memory, parent, complete=fake_complete, mirror=fake_mirror),
    )
    tasks = [task for task in bs._inflight.values() if not task.done()]
    await asyncio.gather(*tasks)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_branch_summary_skips_non_branch_and_unprogressed_forks(tmp_path):
    memory, parent, child, fork_point = await _seed_fork(tmp_path, "skips")
    plain = await memory.create_conversation("not a branch")
    calls: list[tuple[str, list[dict[str, str]]]] = []

    async def fake_complete(model, messages):
        calls.append((model, messages))
        return "should not be called"

    assert await bs.generate_branch_summary(memory, plain, complete=fake_complete) is None
    # Child without post-fork progress: strip everything copied into the fork.
    child_messages = await memory.get_conversation_messages(child, limit=1000)
    await memory.truncate_conversation(child, child_messages[0]["id"])
    assert await bs.generate_branch_summary(memory, child, complete=fake_complete) is None
    assert calls == []


@pytest.mark.asyncio
async def test_resolve_summary_model_prefers_compression_setting(tmp_path, monkeypatch):
    monkeypatch.setattr("atlas.config.load_user_settings",
                        lambda: {"compression_model": "cheap"})
    models = SimpleNamespace(
        current_model="main",
        list_models=lambda: [{"id": "main", "litellm_model": "openai/main"},
                             {"id": "cheap", "litellm_model": "openai/cheap"}],
    )
    assert bs.resolve_summary_model(models) == "openai/cheap"
    monkeypatch.setattr("atlas.config.load_user_settings", lambda: {})
    assert bs.resolve_summary_model(models) == "openai/main"
