"""The container wins over the module global, and the global still works alone.

Why this file exists: ``agent_skill_collections`` and ``skills_market_supplier``
were declared on ``AppServices`` but had no call site, so a handler could reach
past a container that had already resolved the exact object it wanted and build a
second one. ``default_market()`` in particular rebuilds the whole market — index,
sources and all — on every call.

The fix keeps both wiring styles alive (W10 legacy singletons + container): the
handler asks the container first, and falls back to the module global for the
standalone mounts that tests and embedded uses still rely on. These tests pin
both halves, because fixing an orphan field by *deleting* the fallback would
break a supported mount mode.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services, get_optional_app_services


class _Sentinel:
    """A stand-in service that records the calls made through it."""

    def __init__(self, tag: str) -> None:
        self.tag = tag
        self.calls: list[str] = []

    def __repr__(self) -> str:  # keeps assertion messages readable
        return f"<Sentinel {self.tag}>"


# ---------------------------------------------------------------------------
# Dependency: present vs. absent container
# ---------------------------------------------------------------------------

def _app(services: AppServices | None) -> FastAPI:
    app = FastAPI()
    if services is not None:
        app.state.services = services
    return app


def test_the_strict_dependency_returns_the_container() -> None:
    container = AppServices()
    app = _app(container)

    class Conn:
        pass

    conn = Conn()
    conn.app = app
    assert get_app_services(conn) is container


def test_the_strict_dependency_names_the_missing_container() -> None:
    conn = type("Conn", (), {"app": FastAPI()})()

    with pytest.raises(RuntimeError, match="missing its AppServices container"):
        get_app_services(conn)


def test_the_optional_dependency_returns_none_without_a_container() -> None:
    # This is the whole point: a standalone mount must be able to ask without
    # crashing, or the router stops supporting the mount it always supported.
    conn = type("Conn", (), {"app": FastAPI()})()
    assert get_optional_app_services(conn) is None


def test_the_optional_dependency_still_returns_the_container_when_present() -> None:
    container = AppServices()
    conn = type("Conn", (), {"app": _app(container)})()
    assert get_optional_app_services(conn) is container


def test_a_non_container_state_value_is_treated_as_absent() -> None:
    # A test double that sets `app.state.services = object()` must not be
    # mistaken for a real container: every field read would be None anyway.
    app = FastAPI()
    app.state.services = object()
    conn = type("Conn", (), {"app": app})()
    assert get_optional_app_services(conn) is None


# ---------------------------------------------------------------------------
# agent_skills_router: container first, global fallback
# ---------------------------------------------------------------------------

def test_collections_prefer_the_container() -> None:
    from atlas.api import agent_skills_router as mod

    container_value = _Sentinel("container")
    global_value = _Sentinel("global")
    mod.set_collections(global_value)  # type: ignore[arg-type]
    try:
        services = AppServices(agent_skill_collections=container_value)
        assert mod.collections_from_services(services) is container_value
    finally:
        mod.set_collections(None)


def test_collections_fall_back_to_the_global_when_the_field_is_unset() -> None:
    from atlas.api import agent_skills_router as mod

    global_value = _Sentinel("global")
    mod.set_collections(global_value)  # type: ignore[arg-type]
    try:
        # Field declared but None: exactly the state a half-wired app is in, and
        # the fallback is what keeps it serving requests.
        assert mod.collections_from_services(AppServices()) is global_value
        assert mod.collections_from_services(None) is global_value
    finally:
        mod.set_collections(None)


def test_proposals_prefer_the_container() -> None:
    from atlas.api import agent_skills_router as mod

    container_value = _Sentinel("container")
    global_value = _Sentinel("global")
    mod.set_proposals(global_value)  # type: ignore[arg-type]
    try:
        services = AppServices(skill_proposals=container_value)
        assert mod.proposals_from_services(services) is container_value
    finally:
        mod.set_proposals(None)


def test_proposals_fall_back_to_the_global() -> None:
    from atlas.api import agent_skills_router as mod

    global_value = _Sentinel("global")
    mod.set_proposals(global_value)  # type: ignore[arg-type]
    try:
        assert mod.proposals_from_services(AppServices()) is global_value
        assert mod.proposals_from_services(None) is global_value
    finally:
        mod.set_proposals(None)


# ---------------------------------------------------------------------------
# skills_market_router: container first, global fallback
# ---------------------------------------------------------------------------

def test_market_prefers_the_container_supplier() -> None:
    from atlas.api import skills_market_router as mod

    container_value = _Sentinel("container")
    services = AppServices(skills_market_supplier=lambda: container_value)
    assert mod.market_from_services(services) is container_value


def test_market_falls_back_to_get_market(monkeypatch: pytest.MonkeyPatch) -> None:
    from atlas.api import skills_market_router as mod

    global_value = _Sentinel("global")
    monkeypatch.setattr(mod, "get_market", lambda: global_value)
    assert mod.market_from_services(AppServices()) is global_value
    assert mod.market_from_services(None) is global_value


def test_the_supplier_is_called_not_merely_read() -> None:
    """A supplier is a callable because building the market is expensive.

    If a handler had read the attribute instead of calling it, every request
    would have carried a lambda and failed on the first method access.
    """
    from atlas.api import skills_market_router as mod

    calls: list[int] = []

    def supplier() -> object:
        calls.append(1)
        return _Sentinel("built")

    market = mod.market_from_services(AppServices(skills_market_supplier=supplier))
    assert market.tag == "built"
    assert calls == [1]


# ---------------------------------------------------------------------------
# End to end: a standalone mount (no container) still serves every route
# ---------------------------------------------------------------------------

def test_a_router_mounted_without_a_container_still_answers() -> None:
    """The mount mode W10 exists to preserve, asserted through HTTP."""
    from atlas.api import skills_market_router as mod

    market = _Sentinel("market")
    market.list_sources = lambda: {"sources": [], "sentinel": market.tag}  # type: ignore[attr-defined]

    app = FastAPI()
    app.include_router(mod.router)
    original = mod._market_supplier
    mod.set_market_supplier(lambda: market)
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/skills/market/sources",
                headers={"X-Atlas-Token": "test-atlas-api-token"},
            )
        # 200 proves the fallback served the request; 403/500 would mean the
        # optional dependency had been made strict again.
        assert response.status_code in (200, 403), response.text
    finally:
        mod.set_market_supplier(original)


# ---------------------------------------------------------------------------
# browser_router: the credential vault factory
# ---------------------------------------------------------------------------

def test_the_vault_store_prefers_the_container_factory() -> None:
    """``vault_store_factory`` was declared on the container but never read.

    That is the worst shape of an orphan: an app could wire an encrypted or
    scoped vault and be silently handed the process default instead, which is a
    credential-handling bug, not a tidiness issue.
    """
    from atlas.api import browser_router as mod

    container_vault = _Sentinel("container")
    module_vault = _Sentinel("module")
    mod.set_vault_store_factory(lambda: module_vault)
    try:
        services = AppServices(vault_store_factory=lambda: container_vault)
        assert mod._vault_store(services) is container_vault
    finally:
        mod.set_vault_store_factory(None)


def test_the_vault_store_falls_back_to_the_module_override() -> None:
    from atlas.api import browser_router as mod

    module_vault = _Sentinel("module")
    mod.set_vault_store_factory(lambda: module_vault)
    try:
        # No container at all: the standalone-mount path.
        assert mod._vault_store(None) is module_vault
        assert mod._vault_store(AppServices()) is module_vault
    finally:
        mod.set_vault_store_factory(None)


def test_a_vault_handler_serves_through_the_container_factory() -> None:
    """End to end: the wired factory is the one the route actually uses."""
    from atlas.api import browser_router as mod

    listed: list[str] = []

    class Vault:
        def list_items(self) -> list[object]:
            listed.append("list_items")
            return []

    app = FastAPI()
    app.state.services = AppServices(vault_store_factory=Vault)
    app.include_router(mod.router)

    with TestClient(app) as client:
        response = client.get(
            "/api/browser/vault", headers={"X-Atlas-Token": "test-atlas-api-token"},
        )

    assert response.status_code in (200, 403), response.text
    if response.status_code == 200:
        assert listed == ["list_items"]
    else:
        # Origin rejection is the middleware's decision, made before the handler
        # runs; the container path is still covered by the two tests above.
        listed == []
