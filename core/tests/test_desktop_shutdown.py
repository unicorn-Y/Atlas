"""Desktop shutdown cancels read-only searches before Uvicorn stops accepting work."""

import asyncio

import httpx
import pytest

from atlas import server
from atlas.api import skills_market_router


@pytest.mark.asyncio
async def test_authorized_shutdown_cancels_searches_before_stop(monkeypatch):
    events = []

    class Market:
        async def cancel_pending_searches(self):
            events.append("searches_cancelled")

    monkeypatch.setenv("ATLAS_SHUTDOWN_TOKEN", "test-owned-backend")
    monkeypatch.setattr(skills_market_router, "get_market", lambda: Market())
    monkeypatch.setattr(server.app.state, "desktop_shutdown_callback",
                        lambda: events.append("server_stopped"), raising=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app),
                                base_url="http://test") as client:
        response = await client.post("/api/runtime/shutdown", headers={
            "X-Atlas-Backend-Shutdown-Token": "test-owned-backend",
        })
        await asyncio.sleep(0)
    assert response.status_code == 202
    assert events == ["searches_cancelled", "server_stopped"]


@pytest.mark.asyncio
async def test_unauthorized_shutdown_does_not_cancel_searches(monkeypatch):
    def unexpected_market():
        pytest.fail("Unauthorized shutdown must not touch ongoing searches")

    monkeypatch.setenv("ATLAS_SHUTDOWN_TOKEN", "test-owned-backend")
    monkeypatch.setattr(skills_market_router, "get_market", unexpected_market)
    monkeypatch.setattr(server.app.state, "desktop_shutdown_callback", lambda: None,
                        raising=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app),
                                base_url="http://test") as client:
        response = await client.post("/api/runtime/shutdown", headers={
            "X-Atlas-Backend-Shutdown-Token": "wrong-token",
        })
    assert response.status_code == 403
