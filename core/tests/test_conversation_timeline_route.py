"""The turn-outline projection is reachable over HTTP (S16 exposure, S22 evidence path)."""

from __future__ import annotations

import pytest

from atlas.api import conversations_router as router_module

pytestmark = pytest.mark.unit


class _FakeMemory:
    def __init__(self, known: set[str]) -> None:
        self.known = known

    async def get_conversation(self, conversation_id: str) -> dict | None:
        return {"id": conversation_id} if conversation_id in self.known else None


class _FakeDB:
    def __init__(self, result):
        self._result = result
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def get_session_timeline(self, session_id, *, limit, after_row_id):
        self.calls.append({"session_id": session_id, "limit": limit, "after_row_id": after_row_id})
        return self._result


def test_timeline_route_is_registered():
    paths = {route.path for route in router_module.router.routes}
    assert "/api/conversations/{conversation_id}/timeline" in paths


@pytest.mark.asyncio
async def test_timeline_unknown_conversation_is_404(monkeypatch, tmp_path):
    services = type("S", (), {"memory": _FakeMemory(set())})()
    monkeypatch.setattr(router_module, "_server", lambda: type("X", (), {"memory": None})())
    with pytest.raises(Exception) as caught:
        await router_module.get_conversation_timeline(services, "missing")
    assert "404" in str(caught.value)


@pytest.mark.asyncio
async def test_timeline_passes_bounds_and_returns_projection(monkeypatch, tmp_path):
    services = type("S", (), {"memory": _FakeMemory({"conv-1"})})()
    fake_db = _FakeDB({"turns": [{"title": "t"}], "pagination": {"returned": 1, "total": 1}})

    class _FakeSessionDB:
        def __init__(self, *, db_path):
            fake_db.db_path = db_path

        def __enter__(self):
            return fake_db

        def __exit__(self, *exc):
            return None

    monkeypatch.setattr(
        "atlas.engine.state.atlas_state.SessionDB", _FakeSessionDB
    )
    monkeypatch.setattr("atlas.config.DATA_ROOT", tmp_path)
    (tmp_path / "engine").mkdir(exist_ok=True)

    result = await router_module.get_conversation_timeline(
        services, "conv-1", limit=50, after_row_id=7,
    )
    assert result["pagination"]["returned"] == 1
    assert fake_db.calls == [{"session_id": "conv-1", "limit": 50, "after_row_id": 7}]
    assert str(fake_db.db_path).endswith("state.db")
