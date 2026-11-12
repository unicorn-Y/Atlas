"""The context introspection provider.

Two things worth pinning: that the provider is registered (so the manifest the UI
reads actually lists it), and that a bare container — no services, no config —
answers instead of raising. Introspection runs over a half-built app in tests and
in the CLI, so "no config" has to be an answer.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

import httpx
import pytest

from atlas.api.app_services import AppServices
from atlas.api.application import create_app
from atlas.introspect import registry
from atlas.introspect.providers import context as provider


@asynccontextmanager
async def _noop_lifespan():
    yield


async def _call(method: str, payload: dict | None = None) -> dict:
    return (await registry.query("context", method, payload or {}))["result"]


def test_provider_is_registered():
    ids = [p.id for p in registry.providers()]
    assert "context" in ids
    assert ids.count("context") == 1


def test_manifest_is_serialisable_and_lists_both_methods():
    manifest = registry.describe("context")
    assert manifest["id"] == "context"
    assert [m["name"] for m in manifest["methods"]] == ["windows", "pressure"]
    json.dumps(manifest)


def test_unknown_method_is_a_query_error():
    with pytest.raises(registry.QueryError):
        registry.get_provider("context").method("nope")


@pytest.mark.asyncio
async def test_windows_answers_without_a_config():
    result = await _call("windows")
    assert result["default_window"] > 0
    assert result["levels"] == ["idle", "roomy", "filling", "tight", "critical"]
    assert isinstance(result["models"], list)


@pytest.mark.asyncio
async def test_windows_marks_a_model_without_a_declared_window():
    class Models:
        custom = [{"id": "m1"}, {"id": "m2", "context_window": 200_000}]

    class Config:
        models = Models()

    class Services:
        config = Config()

    payload = (await registry.query("context", "windows", {}, services=Services()))["result"]
    by_id = {row["id"]: row for row in payload["models"]}
    assert by_id["m1"]["known"] is False
    assert by_id["m2"]["known"] is True
    assert by_id["m2"]["thresholds"]["blocking"] > 0


@pytest.mark.asyncio
async def test_pressure_from_an_explicit_count():
    result = await _call("pressure", {"used_tokens": 150_000, "model_window": 200_000})
    assert result["pressure"] == "filling"
    assert result["used_percent"] == 75
    assert result["thresholds"]["warning"] > 0


@pytest.mark.asyncio
async def test_pressure_with_no_input_is_unknown_not_an_error():
    result = await _call("pressure")
    assert result["pressure"] == "unknown"
    assert "无法判断" in result["sentence"]


@pytest.mark.asyncio
async def test_pressure_for_a_session_with_no_row_is_unknown():
    result = await _call("pressure", {"session_id": "does-not-exist"})
    assert result["session_id"] == "does-not-exist"
    assert result["pressure"] == "unknown"


@pytest.mark.asyncio
async def test_pressure_reads_a_session_row_when_the_state_can_find_one():
    class State:
        def get_session_usage(self, session_id):
            return {"context_tokens": 190_000, "context_window": 200_000}

    class Services:
        state = State()

    result = (
        await registry.query("context", "pressure", {"session_id": "s1"}, services=Services())
    )["result"]
    assert result["pressure"] == "critical"
    assert result["used_tokens"] == 190_000


@pytest.mark.asyncio
async def test_a_failing_state_read_is_reported_not_raised():
    class State:
        def get_session_usage(self, session_id):
            raise RuntimeError("db gone")

    class Services:
        state = State()

    result = (
        await registry.query("context", "pressure", {"session_id": "s1"}, services=Services())
    )["result"]
    assert "db gone" in result["error"]


@pytest.mark.asyncio
async def test_http_round_trip():
    app = create_app(lifespan=_noop_lifespan, services=AppServices())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://atlas"
    ) as client:
        listing = await client.get("/api/introspect/providers")
        assert listing.status_code == 200
        assert "context" in {p["id"] for p in listing.json()["providers"]}

        described = await client.get("/api/introspect/providers/context")
        assert described.status_code == 200

        answer = await client.post(
            "/api/introspect/query",
            json={"provider": "context", "method": "pressure",
                  "input": {"used_tokens": 199_000, "model_window": 200_000}},
        )
        assert answer.status_code == 200
        assert answer.json()["result"]["pressure"] == "critical"


@pytest.mark.asyncio
async def test_provider_runs_read_only():
    """Calling either method must not mutate the config it reads."""
    before = json.dumps(provider._models(registry.Context()), sort_keys=True, default=str)
    await _call("windows")
    await _call("pressure", {"used_tokens": 10, "model_window": 200_000})
    after = json.dumps(provider._models(registry.Context()), sort_keys=True, default=str)
    assert before == after
