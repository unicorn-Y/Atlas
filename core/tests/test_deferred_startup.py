"""H8 deferred-component isolation and shutdown behavior."""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest

from atlas.api import deferred_startup
from atlas.api.startup_components import COMPONENT_NAMES, StartupComponents

pytestmark = pytest.mark.unit


@pytest.fixture
def logged() -> list[tuple[str, str]]:
    return []


@pytest.mark.parametrize(
    ("component", "branch"),
    (("dbos", "_start_dbos"), ("mcp", "_start_mcp"), ("channels", "_start_channels")),
)
async def test_deferred_backend_failure_is_logged_and_does_not_escape(
    component: str,
    branch: str,
    monkeypatch: pytest.MonkeyPatch,
    logged: list[tuple[str, str]],
) -> None:
    async def succeeds(*_args: object) -> None:
        return None

    async def starts_skills(_services: object, components: StartupComponents) -> None:
        components.mark("skills", "ready")
        components.mark("plugins", "ready")

    async def fails(*_args: object) -> None:
        raise RuntimeError(f"injected {component} failure")

    for name in (
        "_start_dbos", "_start_mcp", "_start_skills_plugins",
        "_start_engine_registrations", "_start_channels", "_start_automation",
        "_start_scheduler", "_start_telegram", "_register_extensions",
        "_migrate_legacy_sessions",
    ):
        monkeypatch.setattr(deferred_startup, name, succeeds)
    monkeypatch.setattr(deferred_startup, "_start_skills_plugins", starts_skills)
    monkeypatch.setattr(deferred_startup, branch, fails)

    def record_exception(event: str, **_fields: object) -> None:
        logged.append((event, str(sys.exc_info()[1])))

    monkeypatch.setattr(deferred_startup, "log", SimpleNamespace(exception=record_exception))
    startup = StartupComponents()
    for name in COMPONENT_NAMES:
        startup.mark(name, "starting")
    services = SimpleNamespace()
    await deferred_startup.run_deferred_startup(object(), services, startup)

    assert startup.state(component) == "failed"
    assert startup.error_snapshot()[component] == f"injected {component} failure"
    assert any(
        event == "startup.component_failed" and error == f"injected {component} failure"
        for event, error in logged
    )
    # Every deferred branch settles; the startup runner itself remains usable.
    assert all(state in {"ready", "failed"} for state in startup.snapshot().values())


async def test_shutdown_cancellation_leaves_no_deferred_startup_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = asyncio.Event()

    async def blocked(*_args: object) -> None:
        entered.set()
        await asyncio.Event().wait()

    async def succeeds(*_args: object) -> None:
        return None

    async def starts_skills(_services: object, components: StartupComponents) -> None:
        components.mark("skills", "ready")
        components.mark("plugins", "ready")

    for name in (
        "_start_dbos", "_start_mcp", "_start_skills_plugins",
        "_start_engine_registrations", "_start_channels", "_start_automation",
        "_start_scheduler", "_start_telegram", "_register_extensions",
        "_migrate_legacy_sessions",
    ):
        monkeypatch.setattr(deferred_startup, name, succeeds)
    monkeypatch.setattr(deferred_startup, "_start_skills_plugins", starts_skills)
    monkeypatch.setattr(deferred_startup, "_start_mcp", blocked)

    startup = StartupComponents()
    for name in COMPONENT_NAMES:
        startup.mark(name, "starting")
    task = asyncio.create_task(
        deferred_startup.run_deferred_startup(object(), SimpleNamespace(), startup),
        name="atlas-deferred-startup-test",
    )
    await asyncio.wait_for(entered.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0)

    leftovers = [
        child.get_name()
        for child in asyncio.all_tasks()
        if child is not asyncio.current_task() and child.get_name().startswith("startup-")
    ]
    assert leftovers == []


async def test_mcp_without_enabled_servers_is_ready_without_constructing_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from atlas import config

    class EmptyConfig:
        def get(self, key: str, default: object = None) -> object:
            return {"tools.servers": {}, "tools.auto_start": []}.get(key, default)

    constructed: list[bool] = []

    def construct_client() -> object:
        constructed.append(True)
        raise AssertionError("empty MCP configuration must not import/construct the client")

    monkeypatch.setattr(config, "get_config", EmptyConfig)
    monkeypatch.setattr(deferred_startup, "_construct_mcp_client", construct_client)
    startup = StartupComponents()
    startup.mark("mcp", "starting")

    await deferred_startup._component(
        startup, "mcp", lambda: deferred_startup._start_mcp(SimpleNamespace()),
    )

    assert startup.state("mcp") == "ready"
    assert constructed == []


async def test_invalid_mcp_server_settings_fail_instead_of_being_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from atlas import config, server

    class InvalidConfig:
        def get(self, key: str, default: object = None) -> object:
            return {"tools.servers": "invalid", "tools.auto_start": []}.get(key, default)

    class Client:
        async def start(self) -> None:
            raise ValueError("invalid MCP server settings")

    constructed: list[bool] = []

    def construct_client() -> Client:
        constructed.append(True)
        return Client()

    monkeypatch.setattr(config, "get_config", InvalidConfig)
    monkeypatch.setattr(server, "mcp_client", None)
    monkeypatch.setattr(deferred_startup, "_construct_mcp_client", construct_client)
    startup = StartupComponents()
    startup.mark("mcp", "starting")

    await deferred_startup._component(
        startup, "mcp", lambda: deferred_startup._start_mcp(SimpleNamespace()),
    )

    assert startup.state("mcp") == "failed"
    assert constructed == [True]
