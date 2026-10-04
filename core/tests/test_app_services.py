"""Production WebSocket run routing stays isolated between FastAPI apps."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from atlas.api.app_services import AppServices
from atlas.api.application import create_app
from atlas.api.runtime import RunState, RuntimeManager


@asynccontextmanager
async def _test_lifespan(_app: FastAPI):
    yield


def _make_app(marker: str) -> tuple[FastAPI, RuntimeManager]:
    manager = RuntimeManager()

    async def start_run(
        connection_id: str, message: dict[str, object], owner: RuntimeManager,
    ) -> None:
        assert owner.services.config == {"marker": marker}
        run_id = str(message["run_id"])
        run = RunState(run_id, f"conversation-{marker}", f"model-{marker}")
        owner.runs[run_id] = run
        owner.conn_runs[connection_id] = run_id
        await owner.send_run(
            run, run.next_envelope("run.started", {"marker": marker}), connection_id,
        )

    async def no_op_handler(*_args) -> None:
        return None

    services = AppServices(
        config={"marker": marker},
        runtime_mgr=manager,
        runtime_start_handler=start_run,
        runtime_resume_handler=no_op_handler,
        rules_trust_handler=no_op_handler,
    )
    return create_app(lifespan=_test_lifespan, services=services), manager


def test_production_ws_chat_routes_concurrent_runs_to_each_app_services() -> None:
    first, first_manager = _make_app("first")
    second, second_manager = _make_app("second")

    def receive_run(app: FastAPI, marker: str) -> dict[str, object]:
        with TestClient(app).websocket_connect("/ws/chat") as websocket:
            websocket.send_json({"type": "run.start", "run_id": f"run-{marker}"})
            return websocket.receive_json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(receive_run, first, "first")
        second_future = pool.submit(receive_run, second, "second")
        first_event = first_future.result(timeout=10)
        second_event = second_future.result(timeout=10)

    assert first_event["run_id"] == "run-first"
    assert first_event["data"] == {"marker": "first"}
    assert second_event["run_id"] == "run-second"
    assert second_event["data"] == {"marker": "second"}
    assert set(first_manager.runs) == {"run-first"}
    assert set(second_manager.runs) == {"run-second"}
    assert first_manager.runs["run-first"].conversation_id == "conversation-first"
    assert second_manager.runs["run-second"].conversation_id == "conversation-second"
    assert first_manager.connections == second_manager.connections == {}
