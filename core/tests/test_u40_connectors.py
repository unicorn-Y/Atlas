from __future__ import annotations

import asyncio

from atlas.api import cloud_documents_router, integrations_router


def test_connector_manifest_and_local_google_adapter(monkeypatch):
    from atlas import secrets_store

    monkeypatch.setattr(cloud_documents_router, "google_status", lambda: _awaitable({
        "configured": True, "connected": True, "account": "user@example.test",
    }))
    monkeypatch.setattr(secrets_store, "resolve_secret", lambda name: "test-linear-secret" if name == "ATLAS_LINEAR_API_KEY" else None)
    manifest = asyncio.run(integrations_router.list_connectors())
    google = next(item for item in manifest["connectors"] if item["id"] == "google-workspace")
    linear = next(item for item in manifest["connectors"] if item["id"] == "linear")
    assert google["connected"] and google["account"] == "user@example.test"
    assert linear["configured"] and linear["authorization"] == "secret-handle"

    async def fake_google_items(source: str, q: str):
        return {"source": source, "items": [{"id": "file-1", "name": q}]}

    monkeypatch.setattr(cloud_documents_router, "google_items", fake_google_items)
    result = asyncio.run(integrations_router.google_connector_search("drive", "design notes"))
    assert result == {"source": "drive", "items": [{"id": "file-1", "name": "design notes"}]}


async def _awaitable(value):
    return value
