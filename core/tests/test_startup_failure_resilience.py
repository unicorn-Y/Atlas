"""H8 production lifespan failure and shutdown behavior."""

from __future__ import annotations

import asyncio
import subprocess
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from atlas import config, server
from atlas.api import deferred_startup
from atlas.capabilities.durable.dbos_backend import DurableBackend
from atlas.channels import ChannelManager

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_root = tmp_path / "atlas-data"
    config_path = tmp_path / "config" / "atlas.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "[scheduler]\nenabled = false\n\n[tools]\nauto_start = []\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)
    monkeypatch.setattr(config, "DATA_ROOT", data_root)
    monkeypatch.setattr(config, "USER_SETTINGS_PATH", data_root / "data" / "user-settings.json")
    monkeypatch.setattr(config, "_config", None)
    for key in ("OPENAI_API_BASE", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key, raising=False)


def configure_enabled_mcp_server() -> None:
    config.get_config().raw.setdefault("tools", {})["servers"] = {
        "test-server": {"enabled": True},
    }


async def test_production_lifespan_survives_dbos_mcp_and_channel_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_enabled_mcp_server()
    original_services = replace(server.app.state.services)
    global_names = (
        "model_mgr", "memory", "projects", "durable", "plugin_runtime", "notifications",
        "orchestrator", "mcp_client", "local_execution", "computer_use", "capability_bus",
        "cua_backend", "browser_use", "agent_backend_host", "web_runtime", "custom_tools",
        "telegram_service", "skill_mgr", "skill_registry", "scheduler", "usage_ledger",
        "asr_manager", "channel_manager", "gateway_bridge", "heartbeat_service",
    )
    original_globals = {name: getattr(server, name) for name in global_names}
    logged: list[tuple[str, str, str]] = []

    def log_call(level: str, event: str, **fields: Any) -> None:
        error = str(sys.exc_info()[1]) if level == "exception" else ""
        logged.append((level, event, error or str(fields.get("error", ""))))

    class CapturingLog:
        def __getattr__(self, level: str):
            return lambda event, **fields: log_call(level, event, **fields)

    monkeypatch.setattr(deferred_startup, "log", CapturingLog())

    def dbos_failure(_self: DurableBackend, *, run_migrations: bool = True) -> dict[str, Any]:
        return {"started": False, "start_error": "injected DBOS start failure"}

    async def channel_failure(_self: ChannelManager) -> None:
        raise RuntimeError("injected channel start failure")

    class FailingMCP:
        async def start(self) -> None:
            raise RuntimeError("injected MCP start failure")

        async def stop(self) -> None:
            return None

    monkeypatch.setattr(DurableBackend, "start", dbos_failure)
    monkeypatch.setattr(ChannelManager, "start", channel_failure)
    monkeypatch.setattr(deferred_startup, "_construct_mcp_client", FailingMCP)

    try:
        async with server.lifespan(server.app):
            services = server.app.state.services
            assert services.startup is not None
            await asyncio.gather(*(
                services.startup.wait_ready(name, timeout=30)
                for name in ("dbos", "mcp", "channels")
            ))
            async with AsyncClient(
                transport=ASGITransport(app=server.app), base_url="http://test",
            ) as client:
                response = await client.get("/api/health")

            assert response.status_code == 200
            body = response.json()
            assert body["status"] == "starting"
            for name in ("dbos", "mcp", "channels"):
                assert body["components"][name] == "failed"
            assert "injected DBOS start failure" in body["component_errors"]["dbos"]
            assert "injected MCP start failure" in body["component_errors"]["mcp"]
            assert "injected channel start failure" in body["component_errors"]["channels"]
    finally:
        server.app.state.services = original_services
        original_services.runtime_mgr.services = original_services
        for name, value in original_globals.items():
            setattr(server, name, value)

    assert all(
        any(
            level == "exception"
            and event == "startup.component_failed"
            and message == expected
            for level, event, message in logged
        )
        for expected in (
            "injected MCP start failure",
            "injected channel start failure",
        )
    )
    assert any(event == "startup.component_failed" for _, event, _ in logged)


