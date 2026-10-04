"""H8 S1/S4 tests — startup component registry + /api/health ``components``.

Taskbook §10 ("health ``components`` 字段测试"): every ``components`` value is
one of ``starting | ready | failed``, and ``status == "ok"`` holds exactly
when all registered components are ready. Written against the real app
factory (``create_app``) under a real lifespan, the way the server exposes
the contract (httpx's ASGITransport alone never runs lifespans).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from atlas.api.app_services import AppServices
from atlas.api.application import create_app
from atlas.api.startup_components import COMPONENT_NAMES, StartupComponents

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# S1 — StartupComponents
# ---------------------------------------------------------------------------


async def test_mark_and_snapshot_track_component_states() -> None:
    startup = StartupComponents()
    assert startup.snapshot() == {}
    assert startup.state("mcp") is None

    startup.mark("mcp", "starting")
    startup.mark("dbos", "ready")
    startup.mark("plugins", "failed")

    assert startup.snapshot() == {"mcp": "starting", "dbos": "ready", "plugins": "failed"}
    with pytest.raises(ValueError):
        startup.mark("mcp", "bogus")  # type: ignore[arg-type]


async def test_wait_ready_parks_while_starting_then_resolves() -> None:
    startup = StartupComponents()
    startup.mark("mcp", "starting")

    pending = asyncio.ensure_future(startup.wait_ready("mcp", timeout=5.0))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert not pending.done()  # "starting" keeps the bounded wait parked
    startup.mark("mcp", "ready")
    assert await pending is True


async def test_wait_ready_false_on_failed_and_timeout() -> None:
    startup = StartupComponents()
    startup.mark("mcp", "failed")
    assert await startup.wait_ready("mcp", timeout=5.0) is False  # settled, not ready
    assert await startup.wait_ready("never-registered", timeout=0.05) is False


async def test_wait_all_ready_requires_every_component_ready() -> None:
    startup = StartupComponents()
    for name in COMPONENT_NAMES:
        startup.mark(name, "starting")
    waiter = asyncio.ensure_future(startup.wait_all_ready(timeout=5.0))
    await asyncio.sleep(0)
    for name in COMPONENT_NAMES[:-1]:
        startup.mark(name, "ready")
    await asyncio.sleep(0)
    assert not waiter.done()  # one component short
    startup.mark(COMPONENT_NAMES[-1], "ready")
    assert await waiter is True

    startup.mark("mcp", "failed")
    assert await startup.wait_all_ready(timeout=5.0) is False


# ---------------------------------------------------------------------------
# S4 — /api/health components contract (real app factory + real lifespan)
# ---------------------------------------------------------------------------


def _health_app(setup: Any) -> FastAPI:
    """Build the real app under a lifespan registering the given states."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> Any:
        startup = app.state.services.startup
        assert startup is not None, "create_app must mount StartupComponents"
        setup(startup)
        yield

    return create_app(lifespan=lifespan, services=AppServices())


async def _health_under_lifespan(app: FastAPI) -> dict[str, Any]:
    """GET /api/health once, with the app's lifespan actually running.

    (httpx's ASGITransport alone never runs lifespan events, so tests enter
    ``app.router.lifespan_context`` — the same object uvicorn drives.)
    """
    lifespan = app.router.lifespan_context

    async with lifespan(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
        ) as client:
            return (await client.get("/api/health")).json()


@pytest.mark.unit
async def test_health_reports_component_states_and_flips_to_ok() -> None:
    settle_gate = asyncio.Event()

    def setup(startup: StartupComponents) -> None:
        startup.mark("dbos", "starting")
        startup.mark("mcp", "starting")
        startup.mark("channels", "starting")

        async def settle_when_asked() -> None:
            # The "deferred startup" completes only once the test has seen
            # the starting state — deterministic, no timer races.
            await settle_gate.wait()
            startup.mark("dbos", "ready")
            startup.mark("mcp", "ready")
            startup.mark("channels", "ready")

        asyncio.get_running_loop().create_task(settle_when_asked())

    app = _health_app(setup)
    lifespan = app.router.lifespan_context
    async with lifespan(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
        ) as client:
            async def health() -> dict[str, Any]:
                return (await client.get("/api/health")).json()

            body = await health()
            assert body["status"] == "starting"
            assert set(body["components"]) == {"dbos", "mcp", "channels"}
            assert all(
                state in {"starting", "ready", "failed"}
                for state in body["components"].values()
            )

            settle_gate.set()
            async with asyncio.timeout(5):
                while (await health())["status"] != "ok":
                    await asyncio.sleep(0.02)

            final = await health()
            assert final["status"] == "ok"
            assert final["components"] == {
                "dbos": "ready", "mcp": "ready", "channels": "ready",
            }
            assert "version" in final


async def test_health_stays_starting_while_any_component_failed() -> None:
    def setup(startup: StartupComponents) -> None:
        startup.mark("dbos", "ready")
        startup.mark("mcp", "failed")

    body = await _health_under_lifespan(_health_app(setup))
    assert body["status"] == "starting"
    assert body["components"] == {"dbos": "ready", "mcp": "failed"}


async def test_health_without_components_stays_ok() -> None:
    # An app mounted without a registering lifespan shows no components:
    # the historical {"status": "ok"} contract is preserved.
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> Any:
        yield

    services = AppServices()
    app = create_app(lifespan=lifespan, services=services)
    assert services.startup is not None  # mounted by create_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        body = (await client.get("/api/health")).json()
    assert body == {"status": "ok", "version": "0.1.0", "components": {}}
