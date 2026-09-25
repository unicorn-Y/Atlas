"""Tests for Atlas REST API — FastAPI endpoints."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from atlas.server import app


@pytest.fixture
async def client():
    """Async test client using httpx + ASGI transport with lifespan."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Manually trigger lifespan startup
        from atlas.server import lifespan
        from contextlib import asynccontextmanager

        async with lifespan(app):
            yield ac


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class TestHealth:
    async def test_health(self, client: AsyncClient) -> None:
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class TestModels:
    async def test_list_models(self, client: AsyncClient) -> None:
        resp = await client.get("/api/models")
        assert resp.status_code == 200
        data = resp.json()
        assert "models" in data
        assert "current" in data
        assert len(data["models"]) >= 7

    async def test_select_valid_model(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/models/select",
            json={"model": "gpt-4o"},
        )
        assert resp.status_code == 200
        assert resp.json()["model"] == "gpt-4o"

    async def test_select_invalid_model(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/models/select",
            json={"model": "nonexistent"},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------

class TestConversations:
    async def test_list_empty(self, client: AsyncClient) -> None:
        resp = await client.get("/api/conversations")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_get_messages_404(self, client: AsyncClient) -> None:
        resp = await client.get("/api/conversations/nonexistent/messages")
        assert resp.status_code == 404

    async def test_update_conversation_404(self, client: AsyncClient) -> None:
        resp = await client.put(
            "/api/conversations/nonexistent",
            json={"title": "New Title"},
        )
        assert resp.status_code == 404

    async def test_delete_conversation_404(self, client: AsyncClient) -> None:
        resp = await client.delete("/api/conversations/nonexistent")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

class TestSearch:
    async def test_search_requires_query(self, client: AsyncClient) -> None:
        resp = await client.get("/api/search")
        assert resp.status_code == 422  # missing required 'q' param

    async def test_search_empty_results(self, client: AsyncClient) -> None:
        resp = await client.get("/api/search", params={"q": "xyznonexistent"})
        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------

class TestFacts:
    async def test_list_facts_empty(self, client: AsyncClient) -> None:
        resp = await client.get("/api/facts")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_create_and_list_fact(self, client: AsyncClient) -> None:
        # Create
        resp = await client.post(
            "/api/facts",
            json={"key": "test_key", "value": "test_value", "category": "test"},
        )
        assert resp.status_code == 200
        assert resp.json()["key"] == "test_key"

        # List
        resp = await client.get("/api/facts", params={"category": "test"})
        assert resp.status_code == 200
        facts = resp.json()
        assert len(facts) >= 1
        assert any(f["key"] == "test_key" for f in facts)

    async def test_delete_fact(self, client: AsyncClient) -> None:
        # Create first
        await client.post(
            "/api/facts",
            json={"key": "to_delete", "value": "temp"},
        )
        # Delete
        resp = await client.delete("/api/facts/to_delete")
        assert resp.status_code == 200

        # Delete again should 404
        resp = await client.delete("/api/facts/to_delete")
        assert resp.status_code == 404
