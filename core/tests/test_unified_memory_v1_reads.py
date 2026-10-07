from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import structlog

from atlas.memory import MemoryStore
from atlas.memory.unified_client import ServiceUnavailable, UnifiedMemoryClient
from atlas.memory.unified_facade import UnifiedMemoryFacade


class _Config:
    def __init__(self, values: dict[str, Any]) -> None:
        self.values = values

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)


class _Lifecycle:
    def __init__(self, state: str) -> None:
        self.state = state
        self.last_error = "startup probe failed"

    def note_http_ready(self) -> None:
        self.state = "ready"
        self.last_error = None


@pytest.mark.asyncio
async def test_enabled_memory_reads_delegate_to_http_and_exclude_local_fact(
    tmp_path: Path,
) -> None:
    paths: list[tuple[str, str]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        paths.append((request.method, request.url.path))
        if request.url.path == "/v1/unified/records":
            if request.url.params.get("cursor") == "page-2":
                return httpx.Response(200, json={
                    "items": [{
                        "record_ref": "fact:remote-key-after-eight",
                        "record_revision": 2, "facet": "personal",
                        "content": {"key": "remote-key-after-eight",
                                    "value": "remote value"},
                    }],
                    "next_cursor": None,
                })
            return httpx.Response(200, json={
                "items": [{
                    "record_ref": f"fact:remote-{i}", "record_revision": 1,
                    "facet": "personal",
                    "content": {"key": f"remote-{i}", "value": f"value-{i}"},
                } for i in range(8)],
                "next_cursor": "page-2",
            })
        if request.url.path == "/v1/unified/recall":
            return httpx.Response(200, json={
                "read_id": "remote-read-1", "authority_revision": 1,
                "context_hash": "sha256:test", "context_items": [],
                "source_snippets": [], "conflicts": [], "missing_evidence": [],
            })
        return httpx.Response(404, json={"error": "not found"})

    client = UnifiedMemoryClient(
        "http://127.0.0.1:8099", transport=httpx.MockTransport(respond))
    facade = UnifiedMemoryFacade(_Config({"memory.unified.enabled": True}), client)
    store = MemoryStore(db_path=tmp_path / "legacy.sqlite3")
    await store.init()
    try:
        await store.set_fact(
            "B_LOCAL_ONLY_SENTINEL", "never inject this legacy-only value")
        store._unified = facade

        assert await store.get_fact("B_LOCAL_ONLY_SENTINEL") is None
        assert await store.get_fact("missing-exact-key") is None
        assert await store.get_fact("remote-key-after-eight") == "remote value"
        facts = await store.list_facts()
        assert len(facts) == 9
        assert "B_LOCAL_ONLY_SENTINEL" not in {item["key"] for item in facts}
        assert await store.get_active_context("B_LOCAL_ONLY_SENTINEL") == []
        context = await store.get_agent_context_with_trace("B_LOCAL_ONLY_SENTINEL")
        assert context["memories"] == []
        assert "B_LOCAL_ONLY_SENTINEL" not in json.dumps(context)
        assert "never inject this legacy-only value" not in json.dumps(context)

        assert ("GET", "/v1/unified/records") in paths
        assert ("POST", "/v1/unified/recall") in paths
    finally:
        await client.aclose()
        await store.close()


@pytest.mark.asyncio
async def test_facade_transport_failure_is_reported_as_service_unavailable() -> None:
    def disconnected(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("test service down")

    client = UnifiedMemoryClient(
        "http://127.0.0.1:8099", transport=httpx.MockTransport(disconnected))
    facade = UnifiedMemoryFacade(_Config({"memory.unified.enabled": True}), client)
    try:
        with pytest.raises(ServiceUnavailable, match="unreachable"):
            await facade.recall_for_conversation("hello")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_remote_fact_advisories_paginate_without_opening_legacy_fact_store(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, str | None]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        status = request.url.params.get("status")
        cursor = request.url.params.get("cursor")
        calls.append((str(status), cursor))
        if status == "CONFLICTED":
            if cursor == "conflicts-2":
                return httpx.Response(200, json={"items": [{
                    "record_ref": "conflict:second", "content": {
                        "key": "second", "candidate_value": "new",
                        "current_value": "old",
                    },
                }], "next_cursor": None})
            return httpx.Response(200, json={"items": [{
                "record_ref": "conflict:first", "content": {
                    "key": "first", "candidate_value": "new",
                    "current_value": "old",
                },
            }], "next_cursor": "conflicts-2"})
        if status == "ACTIVE":
            return httpx.Response(200, json={"items": [{
                "record_ref": "fact:remote", "updated_at": "2026-10-07T12:00:00+00:00",
                "content": {"key": "remote", "value": "remote value"},
            }], "next_cursor": None})
        return httpx.Response(400, json={"error": f"unexpected status {status}"})

    client = UnifiedMemoryClient(
        "http://127.0.0.1:8099", transport=httpx.MockTransport(respond))
    store = MemoryStore(db_path=tmp_path / "legacy.sqlite3")
    store._unified = UnifiedMemoryFacade(
        _Config({"memory.unified.enabled": True}), client)
    try:
        conflicts = await store.list_memory_conflicts()
        assert [item["record_ref"] for item in conflicts] == [
            "conflict:first", "conflict:second"]
        health = await store.get_memory_health()
        assert health["memory_count"] == 1
        assert calls.count(("CONFLICTED", None)) == 1
        assert ("CONFLICTED", "conflicts-2") in calls
        assert ("ACTIVE", None) in calls
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_facade_recovers_after_startup_failure_when_service_appears() -> None:
    def recovered(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/unified/status"
        return httpx.Response(200, json={"status": "ok", "service": "MemoryOS"})

    client = UnifiedMemoryClient(
        "http://127.0.0.1:8099", transport=httpx.MockTransport(recovered))
    facade = UnifiedMemoryFacade(_Config({"memory.unified.enabled": True}), client)
    lifecycle = _Lifecycle("offline")
    facade.bind_service_lifecycle(lifecycle)
    try:
        status = await facade.status()
        assert status == {"status": "ok", "service": "MemoryOS"}
        assert lifecycle.state == "ready"
        assert lifecycle.last_error is None
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_recall_timeout_consumes_config_and_does_not_block_event_loop() -> None:
    started = asyncio.Event()

    async def slow_handler(request: httpx.Request) -> httpx.Response:
        started.set()
        await asyncio.sleep(1)
        return httpx.Response(200, json={"context_items": []})

    client = UnifiedMemoryClient(
        "http://127.0.0.1:8099",
        transport=httpx.MockTransport(slow_handler), timeout=2.0)
    facade = UnifiedMemoryFacade(_Config({
        "memory.unified.enabled": True,
        "memory.v1.recall_timeout_seconds": 0.05,
    }), client)
    try:
        with pytest.raises(ServiceUnavailable, match="exceeded 0.05s"):
            await facade.recall_for_conversation("bounded query")
        assert started.is_set()
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_run_phase_context_uses_remote_ref_and_degrades_without_local_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from atlas.agent import run_phases
    from atlas.engine import session_sync
    from atlas.memory.unified_client import ServiceUnavailable

    monkeypatch.setattr(session_sync, "read_session_messages", lambda *_a, **_k: [])
    monkeypatch.setattr(
        run_phases._agent, "get_config",
        lambda: SimpleNamespace(max_context_messages=8, get=lambda *_a: True),
    )

    class _Memory:
        def __init__(self, offline: bool) -> None:
            self.offline = offline
            self.extract_called = False
            self.recall_session_id: str | None = None

        def _unified_reads_enabled(self) -> bool:
            return True

        async def extract_memories(self, *_args: Any) -> None:
            self.extract_called = True
            raise AssertionError("unified mode must not read/extract local facts")

        async def _unified_recall_context(
            self, _query: str, *, limit: int, runtime_session_id: str | None = None,
        ) -> dict[str, Any]:
            self.recall_session_id = runtime_session_id
            if self.offline:
                raise ServiceUnavailable("test service offline", route="/v1/unified/recall")
            return {
                "memories": [{"key": "remote", "record_ref": "record:remote-1",
                              "content": {"text": "remote memory"}}],
                "knowledge_trace": {"read_id": "read-1", "authority_revision": 7},
            }

    for offline in (False, True):
        memory = _Memory(offline)
        agent = SimpleNamespace(_memory=memory)
        request = run_phases.RunRequest(
            message="按我之前的个人偏好回答。", conversation_id=f"b-{offline}")
        state = run_phases._RunState(
            request=request, callbacks=run_phases.RunCallbacks(),
            message=request.message, runtime=SimpleNamespace(maintenance_context={}),
        )
        with structlog.testing.capture_logs() as captured:
            async for _event in run_phases._phase_context(agent, state):
                pass
        assert state.abort is False
        assert memory.extract_called is False
        assert memory.recall_session_id == request.conversation_id
        if offline:
            assert state.context["memories"] == []
        else:
            assert state.context["memories"][0]["record_ref"] == "record:remote-1"
            recall_logs = [
                item for item in captured
                if item.get("event") == "agent.memory.unified_read"
            ]
            assert recall_logs and recall_logs[0]["record_refs"] == ["record:remote-1"]


@pytest.mark.asyncio
async def test_unified_http_client_bypasses_proxy_only_for_loopback() -> None:
    loopback = UnifiedMemoryClient("http://127.0.0.1:8099")
    remote = UnifiedMemoryClient("https://memory.example.invalid")
    try:
        assert loopback._http()._trust_env is False
        assert remote._http()._trust_env is True
    finally:
        await loopback.aclose()
        await remote.aclose()


@pytest.mark.asyncio
async def test_capture_flush_callback_only_schedules_observer_work() -> None:
    from atlas.memory.capture import capture_flush_loop

    flush_done = asyncio.Event()
    callback_called = asyncio.Event()
    observer_started = asyncio.Event()
    observer_gate = asyncio.Event()
    observer_task: asyncio.Task[None] | None = None

    class _Capture:
        def attach_wake(self, _wake: asyncio.Event) -> None:
            return None

        async def flush(self) -> dict[str, int]:
            flush_done.set()
            return {"acked": 1}

    async def observer_work() -> None:
        observer_started.set()
        await observer_gate.wait()

    def schedule_observer() -> None:
        nonlocal observer_task
        assert flush_done.is_set()
        callback_called.set()
        observer_task = asyncio.create_task(observer_work())

    loop_task = asyncio.create_task(capture_flush_loop(
        _Capture(), idle_seconds=60,
        after_flush_tick=schedule_observer,  # type: ignore[arg-type]
    ))
    try:
        await callback_called.wait()
        await observer_started.wait()
        assert not loop_task.done(), "observer/model await must not block capture flush loop"
    finally:
        loop_task.cancel()
        if observer_task is not None:
            observer_task.cancel()
        await asyncio.gather(loop_task, observer_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_unified_finalizer_skips_legacy_local_extraction_and_reflection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from langchain_core.messages import AIMessage
    from atlas.agent import run_phases
    from atlas.engine import session_sync

    monkeypatch.setattr(session_sync, "latest_session_message_id", lambda *_a, **_k: "assistant-1")
    monkeypatch.setattr(session_sync, "read_session_all_messages", lambda *_a, **_k: pytest.fail(
        "unified finalizer must not read transcript for legacy extraction"))
    monkeypatch.setattr("atlas.memory.capture.get_capture_service", lambda: None)

    class _Memory:
        def _unified_reads_enabled(self) -> bool:
            return True

        async def save_conversation_metadata(self, *_args: Any, **_kwargs: Any) -> None:
            return None

        async def extract_conversation_candidates(self, *_args: Any, **_kwargs: Any) -> None:
            pytest.fail("unified finalizer must not form legacy candidates")

    class _Reflection:
        async def reflect(self, **_kwargs: Any) -> None:
            pytest.fail("unified finalizer must not write legacy reflections")

    agent = SimpleNamespace(
        _memory=_Memory(), _reflection=_Reflection(),
        trajectory_reviewer=SimpleNamespace(evidence=[]),
        _emit_hook=lambda *_a, **_k: asyncio.sleep(0),
    )
    request = run_phases.RunRequest(message="hello", conversation_id="finalizer-session")
    runtime = SimpleNamespace(
        verify_nudge_sent=False, changed_paths=[], verification_passed=True,
        external_tool_context=False, run_id="run-1", model="model-1",
    )
    state = run_phases._RunState(
        request=request, callbacks=run_phases.RunCallbacks(), message=request.message,
        runtime=runtime, result={"messages": [AIMessage(content="answer")]},
    )
    events = [event async for event in run_phases._phase_finalize(agent, state)]
    assert events[-1]["type"] == "done"
