"""Users must be able to get their own conversation data out over HTTP.

``export_session`` / ``import_sessions`` already round-trip a conversation, but
only a share-to-HTML route was exposed, so the machine-readable path existed in
code and nowhere a client could reach. These tests pin the route contract:
registered, 404 on an unknown conversation, and a document that carries the
export format marker plus the caller's flags through to the store call.
"""

from __future__ import annotations

from typing import Any

import pytest

from atlas.api import conversations_router as router_module

pytestmark = pytest.mark.unit


class _FakeMemory:
    def __init__(self, known: set[str]) -> None:
        self.known = known

    async def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        return {"id": conversation_id} if conversation_id in self.known else None


class _FakeDB:
    last_call: dict[str, Any] = {}

    def __init__(self, result: dict[str, Any] | None) -> None:
        self._result = result

    def __enter__(self) -> "_FakeDB":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def export_session(self, conversation_id: str, *, include_compacted: bool,
                       include_inactive: bool) -> dict[str, Any] | None:
        type(self).last_call = {
            "conversation_id": conversation_id,
            "include_compacted": include_compacted,
            "include_inactive": include_inactive,
        }
        return self._result


def _route_paths() -> set[str]:
    return {route.path for route in router_module.router.routes}


def test_export_route_is_registered():
    assert "/api/conversations/{conversation_id}/export" in _route_paths()


@pytest.mark.asyncio
async def test_unknown_conversation_is_404(monkeypatch):
    services = type("S", (), {"memory": _FakeMemory(set())})()
    with pytest.raises(Exception) as caught:
        await router_module.export_conversation(services, "missing")
    assert "404" in str(caught.value)


@pytest.mark.asyncio
async def test_export_returns_document_with_format_marker(monkeypatch, tmp_path):
    services = type("S", (), {"memory": _FakeMemory({"conv-1"})})()
    captured = {}

    def _fake_open_db(_home):
        return _FakeDB({"id": "conv-1", "messages": [{"role": "user", "content": "hi"}]})

    monkeypatch.setattr("atlas.engine.session_sync._open_db", _fake_open_db)
    # The route only guards on state.db existing; point DATA_ROOT at a stub tree.
    monkeypatch.setattr("atlas.config.DATA_ROOT", tmp_path)
    (tmp_path / "engine").mkdir()
    (tmp_path / "engine" / "state.db").write_bytes(b"")

    document = await router_module.export_conversation(
        services, "conv-1", include_compacted=False, include_inactive=False,
    )
    captured = dict(_FakeDB.last_call)

    assert document["export_format"] == "atlas.session.v1"
    assert document["conversation_id"] == "conv-1"
    assert document["messages"] == [{"role": "user", "content": "hi"}]
    assert captured == {
        "conversation_id": "conv-1",
        "include_compacted": False,
        "include_inactive": False,
    }


@pytest.mark.asyncio
async def test_flags_are_forwarded_not_normalised(monkeypatch, tmp_path):
    services = type("S", (), {"memory": _FakeMemory({"conv-2"})})()

    monkeypatch.setattr(
        "atlas.engine.session_sync._open_db",
        lambda _home: _FakeDB({"id": "conv-2", "messages": []}),
    )
    monkeypatch.setattr("atlas.config.DATA_ROOT", tmp_path)
    (tmp_path / "engine").mkdir()
    (tmp_path / "engine" / "state.db").write_bytes(b"")

    await router_module.export_conversation(
        services, "conv-2", include_compacted=True, include_inactive=True,
    )

    assert _FakeDB.last_call["include_compacted"] is True
    assert _FakeDB.last_call["include_inactive"] is True
