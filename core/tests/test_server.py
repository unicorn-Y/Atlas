"""Tests for Atlas REST API — FastAPI endpoints."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from atlas.server import app


@pytest.fixture
async def client():
    """Async test client using httpx + ASGI transport with lifespan."""
    import os
    old_val = os.environ.get("ATLAS_SCHEDULER_ENABLED")
    os.environ["ATLAS_SCHEDULER_ENABLED"] = "false"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Manually trigger lifespan startup
        from atlas.server import lifespan

        async with lifespan(app):
            yield ac

    # Restore
    if old_val is None:
        os.environ.pop("ATLAS_SCHEDULER_ENABLED", None)
    else:
        os.environ["ATLAS_SCHEDULER_ENABLED"] = old_val


# ---------------------------------------------------------------------------
# Runtime Protocol
# ---------------------------------------------------------------------------

class TestRuntimeProtocol:
    async def test_protocol_version(self, client: AsyncClient) -> None:
        resp = await client.get("/api/runtime/protocol")
        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] == "1.2"


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


# ---------------------------------------------------------------------------
# MCP Server Management
# ---------------------------------------------------------------------------

class TestMCPServerManagement:
    async def test_list_mcp_servers_empty(self, client: AsyncClient) -> None:
        resp = await client.get("/api/mcp/servers")
        assert resp.status_code == 200
        data = resp.json()
        assert "servers" in data
        assert isinstance(data["servers"], list)

    async def test_add_server_invalid_transport(self, client: AsyncClient) -> None:
        """Adding a server with bad config should return 500."""
        resp = await client.post("/api/mcp/servers", json={
            "name": "bad-server",
            "transport": "stdio",
            "command": "nonexistent-binary-xyz",
        })
        assert resp.status_code == 500

    async def test_remove_server_404(self, client: AsyncClient) -> None:
        resp = await client.delete("/api/mcp/servers/nonexistent")
        assert resp.status_code == 404

    async def test_restart_server_404(self, client: AsyncClient) -> None:
        resp = await client.post("/api/mcp/servers/nonexistent/restart")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Knowledge Base
# ---------------------------------------------------------------------------

class TestKnowledge:
    async def test_list_knowledge_empty(self, client: AsyncClient) -> None:
        resp = await client.get("/api/knowledge")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_add_and_search_knowledge(self, client: AsyncClient) -> None:
        # Add entry
        resp = await client.post("/api/knowledge", json={
            "content": "Atlas uses LangGraph for agent orchestration",
            "source": "docs",
            "category": "architecture",
        })
        assert resp.status_code == 200
        entry = resp.json()
        assert "id" in entry
        assert entry["content"] == "Atlas uses LangGraph for agent orchestration"

        # Search
        resp = await client.get("/api/knowledge/search", params={"q": "LangGraph"})
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) >= 1
        assert any("LangGraph" in r["content"] for r in results)

    async def test_delete_knowledge(self, client: AsyncClient) -> None:
        # Create
        resp = await client.post("/api/knowledge", json={
            "content": "Temporary knowledge entry",
        })
        entry_id = resp.json()["id"]

        # Delete
        resp = await client.delete(f"/api/knowledge/{entry_id}")
        assert resp.status_code == 200

        # Delete again -> 404
        resp = await client.delete(f"/api/knowledge/{entry_id}")
        assert resp.status_code == 404

    async def test_search_requires_query(self, client: AsyncClient) -> None:
        resp = await client.get("/api/knowledge/search")
        assert resp.status_code == 422


class TestWebSocketProtocol:
    """Test the Runtime Event Protocol 1.2 WebSocket endpoint.

    Uses starlette's built-in WebSocket test client (via pytest + anyio).
    """

    async def test_run_start_emits_agent_events(self, client: AsyncClient) -> None:
        """A run.start message should produce agent_event envelopes."""
        import asyncio
        import json as _json
        from starlette.testclient import TestClient
        from atlas.server import app as _app, lifespan

        # Use sync TestClient for WebSocket (starlette limitation)
        with TestClient(_app) as tc:
            with tc.websocket_connect("/ws/chat") as ws:
                ws.send_text(_json.dumps({
                    "type": "run.start",
                    "run_id": "test-run-1",
                    "content": "Hello Atlas",
                    "conversation_id": "test-conv-1",
                }))

                # Collect events until run.completed or run.failed
                events: list[dict] = []
                for _ in range(100):  # safety limit
                    raw = ws.receive_text()
                    evt = _json.loads(raw)
                    events.append(evt)
                    if evt.get("event") in ("run.completed", "run.failed"):
                        break

                # All events must be agent_event envelopes
                for evt in events:
                    assert evt["type"] == "agent_event", f"Expected agent_event, got {evt}"
                    assert evt["run_id"] == "test-run-1"
                    assert "event_id" in evt
                    assert "sequence" in evt
                    assert "timestamp" in evt
                    assert "event" in evt
                    assert "data" in evt

                # Sequences must be monotonically increasing
                seqs = [e["sequence"] for e in events]
                assert seqs == sorted(seqs)
                assert len(set(seqs)) == len(seqs)  # all unique

                # First event should be run.started
                assert events[0]["event"] == "run.started"

                # Last event should be run.completed or run.failed
                assert events[-1]["event"] in ("run.completed", "run.failed")
