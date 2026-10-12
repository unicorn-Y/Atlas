"""Production WebSocket run routing stays isolated between FastAPI apps."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import asyncio
import json

import pytest
from fastapi import WebSocketDisconnect

from fastapi import FastAPI
from fastapi.testclient import TestClient

from atlas.api.app_services import AppServices
from atlas.api.application import create_app
from atlas.api.runtime import RunState, RuntimeManager
from atlas.api.runtime_ws_router import ws_chat


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["running", "paused", "waiting"])
@pytest.mark.parametrize("executor_emits_terminal", [False, True])
async def test_stop_interrupts_blocked_run_and_emits_one_terminal(
    status: str, executor_emits_terminal: bool,
) -> None:
    manager = RuntimeManager()
    run = RunState("blocked", "conversation", "model")
    run.status = status
    manager.runs[run.run_id] = run
    interrupted = asyncio.Event()

    async def blocked_execution() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            interrupted.set()
            if executor_emits_terminal:
                run.status = "cancelled"
                await manager.send_run(run, run.next_envelope("run.cancelled", {}), "")
            raise

    class Socket:
        calls = 0
        sent: list[dict] = []

        async def accept(self):
            pass

        async def receive_text(self):
            await asyncio.sleep(0)
            self.calls += 1
            if self.calls <= 2:
                return json.dumps({"type": "run.cancel", "run_id": run.run_id})
            raise WebSocketDisconnect()

        async def send_json(self, data):
            self.sent.append(data)

    socket = Socket()
    run.task = asyncio.create_task(blocked_execution())
    try:
        await asyncio.wait_for(ws_chat(socket, AppServices(runtime_mgr=manager)), 2)
        assert interrupted.is_set()
        assert run.task.done()
        assert run.cancel_event.is_set()
        assert run.status == "cancelled"
        assert [event["event"] for event in run.events] == ["run.cancelled"]
    finally:
        run.task.cancel()
        await asyncio.gather(run.task, return_exceptions=True)


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
        with TestClient(app, client=("127.0.0.1", 50000)).websocket_connect("/ws/chat") as websocket:
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