async def test_lifespan_shutdown_stops_blocked_mcp_child_and_startup_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_enabled_mcp_server()
    original_services = replace(server.app.state.services)
    global_names = (
        "model_mgr", "memory", "projects", "durable", "plugin_runtime", "notifications",
        "orchestrator", "mcp_client", "local_execution", "computer_use", "capability_bus",
        "cua_backend", "browser_use", "agent_backend_host", "web_runtime", "custom_tools",
        "telegram_service", "skill_mgr", "skill_registry", "scheduler", "usage_ledger",
        "asr_manager", "channel_manager", "gateway_bridge", "heartbeat_service",
    )
    original_globals = {name: getattr(server, name) for name in global_names}
    mcp_started = asyncio.Event()
    events: list[str] = []
    child: subprocess.Popen[bytes] | None = None

    def delayed_dbos_start(
        _self: DurableBackend, *, run_migrations: bool = True,
    ) -> dict[str, Any]:
        time.sleep(0.1)
        events.append("dbos-start-complete")
        return {"started": True}

    def dbos_stop(_self: DurableBackend) -> None:
        events.append("dbos-stop")

    class BlockingMCP:
        async def start(self) -> None:
            nonlocal child
            child = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            mcp_started.set()
            await asyncio.Event().wait()

        async def stop(self) -> None:
            if child is not None and child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=3)

    monkeypatch.setattr(DurableBackend, "start", delayed_dbos_start)
    monkeypatch.setattr(DurableBackend, "stop", dbos_stop)
    monkeypatch.setattr(ChannelManager, "start", lambda _self: asyncio.sleep(0))
    monkeypatch.setattr(deferred_startup, "_construct_mcp_client", BlockingMCP)

    try:
        async with server.lifespan(server.app):
            await asyncio.wait_for(mcp_started.wait(), timeout=15)
            assert child is not None and child.poll() is None
            deadline = asyncio.get_running_loop().time() + 5
            while (
                "dbos-start-complete" not in events
                and asyncio.get_running_loop().time() < deadline
            ):
                await asyncio.sleep(0.02)
            assert "dbos-start-complete" in events
        await asyncio.sleep(0)
        assert child is not None and child.poll() is not None
        assert "dbos-start-complete" in events
        assert events.index("dbos-start-complete") < events.index("dbos-stop")
        assert not [
            task for task in asyncio.all_tasks()
            if task is not asyncio.current_task()
            and task.get_name().startswith(("startup-", "atlas-deferred-startup"))
        ]
    finally:
        if child is not None and child.poll() is None:
            child.kill()
            child.wait(timeout=3)
        server.app.state.services = original_services
        original_services.runtime_mgr.services = original_services
        for name, value in original_globals.items():
            setattr(server, name, value)


async def test_lifespan_body_error_still_stops_startup_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_enabled_mcp_server()
    original_services = replace(server.app.state.services)
    global_names = (
        "model_mgr", "memory", "projects", "durable", "plugin_runtime", "notifications",
        "orchestrator", "mcp_client", "local_execution", "computer_use", "capability_bus",
        "cua_backend", "browser_use", "agent_backend_host", "web_runtime", "custom_tools",
        "telegram_service", "skill_mgr", "skill_registry", "scheduler", "usage_ledger",
        "asr_manager", "channel_manager", "gateway_bridge", "heartbeat_service",
    )
    original_globals = {name: getattr(server, name) for name in global_names}
    mcp_started = asyncio.Event()
    child: subprocess.Popen[bytes] | None = None

    def dbos_start(_self: DurableBackend, *, run_migrations: bool = True) -> dict[str, Any]:
        return {"started": True}

    def dbos_stop(_self: DurableBackend) -> None:
        return None

    class BlockingMCP:
        async def start(self) -> None:
            nonlocal child
            child = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            mcp_started.set()
            await asyncio.Event().wait()

        async def stop(self) -> None:
            if child is not None and child.poll() is None:
                child.terminate()
                child.wait(timeout=3)

    monkeypatch.setattr(DurableBackend, "start", dbos_start)
    monkeypatch.setattr(DurableBackend, "stop", dbos_stop)
    monkeypatch.setattr(ChannelManager, "start", lambda _self: asyncio.sleep(0))
    monkeypatch.setattr(deferred_startup, "_construct_mcp_client", BlockingMCP)

    try:
        with pytest.raises(RuntimeError, match="injected lifespan body error"):
            async with server.lifespan(server.app):
                await asyncio.wait_for(mcp_started.wait(), timeout=15)
                assert child is not None and child.poll() is None
                deferred = next(
                    task for task in asyncio.all_tasks()
                    if task.get_name() == "atlas-deferred-startup"
                )
                deferred.cancel()
                await asyncio.gather(deferred, return_exceptions=True)
                raise RuntimeError("injected lifespan body error")

        assert child is not None and child.poll() is not None
        assert not [
            task for task in asyncio.all_tasks()
            if task is not asyncio.current_task()
            and task.get_name().startswith(("startup-", "atlas-deferred-startup"))
        ]
    finally:
        if child is not None and child.poll() is None:
            child.kill()
            child.wait(timeout=3)
        server.app.state.services = original_services
        original_services.runtime_mgr.services = original_services
        for name, value in original_globals.items():
            setattr(server, name, value)


