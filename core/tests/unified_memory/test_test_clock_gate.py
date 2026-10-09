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
from pathlib import Path

import pytest

from atlas.agent.run_phases import RunCallbacks, RunRequest, _RunState, _capture_run_user_message
from atlas.memory.test_clock import isolated_test_environment, resolve_test_clock

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
                           "text": text, "occurred_at": occurred_at})
        return {"ok": True}


def _install(monkeypatch, tmp_path: Path, capture: _Capture) -> None:
    """把捕获点的三个依赖换成探针（DATA_ROOT / 会话读取 / 采集服务）。"""
    import atlas.config
    import atlas.engine.session_sync as session_sync
    import atlas.memory.capture as capture_mod

    monkeypatch.setattr(atlas.config, "DATA_ROOT", tmp_path / "data", raising=False)
    monkeypatch.setattr(session_sync, "latest_session_message",
                        lambda home, conv, role="user": {
                            "id": "msg-1", "content": "帮我记一下", "created_at": REAL})
    monkeypatch.setattr(session_sync, "read_session_messages",
                        lambda home, conv, limit=50: [])
    monkeypatch.setattr(capture_mod, "get_capture_service", lambda: capture)
    sys.modules.setdefault("atlas.memory.capture", capture_mod)


def _state(test_clock: str | None) -> _RunState:
    return _RunState(
        request=RunRequest(message="帮我记一下", conversation_id="conv-1",
                           test_clock=test_clock),
        callbacks=RunCallbacks(), message="帮我记一下")


def test_capture_uses_test_clock_when_gate_opens(monkeypatch, isolated) -> None:
    capture = _Capture()
    _install(monkeypatch, isolated, capture)
    asyncio.run(_capture_run_user_message(_state(CLOCK)))
    assert capture.calls[0]["occurred_at"] == "2026-10-05T09:00:00"


def test_capture_uses_real_time_in_production(monkeypatch, tmp_path: Path) -> None:
    """生产（event_class=PRODUCTION）：即使请求带了 test_clock 也必须忽略。"""
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path / "atlas_data"))
    monkeypatch.setenv("ATLAS_UNIFIED_EVENT_CLASS", "PRODUCTION")
    capture = _Capture()
    _install(monkeypatch, tmp_path, capture)
    asyncio.run(_capture_run_user_message(_state(CLOCK)))
    assert capture.calls[0]["occurred_at"] == REAL


def test_capture_uses_real_time_without_clock(monkeypatch, isolated) -> None:
    capture = _Capture()
    _install(monkeypatch, isolated, capture)
    asyncio.run(_capture_run_user_message(_state(None)))
    assert capture.calls[0]["occurred_at"] == REAL
