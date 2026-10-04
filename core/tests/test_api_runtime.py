"""Persistence behavior for the extracted per-app runtime manager."""

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
