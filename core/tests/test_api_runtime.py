"""Persistence behavior for the extracted per-app runtime manager."""

import ast
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atlas.api.app_services import AppServices
from atlas.api.runtime import RunState, RuntimeManager
from atlas.api.runtime_router import router as runtime_router


@pytest.mark.asyncio
async def test_runtime_manager_recovers_interrupted_run_as_failed(tmp_path) -> None:
    db_path = tmp_path / "runtime.sqlite3"
    manager = RuntimeManager(db_path)
    await manager.init()
    run = RunState("run-1", "conversation-1", "model-1")
    run.next_envelope("run.started", {})
    await manager.persist_run(run)
    await manager.close()

    restarted = RuntimeManager(db_path)
    await restarted.init()
    try:
        recovered = restarted.runs["run-1"]
        assert recovered.status == "failed"
        assert recovered.events[-1]["event"] == "run.failed"
        assert recovered.events[-1]["data"]["category"] == "interrupted"
        assert recovered.sequence == 2
    finally:
        await restarted.close()


def test_cancel_subtask_route_uses_app_runtime_manager() -> None:
    manager = RuntimeManager()
    run = RunState("run-1", "conversation-1", "model-1")
    import threading

    cancel_event = threading.Event()
    run.subtasks["subtask-1"] = {"status": "running", "cancel_event": cancel_event}
    manager.runs[run.run_id] = run
    app = FastAPI()
    app.state.services = AppServices(runtime_mgr=manager)
    app.include_router(runtime_router)

    response = TestClient(app).post("/api/runs/run-1/subtasks/subtask-1/cancel")

    assert response.status_code == 200
    assert response.json() == {"status": "cancelling", "subtask_id": "subtask-1"}
    assert cancel_event.is_set()


@pytest.mark.asyncio
async def test_native_subtask_recovery_point_survives_runtime_restart(tmp_path) -> None:
    db_path = tmp_path / "runtime.sqlite3"
    manager = RuntimeManager(db_path)
    await manager.init()
    await manager.save_subtask({
        "parent_run_id": "run-1", "subtask_id": "child-1", "status": "running",
        "goal": "Finish the migration", "backend": "atlas", "workspace": "C:/repo",
        "model": "model-x", "session_id": "session-x",
        "recovery_point": {"conversation_id": "parent-session", "workspace": "C:/repo", "goal": "Finish the migration"},
    })
    await manager.close()

    restarted = RuntimeManager(db_path)
    await restarted.init()
    try:
        child = await restarted.get_subtask("run-1", "child-1")
        assert child["status"] == "closed"
        assert child["session_id"] == "session-x"
        assert child["workspace"] == "C:/repo"
        assert child["recovery_point"]["goal"] == "Finish the migration"
        assert (await restarted.list_subtasks("run-1"))[0]["subtask_id"] == "child-1"
    finally:
        await restarted.close()


