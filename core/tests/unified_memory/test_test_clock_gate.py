"""F3-B3：``occurred_at`` 测试时钟闸门。

评测"隔几天"场景需要虚拟时间；生产路径必须永远用真实时间。闸门
``resolve_test_clock`` 的两个必要条件（缺一即拒）：

1. ``event_class == "TEST"``（``ATLAS_UNIFIED_EVENT_CLASS``）；
2. 隔离数据根（``ATLAS_DATA_DIR`` 已设置且不等于仓库根）。

本文件既测闸门本身，也测**真实捕获点**（``run_phases._capture_run_user_message``）
在两条路径上的实际 ``occurred_at`` —— 不是只测一个纯函数。
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import SystemMessage

import atlas.agent as agent_module
import atlas.agent.run_phases as run_phases
from atlas.agent.run_phases import (
    RunCallbacks,
    RunRequest,
    _capture_run_user_message,
    _RunState,
    execute_run,
)
from atlas.config import AtlasConfig
from atlas.memory.capture import CaptureService
from atlas.memory.test_clock import isolated_test_environment, resolve_test_clock
from atlas.time_context import now_local, now_utc
from atlas.time_context import test_clock_context as clock_context

CLOCK = "2026-10-05 09:00:00"
REAL = "2026-10-09 13:00:00"


@pytest.fixture
def isolated(monkeypatch, tmp_path: Path):
    """TEST + 隔离数据根（两个条件都满足）。"""
    monkeypatch.setenv("ATLAS_UNIFIED_EVENT_CLASS", "TEST")
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path / "atlas_data"))
    return tmp_path


# ----------------------------------------------------------- 闸门本身

def test_gate_accepts_only_test_and_isolated(isolated) -> None:
    assert isolated_test_environment() is True
    # naive 入 → naive 出（场景内相对时间，不擅自补时区）
    assert resolve_test_clock(CLOCK) == "2026-10-05T09:00:00"
    # ISO 带偏移原样保留
    assert resolve_test_clock("2026-10-05T09:00:00+08:00") == "2026-10-05T09:00:00+08:00"


def test_shared_clock_uses_user_local_zone_and_resets(isolated) -> None:
    config = {"user": {"timezone": "Asia/Hong_Kong"}}
    simulated_utc = datetime(2026, 10, 5, 1, tzinfo=UTC)

    with clock_context(CLOCK, config=config, event_class="TEST"):
        assert now_utc() == simulated_utc
        assert now_local(config).isoformat() == "2026-10-05T09:00:00+08:00"

    assert now_utc() != simulated_utc


def test_shared_clock_normalizes_aware_and_rejects_nested_production(isolated, monkeypatch) -> None:
    config = {"user": {"timezone": "Asia/Hong_Kong"}}
    simulated_utc = datetime(2026, 10, 5, 1, tzinfo=UTC)

    with clock_context("2026-10-05T09:00:00+08:00", config=config,
                       event_class="TEST"):
        assert now_utc() == simulated_utc
        monkeypatch.setenv("ATLAS_UNIFIED_EVENT_CLASS", "PRODUCTION")
        with clock_context(CLOCK, config=config):
            assert now_utc() != simulated_utc
        assert now_utc() == simulated_utc


def test_clock_context_rejects_dst_gap_without_aborting(isolated) -> None:
    config = {"user": {"timezone": "America/New_York"}}
    with clock_context("2026-03-08T02:30:00", config=config, event_class="TEST") as value:
        assert value is None
        assert now_utc().year != 2026 or now_utc().month != 3 or now_utc().day != 8


def test_execute_run_injects_gated_local_clock_and_resets(monkeypatch, isolated) -> None:
    config = AtlasConfig({"user": {"timezone": "Asia/Hong_Kong"}})
    monkeypatch.setattr(agent_module, "get_config", lambda: config)
    fake_agent = SimpleNamespace(
        _skills=None, _projects=None,
        _multimodal_content=lambda text, attachments: text,
    )
    observed: list[str] = []

    async def empty_phase(agent, state):
        if False:
            yield {}

    async def turn(agent, state):
        observed.extend(str(item.content) for item in state.initial_messages
                        if isinstance(item, SystemMessage))
        yield {"type": "done"}

    for name in (
        "_phase_begin", "_phase_prompt_hook", "_phase_goal_knowledge",
        "_phase_pre_plan_constraints", "_phase_plan", "_phase_context",
    ):
        monkeypatch.setattr(run_phases, name, empty_phase)
    monkeypatch.setattr(run_phases, "_turn", turn)

    async def collect():
        return [event async for event in execute_run(
            fake_agent, RunRequest(message="hello", conversation_id="c1",
                                   test_clock=CLOCK), RunCallbacks(),
        )]

    events = asyncio.run(collect())
    simulated_utc = datetime(2026, 10, 5, 1, tzinfo=UTC)
    clock_prompt = next(text for text in observed if text.startswith("Current user-local"))
    assert "2026-10-05T09:00:00+08:00 (Asia/Hong_Kong)" in clock_prompt
    assert events == [{"type": "done"}]
    assert now_utc() != simulated_utc


def test_execute_run_ignores_supplied_clock_in_production(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ATLAS_UNIFIED_EVENT_CLASS", "PRODUCTION")
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path / "atlas_data"))
    config = AtlasConfig({"user": {"timezone": "Asia/Hong_Kong"}})
    monkeypatch.setattr(agent_module, "get_config", lambda: config)
    fake_agent = SimpleNamespace(
        _skills=None, _projects=None,
        _multimodal_content=lambda text, attachments: text,
    )
    observed: list[str] = []

    async def empty_phase(agent, state):
        if False:
            yield {}

    async def turn(agent, state):
        observed.extend(str(item.content) for item in state.initial_messages
                        if isinstance(item, SystemMessage))
        yield {"type": "done"}

    for name in (
        "_phase_begin", "_phase_prompt_hook", "_phase_goal_knowledge",
        "_phase_pre_plan_constraints", "_phase_plan", "_phase_context",
    ):
        monkeypatch.setattr(run_phases, name, empty_phase)
    monkeypatch.setattr(run_phases, "_turn", turn)

    async def collect():
        return [event async for event in execute_run(
            fake_agent, RunRequest(message="hello", conversation_id="c1",
                                   test_clock=CLOCK), RunCallbacks(),
        )]

    assert asyncio.run(collect()) == [{"type": "done"}]
    clock_prompt = next(text for text in observed if text.startswith("Current user-local"))
    assert "2026-10-05T09:00:00" not in clock_prompt
    assert "(Asia/Hong_Kong)" in clock_prompt


def test_execute_run_clock_resets_when_async_generator_is_closed(monkeypatch, isolated) -> None:
    config = AtlasConfig({"user": {"timezone": "Asia/Hong_Kong"}})
    monkeypatch.setattr(agent_module, "get_config", lambda: config)
    fake_agent = SimpleNamespace(
        _skills=None, _projects=None,
        _multimodal_content=lambda text, attachments: text,
    )
    finalized: list[bool] = []

    async def empty_phase(agent, state):
        if False:
            yield {}

    async def turn(agent, state):
        try:
            yield {"type": "chunk", "content": "partial"}
            await asyncio.Event().wait()
        finally:
            finalized.append(True)

    for name in (
        "_phase_begin", "_phase_prompt_hook", "_phase_goal_knowledge",
        "_phase_pre_plan_constraints", "_phase_plan", "_phase_context",
    ):
        monkeypatch.setattr(run_phases, name, empty_phase)
    monkeypatch.setattr(run_phases, "_turn", turn)

    async def close_run():
        stream = execute_run(
            fake_agent, RunRequest(message="hello", conversation_id="c1",
                                   test_clock=CLOCK), RunCallbacks(),
        )
        assert await anext(stream) == {"type": "chunk", "content": "partial"}
        assert now_utc() == datetime(2026, 10, 5, 1, tzinfo=UTC)
        await stream.aclose()
        assert finalized == [True]
        return now_utc()

    assert asyncio.run(close_run()) != datetime(2026, 10, 5, 1, tzinfo=UTC)


def test_execute_run_clock_resets_after_task_cancellation(monkeypatch, isolated) -> None:
    config = AtlasConfig({"user": {"timezone": "Asia/Hong_Kong"}})
    monkeypatch.setattr(agent_module, "get_config", lambda: config)
    fake_agent = SimpleNamespace(
        _skills=None, _projects=None,
        _multimodal_content=lambda text, attachments: text,
    )
    after_cancel: list[datetime] = []
    yielded = asyncio.Event()

    async def empty_phase(agent, state):
        if False:
            yield {}

    async def turn(agent, state):
        yielded.set()
        yield {"type": "chunk", "content": "partial"}
        await asyncio.Event().wait()

    for name in (
        "_phase_begin", "_phase_prompt_hook", "_phase_goal_knowledge",
        "_phase_pre_plan_constraints", "_phase_plan", "_phase_context",
    ):
        monkeypatch.setattr(run_phases, name, empty_phase)
    monkeypatch.setattr(run_phases, "_turn", turn)

    async def consume():
        try:
            async for _ in execute_run(
                fake_agent,
                RunRequest(message="hello", conversation_id="cancel-clock",
                           test_clock=CLOCK),
                RunCallbacks(),
            ):
                assert now_utc() == datetime(2026, 10, 5, 1, tzinfo=UTC)
        finally:
            after_cancel.append(now_utc())

    async def cancel_run():
        task = asyncio.create_task(consume())
        await yielded.wait()
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel_run())
    assert len(after_cancel) == 1
    assert after_cancel[0] != datetime(2026, 10, 5, 1, tzinfo=UTC)


def test_concurrent_runs_keep_distinct_request_clocks(monkeypatch, isolated) -> None:
    config = AtlasConfig({"user": {"timezone": "Asia/Hong_Kong"}})
    monkeypatch.setattr(agent_module, "get_config", lambda: config)
    fake_agent = SimpleNamespace(
        _skills=None, _projects=None,
        _multimodal_content=lambda text, attachments: text,
    )
    observed: dict[str, datetime] = {}

    async def empty_phase(agent, state):
        if False:
            yield {}

    async def turn(agent, state):
        await asyncio.sleep(0)
        observed[state.request.conversation_id] = now_utc()
        yield {"type": "done"}

    for name in (
        "_phase_begin", "_phase_prompt_hook", "_phase_goal_knowledge",
        "_phase_pre_plan_constraints", "_phase_plan", "_phase_context",
    ):
        monkeypatch.setattr(run_phases, name, empty_phase)
    monkeypatch.setattr(run_phases, "_turn", turn)

    async def collect(conversation_id: str, test_clock: str):
        return [event async for event in execute_run(
            fake_agent,
            RunRequest(message="hello", conversation_id=conversation_id,
                       test_clock=test_clock),
            RunCallbacks(),
        )]

    async def run_both():
        return await asyncio.gather(
            collect("clock-a", "2026-10-05T09:00:00+08:00"),
            collect("clock-b", "2026-10-06T09:00:00+08:00"),
        )

    assert asyncio.run(run_both()) == [[{"type": "done"}], [{"type": "done"}]]
    assert observed == {
        "clock-a": datetime(2026, 10, 5, 1, tzinfo=UTC),
        "clock-b": datetime(2026, 10, 6, 1, tzinfo=UTC),
    }


def test_clock_context_does_not_leak_to_task_started_before_request(isolated) -> None:
    config = {"user": {"timezone": "Asia/Hong_Kong"}}
    release = asyncio.Event()

    async def read_clock_after_release():
        await release.wait()
        return now_utc()

    async def run():
        unrelated = asyncio.create_task(read_clock_after_release())
        with clock_context(CLOCK, config=config, event_class="TEST"):
            release.set()
            other_task_clock = await unrelated
            assert now_utc() == datetime(2026, 10, 5, 1, tzinfo=UTC)
            return other_task_clock

    assert asyncio.run(run()) != datetime(2026, 10, 5, 1, tzinfo=UTC)


def test_gate_rejects_production_event_class(monkeypatch, tmp_path: Path) -> None:
    """隔离根但 event_class=PRODUCTION → 拒（生产事件类不许虚拟时间）。"""
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path / "atlas_data"))
    monkeypatch.setenv("ATLAS_UNIFIED_EVENT_CLASS", "PRODUCTION")
    assert resolve_test_clock(CLOCK) is None


def test_gate_rejects_missing_event_class(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path / "atlas_data"))
    monkeypatch.delenv("ATLAS_UNIFIED_EVENT_CLASS", raising=False)
    assert resolve_test_clock(CLOCK) is None


def test_gate_rejects_non_isolated_root(monkeypatch) -> None:
    """TEST 但数据根就是仓库根（=生产）→ 拒。"""
    from atlas.config import PROJECT_ROOT

    monkeypatch.setenv("ATLAS_UNIFIED_EVENT_CLASS", "TEST")
    monkeypatch.setenv("ATLAS_DATA_DIR", str(PROJECT_ROOT))
    assert isolated_test_environment() is False
    assert resolve_test_clock(CLOCK) is None


def test_gate_rejects_unset_data_dir(monkeypatch) -> None:
    monkeypatch.setenv("ATLAS_UNIFIED_EVENT_CLASS", "TEST")
    monkeypatch.delenv("ATLAS_DATA_DIR", raising=False)
    assert resolve_test_clock(CLOCK) is None


@pytest.mark.parametrize("value", ["", "   ", None, "昨天", "2026-13-45"])
def test_gate_rejects_empty_or_unparsable(isolated, value) -> None:
    assert resolve_test_clock(value) is None


# ------------------------------------------------ 真实捕获点（两条路径）

class _Capture:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def capture_user_message(self, session_id, message_id, text, occurred_at=None, **kw):
        self.calls.append({"session_id": session_id, "message_id": message_id,
                           "text": text, "occurred_at": occurred_at, **kw})
        return {"ok": True}


def _install(monkeypatch, tmp_path: Path, capture: _Capture) -> None:
    """把捕获点的三个依赖换成探针（DATA_ROOT / 会话读取 / 采集服务）。"""
    import atlas.engine.session_sync as session_sync
    import atlas.memory.capture as capture_mod

    monkeypatch.setattr(agent_module, "get_config", lambda: AtlasConfig({
        "user": {"timezone": "Asia/Hong_Kong"},
    }))
    import atlas.config
    monkeypatch.setattr(atlas.config, "DATA_ROOT", tmp_path / "data", raising=False)
    monkeypatch.setattr(session_sync, "read_session_all_messages",
                        lambda home, conv: [{
                            "id": "msg-1", "role": "user",
                            "content": "帮我记一下", "created_at": REAL,
                        }])
    monkeypatch.setattr(capture_mod, "get_capture_service", lambda: capture)
    sys.modules.setdefault("atlas.memory.capture", capture_mod)


def _state(test_clock: str | None) -> _RunState:
    return _RunState(
        request=RunRequest(message="帮我记一下", conversation_id="conv-1",
                           run_id="run-actual-1", test_clock=test_clock),
        callbacks=RunCallbacks(), message="帮我记一下",
        preexisting_user_message_ids=set())


def test_capture_uses_test_clock_when_gate_opens(monkeypatch, isolated) -> None:
    capture = _Capture()
    _install(monkeypatch, isolated, capture)
    asyncio.run(_capture_run_user_message(_state(CLOCK)))
    assert capture.calls[0]["occurred_at"] == "2026-10-05T09:00:00+08:00"
    assert capture.calls[0]["source_timezone"] == "Asia/Hong_Kong"
    assert capture.calls[0]["request_run_id"] == "run-actual-1"


def test_capture_uses_real_time_in_production(monkeypatch, tmp_path: Path) -> None:
    """生产（event_class=PRODUCTION）：即使请求带了 test_clock 也必须忽略。"""
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path / "atlas_data"))
    monkeypatch.setenv("ATLAS_UNIFIED_EVENT_CLASS", "PRODUCTION")
    capture = _Capture()
    _install(monkeypatch, tmp_path, capture)
    asyncio.run(_capture_run_user_message(_state(CLOCK)))
    assert capture.calls[0]["occurred_at"] == "2026-10-09T13:00:00+08:00"


def test_capture_uses_real_time_without_clock(monkeypatch, isolated) -> None:
    capture = _Capture()
    _install(monkeypatch, isolated, capture)
    asyncio.run(_capture_run_user_message(_state(None)))
    assert capture.calls[0]["occurred_at"] == "2026-10-09T13:00:00+08:00"


@pytest.mark.parametrize(
    "history",
    [
        [{"id": "old-same", "role": "user", "content": "帮我记一下",
          "created_at": REAL}],
        [{"id": "old-different", "role": "user", "content": "旧的其他内容",
          "created_at": REAL}],
    ],
)
def test_capture_does_not_bind_a_historical_user_message(
    monkeypatch, isolated, history,
) -> None:
    import atlas.engine.session_sync as session_sync

    capture = _Capture()
    _install(monkeypatch, isolated, capture)
    monkeypatch.setattr(session_sync, "read_session_all_messages",
                        lambda home, conv: history)
    state = _state(CLOCK)
    state.preexisting_user_message_ids = {item["id"] for item in history}

    asyncio.run(_capture_run_user_message(state))

    assert capture.calls == []


def test_capture_binds_only_new_same_text_message_after_turn_boundary(
    monkeypatch, isolated,
) -> None:
    import atlas.engine.session_sync as session_sync

    capture = _Capture()
    _install(monkeypatch, isolated, capture)
    monkeypatch.setattr(session_sync, "read_session_all_messages", lambda home, conv: [
        {"id": "old-same", "role": "user", "content": "帮我记一下",
         "created_at": REAL},
        {"id": "new-turn", "role": "user", "content": "帮我记一下",
         "created_at": REAL},
    ])
    state = _state(CLOCK)
    state.preexisting_user_message_ids = {"old-same"}

    asyncio.run(_capture_run_user_message(state))

    assert len(capture.calls) == 1
    assert capture.calls[0]["message_id"] == "new-turn"
    assert capture.calls[0]["request_run_id"] == "run-actual-1"


def test_capture_skips_ambiguous_new_same_text_messages(monkeypatch, isolated) -> None:
    import atlas.engine.session_sync as session_sync

    capture = _Capture()
    _install(monkeypatch, isolated, capture)
    monkeypatch.setattr(session_sync, "read_session_all_messages", lambda home, conv: [
        {"id": "new-turn-1", "role": "user", "content": "帮我记一下",
         "created_at": REAL},
        {"id": "new-turn-2", "role": "user", "content": "帮我记一下",
         "created_at": REAL},
    ])
    state = _state(CLOCK)

    asyncio.run(_capture_run_user_message(state))

    assert capture.calls == []


@pytest.mark.parametrize(
    ("event_class", "expected_clock"),
    [
        ("TEST", "2026-10-05T09:00:00+08:00"),
        ("PRODUCTION", None),
    ],
)
def test_run_start_websocket_event_reports_only_gated_clock(
    monkeypatch, tmp_path: Path, event_class: str, expected_clock: str | None,
) -> None:
    import atlas.api.run_drive as run_drive
    import atlas.config
    import atlas.server as server

    monkeypatch.setenv("ATLAS_UNIFIED_EVENT_CLASS", event_class)
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path / "atlas_data"))
    monkeypatch.setattr(atlas.config, "get_config", lambda: AtlasConfig({
        "user": {"timezone": "Asia/Hong_Kong"},
    }))
    runtime = server.RuntimeManager()
    sent: list[dict] = []

    async def send(conn_id, envelope):
        sent.append(envelope)

    async def send_run(run, envelope, fallback_conn_id):
        sent.append(envelope)

    monkeypatch.setattr(runtime, "send", send)
    monkeypatch.setattr(runtime, "send_run", send_run)

    class _Memory:
        _db = None

        async def save_conversation_metadata(self, *args, **kwargs):
            return None

    class _Hooks:
        async def execute(self, *args, **kwargs):
            return None

    monkeypatch.setattr(server, "memory", _Memory())
    monkeypatch.setattr(server, "orchestrator", object())
    monkeypatch.setattr(server, "model_mgr", SimpleNamespace(current_model="test-model"))
    monkeypatch.setattr(server, "_resolve_active_skill_instructions",
                        lambda skills: asyncio.sleep(0, result=[]))
    monkeypatch.setattr(server, "external_agent_status_cache", {})
    monkeypatch.setattr(server, "external_agent_status", lambda *_: {
        "agents": [{"id": "hermes", "available": True}],
    })
    monkeypatch.setattr(server, "_hook_store", lambda: _Hooks())
    monkeypatch.setattr(server, "_execute_external_agent",
                        lambda *args, **kwargs: asyncio.sleep(0, result=("", [])))
    monkeypatch.setattr(server, "_sum_usage", lambda usage: {})
    monkeypatch.setattr(server, "_run_change_summary", lambda run_id: {})
    monkeypatch.setattr(run_drive, "_spawn_background", lambda task: task.close())

    async def run():
        await server._handle_run_start("clock-ws", {
            "run_id": f"clock-ws-{event_class}",
            "conversation_id": f"clock-conv-{event_class}",
            "content": "测试虚拟时间",
            "executor": "hermes",
            "test_clock": CLOCK,
        }, manager=runtime)
        await runtime.runs[f"clock-ws-{event_class}"].task

    asyncio.run(run())

    started = next(item for item in sent if item.get("event") == "run.started")
    assert started["data"].get("effective_test_clock") == expected_clock


def test_capture_persists_actual_request_run_id_as_source_metadata(tmp_path: Path) -> None:
    from atlas.memory.outbox import OperationalOutbox

    outbox = OperationalOutbox(tmp_path / "capture.sqlite3")
    service = CaptureService(
        config={"memory.unified.event_class": "TEST"},
        outbox=outbox,
        event_class="TEST",
    )
    result = service.capture_user_message(
        "conv-1", "sessiondb-message-42", "原始用户消息",
        "2026-10-05T09:00:00+08:00", source_timezone="Asia/Hong_Kong",
        request_run_id="run-actual-42",
    )

    assert result is not None
    stored = outbox.get(result["source_event_id"])
    assert stored["payload"]["observation"]["metadata"] == {
        "request_run_id": "run-actual-42",
    }
    assert stored["payload"]["observation"]["content"]["text"] == "原始用户消息"
    outbox.close()


def test_observer_source_queue_preserves_source_run_metadata() -> None:
    from atlas.memory.observer import MemoryObserver

    source = MemoryObserver._source_from_capture_row({
        "source_event_id": "atlas:ATLAS_USER_MESSAGE:msg-42:1:UPSERT",
        "payload": {
            "event_class": "TEST",
            "observation": {
                "source_kind": "ATLAS_USER_MESSAGE",
                "content": {"text": "原始用户消息"},
                "metadata": {"request_run_id": "run-actual-42"},
                "occurred_at": "2026-10-05T09:00:00+08:00",
                "source_timezone": "Asia/Hong_Kong",
            },
        },
    })

    assert source["metadata"]["request_run_id"] == "run-actual-42"
    assert source["text"] == "原始用户消息"
    assert source["provenance"]["event_class"] == "TEST"


@pytest.mark.parametrize(
    ("event_class", "expected_day"),
    [("TEST", "2026-10-05"), ("PRODUCTION", None)],
)
def test_observer_batch_uses_only_all_test_source_clock(
    monkeypatch, isolated, event_class: str, expected_day: str | None,
) -> None:
    import atlas.memory.observer as observer_module
    from atlas.memory.observer import MemoryObserver

    config = AtlasConfig({
        "user": {"timezone": "Asia/Hong_Kong"},
        "memory": {"unified": {"enabled": True, "event_class": "TEST"}},
    })
    observer_module._DAILY_SPENT.clear()
    observer = MemoryObserver(None, config, token_counter=lambda text: 1)
    monkeypatch.setattr(observer, "_select_model_id", lambda: "test-model")
    prompts: list[str] = []

    async def complete(model_id, messages, *, max_tokens, system_prompt):
        prompts.append(system_prompt)
        return SimpleNamespace(text='{"observations": []}', usage=None)

    monkeypatch.setattr(observer, "_complete_with_retry", complete)
    batch = asyncio.run(observer.add_messages(
        "observer-clock-session",
        [{
            "source_event_id": f"atlas:ATLAS_USER_MESSAGE:clock-{event_class}:1:UPSERT",
            "source_kind": "ATLAS_USER_MESSAGE",
            "speaker_role": "USER",
            "epistemic_kind": "USER_ASSERTED",
            "text": "周末前完成报告",
            "occurred_at": "2026-10-05T09:00:00+08:00",
            "source_timezone": "Asia/Hong_Kong",
            "provenance": {"event_class": event_class},
        }],
        session_ended=True,
    ))

    assert batch is not None
    assert prompts
    if expected_day:
        assert "2026-10-05T09:00:00+08:00" in prompts[0]
        assert expected_day in observer_module._DAILY_SPENT
    else:
        assert "2026-10-05T09:00:00+08:00" not in prompts[0]
        assert "2026-10-05" not in observer_module._DAILY_SPENT


def _reflection_record(source_events=None, *, valid_from="2099-01-01T00:00:00Z"):
    metadata = {}
    if source_events is not None:
        metadata["source_events"] = source_events
    return {
        "record_ref": "memory:reflection-clock-test",
        "text": "用户安排本周完成报告",
        "valid_time": {"valid_from": valid_from},
        "metadata": metadata,
    }


def _install_clock_only_reflector(monkeypatch, config):
    from atlas.memory.reflector import MemoryReflector

    reflector = MemoryReflector(None, config=config)
    monkeypatch.setattr(reflector, "_select_model_id", lambda: "isolated-clock-test")
    prompts: list[str] = []

    async def complete(model_id, messages):
        prompts.append(messages[0]["content"])
        return SimpleNamespace(text='{"operations": []}', usage=None)

    monkeypatch.setattr(reflector, "_complete_with_retry", complete)
    return reflector, prompts


def test_reflector_uses_latest_durable_test_source_time_not_model_valid_time(
    monkeypatch, isolated,
) -> None:
    config = {"user": {"timezone": "Asia/Hong_Kong"}}
    reflector, prompts = _install_clock_only_reflector(monkeypatch, config)
    record = _reflection_record([
        {
            "source_event_id": "source-early",
            "event_class": "TEST",
            "occurred_at": "2026-10-04T23:00:00Z",
            "source_timezone": "Asia/Hong_Kong",
        },
        {
            "source_event_id": "source-latest",
            "event_class": "TEST",
            "occurred_at": "2026-10-05T09:00:00+08:00",
            "source_timezone": "Asia/Hong_Kong",
        },
    ])

    result = asyncio.run(reflector.reflect("subject", [record], force=True))

    assert result.receipt is not None
    assert "2026-10-05T09:00:00+08:00" in prompts[0]
    assert result.receipt["timestamp"] == "2026-10-05T09:00:00+08:00"
    assert "2099-01-01" not in prompts[0]


@pytest.mark.parametrize(
    "source_events",
    [
        None,
        [
            {"source_event_id": "test", "event_class": "TEST",
             "occurred_at": "2026-10-05T09:00:00+08:00",
             "source_timezone": "Asia/Hong_Kong"},
            {"source_event_id": "prod", "event_class": "PRODUCTION",
             "occurred_at": "2026-10-05T10:00:00+08:00",
             "source_timezone": "Asia/Hong_Kong"},
        ],
        [{"source_event_id": "naive", "event_class": "TEST",
          "occurred_at": "2026-10-05T09:00:00",
          "source_timezone": "Asia/Hong_Kong"}],
        [],
    ],
)
def test_reflector_masks_inherited_test_clock_without_complete_test_provenance(
    monkeypatch, isolated, source_events,
) -> None:
    config = {"user": {"timezone": "Asia/Hong_Kong"}}
    reflector, prompts = _install_clock_only_reflector(monkeypatch, config)
    record = _reflection_record(source_events)

    async def run_reflection():
        with clock_context(CLOCK, config=config, event_class="TEST"):
            result = await reflector.reflect("subject", [record], force=True)
        return result

    result = asyncio.run(run_reflection())

    assert result.receipt is not None
    assert "2026-10-05T09:00:00+08:00" not in prompts[0]
    assert "2099-01-01" not in prompts[0]
    assert "2026-10-05T09:00:00+08:00" not in result.receipt["timestamp"]