async def test_preyield_constructor_failure_closes_initialized_memory_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_services = replace(server.app.state.services)
    global_names = (
        "model_mgr", "memory", "projects", "durable", "plugin_runtime", "notifications",
        "orchestrator", "mcp_client", "local_execution", "computer_use", "capability_bus",
        "cua_backend", "browser_use", "agent_backend_host", "web_runtime", "custom_tools",
        "telegram_service", "skill_mgr", "skill_registry", "scheduler", "usage_ledger",
        "asr_manager", "channel_manager", "gateway_bridge", "heartbeat_service",
    )
    original_globals = {name: getattr(server, name) for name in global_names}
    worker_threads: list[threading.Thread] = []
    closed: list[bool] = []
    memory_type = server.MemoryStore

    def tracked_memory_store(*args: Any, **kwargs: Any) -> Any:
        store = memory_type(*args, **kwargs)
        initialize = store.init
        close = store.close

        async def tracked_init() -> None:
            await initialize()
            assert store._db is not None
            worker_threads.append(store._db._thread)

        async def tracked_close() -> None:
            await close()
            closed.append(True)

        store.init = tracked_init
        store.close = tracked_close
        return store

    def fail_usage_ledger(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("injected pre-yield constructor failure")

    monkeypatch.setattr(server, "MemoryStore", tracked_memory_store)
    monkeypatch.setattr(server, "UsageLedger", fail_usage_ledger)

    try:
        with pytest.raises(RuntimeError, match="injected pre-yield constructor failure"):
            async with server.lifespan(server.app):
                pytest.fail("startup must fail before yielding")
        assert closed == [True]
        assert len(worker_threads) == 1
        assert not worker_threads[0].is_alive()
        assert server.mcp_client is None
        assert not [
            task for task in asyncio.all_tasks()
            if task is not asyncio.current_task()
            and task.get_name().startswith(("startup-", "atlas-deferred-startup"))
        ]
    finally:
        server.app.state.services = original_services
        original_services.runtime_mgr.services = original_services
        for name, value in original_globals.items():
            setattr(server, name, value)


async def test_cancelled_dbos_worker_cannot_publish_late_global_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from atlas.api import dbos_startup

    entered = threading.Event()
    release = threading.Event()
    launched = threading.Event()
    dbos_internal = ModuleType("dbos._dbos")
    dbos_internal._dbos_global_instance = None

    class FakeDBOS:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def step(self):
            return lambda function: function

        def workflow(self):
            return lambda function: function

        @staticmethod
        def launch() -> None:
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test launch release timed out")
            dbos_internal._dbos_global_instance = object()
            launched.set()

        @staticmethod
        def destroy(*, destroy_registry: bool = False) -> None:
            dbos_internal._dbos_global_instance = None

    dbos_module = ModuleType("dbos")
    dbos_module.DBOS = FakeDBOS
    monkeypatch.setitem(sys.modules, "dbos", dbos_module)
    monkeypatch.setitem(sys.modules, "dbos._dbos", dbos_internal)
    monkeypatch.setattr(dbos_startup, "migrations_current", lambda _path: True)
    monkeypatch.setattr(dbos_startup, "record_started", lambda *_args, **_kwargs: None)

    durable = DurableBackend(config.get_config().db_path.parent / "dbos.sqlite")
    durable.set_dispatcher(lambda _payload: asyncio.sleep(0, result={}), asyncio.get_running_loop())
    worker = asyncio.create_task(deferred_startup._start_dbos(SimpleNamespace(durable=durable)))
    dbos_worker: asyncio.Task[Any] | None = None
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        dbos_worker = next(
            task for task in asyncio.all_tasks()
            if task.get_name() == "startup-dbos-worker"
        )
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker
        release.set()
        assert await asyncio.to_thread(launched.wait, 3)
        assert dbos_worker is not None
        await asyncio.wait_for(asyncio.shield(dbos_worker), timeout=3)
        deadline = asyncio.get_running_loop().time() + 3
        while dbos_internal._dbos_global_instance is not None:
            if asyncio.get_running_loop().time() >= deadline:
                pytest.fail("cancelled DBOS worker published a late singleton")
            await asyncio.sleep(0.01)
        assert not durable.started
        assert dbos_worker.done()
        assert not [
            task for task in asyncio.all_tasks()
            if task is not asyncio.current_task()
            and task.get_name() == "startup-dbos-worker"
        ]
    finally:
        release.set()


