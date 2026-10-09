"""F3-B：观察者「会话结束」控制面单元测试。

覆盖 ``POST /api/unified-memory/session/close`` 与
``observer_drain.request_observer_session_end``：只复用既有
``end_session``/``end_active_session`` + 既有 drain 调度踢点，不新建调度器、
不直接写库。全部为单元测试（不拉起真服务），真链路验证在 S29 实跑与
``test_reminder_automation`` 的集成用例里。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atlas.api.unified_memory_router import router as unified_memory_router
from atlas.memory import observer_drain as od


class _StubDrain:
    """记录被调用的会话结束动作；不碰 outbox、不碰模型。"""

    def __init__(self, active: str | None = "chat-1") -> None:
        self.active_session = active
        self.ended: list[str] = []
        self.end_active_calls = 0

    def end_session(self, session_id: str) -> None:
        self.ended.append(str(session_id))

    def end_active_session(self) -> None:
        self.end_active_calls += 1
        if self.active_session:
            self.ended.append(self.active_session)


@pytest.fixture(autouse=True)
def _isolated_registry():
    od.register_observer_drain(None)
    yield
    od.register_observer_drain(None)


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(unified_memory_router)
    return TestClient(app)


def test_explicit_session_id_ends_that_session_and_kicks_drain() -> None:
    drain = _StubDrain(active="chat-other")
    kicks: list[int] = []
    od.register_observer_drain(drain, lambda: kicks.append(1))

    result = od.request_observer_session_end("chat-42")

    assert result == {"status": "ok", "session_ended": "chat-42"}
    assert drain.ended == ["chat-42"]
    assert drain.end_active_calls == 0
    assert kicks == [1]


def test_missing_session_id_falls_back_to_active_session() -> None:
    drain = _StubDrain(active="chat-active")
    kicks: list[int] = []
    od.register_observer_drain(drain, lambda: kicks.append(1))

    result = od.request_observer_session_end()

    assert result == {"status": "ok", "session_ended": "chat-active"}
    assert drain.end_active_calls == 1
    assert drain.ended == ["chat-active"]
    assert kicks == [1]


def test_no_active_session_reports_none_and_never_kicks() -> None:
    drain = _StubDrain(active=None)
    kicks: list[int] = []
    od.register_observer_drain(drain, lambda: kicks.append(1))

    result = od.request_observer_session_end()

    assert result == {"status": "no_active_session", "session_ended": None}
    assert kicks == []


def test_unconfigured_observer_reports_unavailable() -> None:
    assert od.request_observer_session_end("chat-1") == {
        "status": "unavailable", "session_ended": None}


def test_kick_failure_never_propagates() -> None:
    drain = _StubDrain(active="chat-1")

    def _boom() -> None:
        raise RuntimeError("scheduler unavailable")

    od.register_observer_drain(drain, _boom)

    result = od.request_observer_session_end()

    assert result["status"] == "ok"
    assert result["session_ended"] == "chat-1"
    assert drain.ended == ["chat-1"]


def test_endpoint_returns_200_with_ended_session() -> None:
    drain = _StubDrain(active="chat-http")
    kicks: list[int] = []
    od.register_observer_drain(drain, lambda: kicks.append(1))

    response = _client().post("/api/unified-memory/session/close",
                              json={"session_id": "chat-http"})

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "ok", "session_ended": "chat-http"}
    assert drain.ended == ["chat-http"]
    assert kicks == [1]


def test_endpoint_accepts_empty_body() -> None:
    drain = _StubDrain(active="chat-empty")
    od.register_observer_drain(drain, lambda: None)

    response = _client().post("/api/unified-memory/session/close")

    assert response.status_code == 200, response.text
    assert response.json()["session_ended"] == "chat-empty"


def test_endpoint_reports_503_when_observer_not_wired() -> None:
    response = _client().post("/api/unified-memory/session/close", json={})

    assert response.status_code == 503, response.text
    assert response.json()["detail"]["error"] == "OBSERVER_NOT_CONFIGURED"


def test_endpoint_rejects_non_object_body() -> None:
    od.register_observer_drain(_StubDrain(), lambda: None)

    response = _client().post("/api/unified-memory/session/close", json=["nope"])

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["error"] == "INVALID_BODY"