@pytest.mark.asyncio
async def test_native_subtask_close_route_persists_closed_state(tmp_path) -> None:
    from httpx import ASGITransport, AsyncClient

    manager = RuntimeManager(tmp_path / "runtime.sqlite3")
    await manager.init()
    await manager.save_subtask({
        "parent_run_id": "run-1", "subtask_id": "child-1", "status": "running",
        "goal": "Do work", "backend": "atlas", "workspace": "C:/repo",
        "model": "model-x", "session_id": "session-x",
        "recovery_point": {"workspace": "C:/repo"},
    })
    app = FastAPI()
    app.state.services = AppServices(runtime_mgr=manager)
    app.include_router(runtime_router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/runs/run-1/subtasks/child-1/close")
    assert response.status_code == 200
    assert response.json()["status"] == "closed"
    assert (await manager.get_subtask("run-1", "child-1"))["status"] == "closed"
    await manager.close()


@pytest.mark.asyncio
async def test_native_subtask_resume_reuses_preserved_transcript(tmp_path) -> None:
    from httpx import ASGITransport, AsyncClient

    class Memory:
        async def get_conversation(self, conversation_id):
            return {"id": conversation_id}

    class Orchestrator:
        def __init__(self):
            self.options = None

        async def _run_atlas_subtask(self, **kwargs):
            self.options = kwargs
            return {"status": "completed", "session_id": kwargs["atlas_options"]["resume_session_id"]}

    manager = RuntimeManager(tmp_path / "runtime.sqlite3")
    await manager.init()
    await manager.save_subtask({
        "parent_run_id": "run-1", "subtask_id": "child-1", "status": "closed",
        "goal": "Finish the migration", "backend": "atlas", "workspace": "C:/repo",
        "model": "model-x", "session_id": "session-x",
        "recovery_point": {"workspace": "C:/repo"},
    })
    orchestrator = Orchestrator()
    app = FastAPI()
    app.state.services = AppServices(runtime_mgr=manager, memory=Memory(), orchestrator=orchestrator)
    app.include_router(runtime_router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/runs/run-1/subtasks/child-1/resume")
        assert response.status_code == 200
        for _ in range(20):
            task = manager.subtask_tasks.get(("run-1", "child-1"))
            if task is None:
                break
            await task
        terminal = await client.post("/api/runs/run-1/subtasks/child-1/resume")
    assert orchestrator.options["atlas_options"]["resume_session_id"] == "session-x"
    assert orchestrator.options["cwd"] == "C:/repo"
    assert (await manager.get_subtask("run-1", "child-1"))["status"] == "completed"
    assert terminal.status_code == 409
    assert "已完成的终态不支持恢复" in terminal.json()["detail"]
    await manager.close()


# Fields wired outside the lifespan body: runtime_mgr at the app factory, the
# WS protocol handlers at the server module tail, and routers still on their
# legacy module singletons (not yet migrated to the container).
_LIFESPAN_WIRED_ELSEWHERE = frozenset({
    "runtime_mgr", "runtime_start_handler", "runtime_resume_handler",
    "rules_trust_handler",
})
_LIFESPAN_LEGACY_SINGLETON_FIELDS = frozenset({
    "sandbox_manager", "skill_catalog_provider", "agent_skill_collections",
    "skill_proposals", "vault_store_factory", "local_runtime_adapter",
    "skills_market_supplier",
})


def test_server_lifespan_populates_every_appservices_field() -> None:
    """The production lifespan must fill every container field handlers read.

    Regression guard: device handlers read ``services.device_registry`` /
    ``services.takeover`` while the lifespan only fed the legacy module
    singletons, so every real /api/devices request failed at runtime.
    """
    import dataclasses

    import atlas.server as server_module

    lifespan_source = inspect_lifespan(server_module)
    assigned: set[str] = set()
    for node in _walk_lifespan_scope(lifespan_source):
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
            target = node.value
            if (isinstance(target, ast.Name) and target.id == "services") or (
                isinstance(target, ast.Attribute) and target.attr == "services"
            ):
                assigned.add(node.attr)
        # `for service_name in ("model_mgr", ...): setattr(services, service_name, ...)`
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "setattr" and len(node.args) == 3
                and isinstance(node.args[1], ast.Name) and isinstance(node.args[2], ast.Call)):
            loop = _loop_variable_source(lifespan_source, node.args[1].id)
            if loop is not None:
                assigned |= _string_constants(loop)

    declared = {field.name for field in dataclasses.fields(AppServices)}
    unpopulated = declared - assigned - _LIFESPAN_WIRED_ELSEWHERE
    lazy_fields = {"asr_manager"}
    assert unpopulated & lazy_fields == lazy_fields, (
        "ASRManager should remain lazy until an ASR endpoint needs it"
    )
    assert unpopulated - lazy_fields <= _LIFESPAN_LEGACY_SINGLETON_FIELDS, (
        f"lifespan never populates non-lazy AppServices fields: "
        f"{sorted(unpopulated - lazy_fields)}"
    )


def _loop_variable_source(lifespan_source: ast.AST, variable: str) -> ast.expr | None:
    """Find the iterable of the ``for <variable> in ...`` loop around a setattr."""
    for node in ast.walk(lifespan_source):
        if isinstance(node, ast.For) and isinstance(node.target, ast.Name) \
                and node.target.id == variable:
            return node.iter
    return None


def _string_constants(node: ast.expr) -> set[str]:
    return {item.value for item in ast.walk(node)
            if isinstance(item, ast.Constant) and isinstance(item.value, str)}


def inspect_lifespan(server_module) -> ast.FunctionDef:
    """Return the parsed lifespan function of the server module."""
    tree = ast.parse(Path(server_module.__file__).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "lifespan":
            return node
    raise AssertionError("atlas.server must define a lifespan function")


def _walk_lifespan_scope(scope: ast.AST):
    """Walk lifespan-owned statements without counting lazy nested callbacks."""
    pending = list(ast.iter_child_nodes(scope))
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        yield node
        pending.extend(ast.iter_child_nodes(node))
