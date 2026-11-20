"""The composition root must be lazy, reversible, and fail closed.

`AppServices` is a flat 52-field dataclass: a field is either assigned in the
lifespan or left None, nothing records who provided it, and nothing can take it
back. This registry adds ownership and reversibility without touching the
dataclass or its 73 call sites.

The properties pinned here are the ones a plugin unload depends on.
"""

from __future__ import annotations

import pytest

from atlas.api.service_registry import (
    ServiceNotRegistered,
    ServiceRegistry,
)

pytestmark = pytest.mark.unit


class _DisposableService:
    def __init__(self) -> None:
        self._sessions: dict[str, object] = {}
        self.sessions = self

    def close(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def shutdown(self) -> None:
        pass

    async def aclose(self) -> None:
        pass

    async def close_session(self, _session_id: str) -> None:
        pass


def test_registration_is_lazy():
    built: list[str] = []
    registry = ServiceRegistry()
    registry.register("demo", lambda: built.append("built") or {"v": 1})

    assert built == [], "a registered but unused service must cost nothing"
    registry.resolve("demo")
    assert built == ["built"]


def test_resolve_returns_one_instance():
    registry = ServiceRegistry()
    registry.register("demo", lambda: object())
    assert registry.resolve("demo") is registry.resolve("demo")


def test_a_failing_factory_is_not_cached():
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        raise RuntimeError("half built")

    registry = ServiceRegistry()
    registry.register("demo", boom)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            registry.resolve("demo")
    assert calls["n"] == 2, "a failed build must be retried, not pinned"


def test_disposer_makes_the_service_unresolvable():
    registry = ServiceRegistry()
    dispose = registry.register("demo", lambda: 1)
    assert registry.has("demo")
    dispose()
    assert not registry.has("demo")
    with pytest.raises(ServiceNotRegistered):
        registry.resolve("demo")


def test_duplicate_registration_names_the_existing_owner():
    registry = ServiceRegistry()
    registry.register("demo", lambda: 1, owner="plugin:alpha")
    with pytest.raises(ValueError) as caught:
        registry.register("demo", lambda: 2, owner="plugin:beta")
    assert "plugin:alpha" in str(caught.value)


def test_unregister_owner_drops_only_that_contributor():
    registry = ServiceRegistry()
    registry.register("a", lambda: 1, owner="plugin:alpha")
    registry.register("b", lambda: 2, owner="plugin:alpha")
    registry.register("c", lambda: 3, owner="core")

    assert registry.unregister_owner("plugin:alpha") == 2
    assert registry.snapshot() == {"c": "core"}


def test_missing_service_lists_registered_owners():
    registry = ServiceRegistry()
    registry.register("a", lambda: 1, owner="plugin:alpha")
    with pytest.raises(ServiceNotRegistered) as caught:
        registry.resolve("nope")
    assert "plugin:alpha" in str(caught.value)


def test_bind_into_only_fills_attributes_that_exist():
    class Target:
        a: object = None

    registry = ServiceRegistry()
    registry.register("a", lambda: "value-a")
    registry.register("unknown", lambda: "should-not-appear")

    bound = registry.bind_into(Target())
    assert bound == ["a"]
    assert not hasattr(Target(), "unknown"), "a typo must not add surface area"


def test_owner_counts_are_reportable():
    registry = ServiceRegistry()
    registry.register("a", lambda: 1, owner="core")
    registry.register("b", lambda: 2, owner="core")
    registry.register("c", lambda: 3, owner="plugin:x")
    assert registry.owners() == {"core": 2, "plugin:x": 1}


# --- integration with AppServices and introspection -------------------------

def test_app_services_defaults_to_a_real_registry():
    from atlas.api.app_services import AppServices

    services = AppServices()
    assert services.service_registry.snapshot() == {}
    services.service_registry.register("demo", lambda: 1, owner="plugin:x")
    assert services.service_registry.snapshot() == {"demo": "plugin:x"}


def test_two_containers_do_not_share_a_registry():
    from atlas.api.app_services import AppServices

    first, second = AppServices(), AppServices()
    first.service_registry.register("only-here", lambda: 1)
    assert second.service_registry.snapshot() == {}


def test_introspect_registry_method_reports_owners():
    from atlas.api.app_services import AppServices
    from atlas.introspect.providers import services as provider

    services = AppServices()
    services.service_registry.register("a", lambda: 1, owner="core:lifespan")
    services.service_registry.register("b", lambda: 2, owner="plugin:x")

    class _Ctx:
        pass

    ctx = _Ctx()
    ctx.services = services
    result = provider._registry(ctx, {})
    assert result["count"] == 2
    assert result["by_owner"] == {"core:lifespan": 1, "plugin:x": 1}


def test_dependencies_are_built_before_the_service_that_needs_them() -> None:
    """Declaring a dependency must make resolve build it first."""
    order: list[str] = []
    registry = ServiceRegistry()
    registry.register("db", lambda: order.append("db") or object())
    registry.register(
        "repo", lambda: order.append("repo") or object(), depends_on=("db",),
    )

    registry.resolve("repo")

    assert order == ["db", "repo"]


def test_a_missing_dependency_is_refused_at_registration() -> None:
    """A wiring typo should fail where the wiring is written, not at first use."""
    registry = ServiceRegistry()
    with pytest.raises(ServiceNotRegistered, match="depends on unregistered"):
        registry.register("repo", lambda: object(), depends_on=("never_registered",))


def test_a_service_cannot_depend_on_itself() -> None:
    registry = ServiceRegistry()
    with pytest.raises(ValueError, match="depend on itself"):
        registry.register("loop", lambda: object(), depends_on=("loop",))


def test_a_cycle_is_refused_instead_of_recursing_forever() -> None:
    """Two services can each be registered first, so the cycle only shows at build."""
    registry = ServiceRegistry()
    registry.register("a", lambda: object())
    registry.register("b", lambda: object(), depends_on=("a",))
    # Rewrite a's declared dependencies to close the loop, bypassing register's
    # up-front check the way a later plugin could.
    registry._entries["a"].depends_on = ("b",)

    with pytest.raises(ValueError, match="dependency cycle"):
        registry.resolve("a")


def test_unregistering_a_dependency_takes_its_dependents_with_it() -> None:
    """Disposing a shared service must not leave a component holding a dead one."""
    disposed: list[str] = []
    registry = ServiceRegistry()
    registry.register("db", lambda: object(), disposer=lambda: disposed.append("db"))
    registry.register(
        "repo", lambda: object(), depends_on=("db",),
        disposer=lambda: disposed.append("repo"),
    )

    registry.unregister("db")

    assert disposed == ["repo", "db"], "dependents must be disposed first"
    assert not registry.has("repo")
    assert not registry.has("db")


def test_unregister_owner_disposes_dependents_before_dependencies() -> None:
    disposed: list[str] = []
    registry = ServiceRegistry()
    registry.register("base", lambda: object(), owner="plugin",
                      disposer=lambda: disposed.append("base"))
    registry.register("mid", lambda: object(), owner="plugin", depends_on=("base",),
                      disposer=lambda: disposed.append("mid"))
    registry.register("top", lambda: object(), owner="plugin", depends_on=("mid",),
                      disposer=lambda: disposed.append("top"))

    removed = registry.unregister_owner("plugin")

    assert removed == 3
    assert disposed == ["top", "mid", "base"]


def test_dependencies_introspection_lists_only_declared_edges() -> None:
    registry = ServiceRegistry()
    registry.register("db", lambda: object())
    registry.register("repo", lambda: object(), depends_on=("db",))

    assert registry.dependencies() == {"repo": ["db"]}


def test_registry_introspection_reports_declared_edges() -> None:
    """`services.registry` must expose the graph, not just the name list."""
    from atlas.introspect.providers.services import _registry

    class Container:
        pass

    container = Container()
    container.service_registry = ServiceRegistry()
    container.service_registry.register("db", lambda: object())
    container.service_registry.register("repo", lambda: object(), depends_on=("db",))

    ctx = type("Ctx", (), {"services": container})()
    result = _registry(ctx, {})

    assert result["count"] == 2
    assert result["depends_on"] == {"repo": ["db"]}


@pytest.mark.asyncio
async def test_lifespan_registers_real_service_edges_and_removes_its_owner() -> None:
    from atlas.api.app_services import AppServices
    from atlas.server import _LIFESPAN_SERVICE_DEPENDENCIES, _register_lifespan_services

    services = AppServices()
    for name, dependencies in _LIFESPAN_SERVICE_DEPENDENCIES.items():
        setattr(services, name, _DisposableService())
        for dependency in dependencies:
            setattr(services, dependency, _DisposableService())

    _register_lifespan_services(services)

    graph = services.service_registry.dependencies()
    assert {name: graph[name] for name in _LIFESPAN_SERVICE_DEPENDENCIES} == {
        name: list(dependencies)
        for name, dependencies in _LIFESPAN_SERVICE_DEPENDENCIES.items()
    }
    assert services.service_registry.owners()["core:lifespan"] >= len(
        _LIFESPAN_SERVICE_DEPENDENCIES,
    )
    assert await services.service_registry.unregister_owner_async("core:lifespan")
    assert services.service_registry.snapshot() == {}


@pytest.mark.asyncio
async def test_lifespan_resource_shutdown_uses_reverse_dependency_order() -> None:
    from atlas.api.deferred_startup import _run_shutdown_actions

    registry = ServiceRegistry()
    registry.register("dependency", lambda: object(), owner="core:lifespan")
    registry.register(
        "dependent", lambda: object(), owner="core:lifespan",
        depends_on=("dependency",),
    )
    closed: list[str] = []

    async def record(name: str) -> None:
        closed.append(name)

    await _run_shutdown_actions(registry, {
        "dependency": lambda: record("dependency"),
        "dependent": lambda: record("dependent"),
    })

    assert closed == ["dependent", "dependency"]


@pytest.mark.asyncio
async def test_shutdown_actions_run_unknown_names_with_an_empty_registry() -> None:
    from atlas.api.deferred_startup import _run_shutdown_actions

    closed: list[str] = []
    await _run_shutdown_actions(ServiceRegistry(), {
        "delayed_scheduler": lambda: closed.append("scheduler"),
        "unregistered_manager": lambda: closed.append("manager"),
    })

    assert closed == ["scheduler", "manager"]


@pytest.mark.asyncio
async def test_lifespan_shutdown_orders_gateway_before_its_channel_manager(monkeypatch) -> None:
    from types import SimpleNamespace

    import atlas.api.deferred_startup as deferred
    import atlas.server as server
    from atlas.api.app_services import AppServices
    from atlas.tools.x2 import browser as x2browser
    from atlas.tools.x2 import computer as x2computer

    closed: list[str] = []

    class ChannelManager:
        async def stop(self) -> None:
            closed.append("channel.stop")

        def close(self) -> None:
            closed.append("channel.close")

    class GatewayBridge:
        class Sessions:
            def close(self) -> None:
                closed.append("gateway.close")

        sessions = Sessions()

    class DelayedScheduler:
        async def stop(self) -> None:
            closed.append("scheduler.stop")

    class RuntimeManager:
        async def close(self) -> None:
            closed.append("manager.close")

    services = AppServices(channel_manager=ChannelManager(), gateway_bridge=GatewayBridge())
    registry = services.service_registry
    registry.register(
        "channel_manager", lambda: services.channel_manager, owner="core:lifespan",
        disposer=services.channel_manager.close,
    )
    registry.register(
        "gateway_bridge", lambda: services.gateway_bridge, owner="core:lifespan",
        depends_on=("channel_manager",),
        disposer=services.gateway_bridge.sessions.close,
    )
    services.service_registry = registry
    state = {name: None for name in (
        "telegram_service", "scheduler", "channel_manager", "gateway_bridge",
        "heartbeat_service", "mcp_client", "local_execution", "computer_use",
        "cua_backend", "browser_use", "ssh_workspaces", "agent_backend_host",
        "durable", "projects", "usage_ledger", "memory", "manager",
    )}
    state["services"] = services
    state["channel_manager"] = services.channel_manager
    state["gateway_bridge"] = services.gateway_bridge
    state["scheduler"] = DelayedScheduler()
    state["manager"] = RuntimeManager()

    async def noop(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(deferred, "_stop_background_startup_tasks", noop)
    monkeypatch.setattr(deferred, "restore_lifespan_routes", lambda *_args: None)
    monkeypatch.setattr(server, "get_automation_engine", lambda: None)
    monkeypatch.setattr(x2computer, "shutdown", noop)
    monkeypatch.setattr(x2browser, "shutdown", noop)
    from atlas.api import group_router
    monkeypatch.setattr(group_router, "set_group_orchestrator", lambda *_args: None)
    monkeypatch.setattr(group_router, "set_group_service", lambda *_args: None)

    app = SimpleNamespace(state=SimpleNamespace(), router=SimpleNamespace(routes=[]))
    await deferred.shutdown_lifespan_components(app, state, 0)

    assert closed == [
        "scheduler.stop", "channel.stop", "gateway.close", "channel.close", "manager.close",
    ]


@pytest.mark.asyncio
async def test_lifespan_rejects_another_owner_for_a_different_service_instance() -> None:
    from atlas.api.app_services import AppServices
    from atlas.server import _register_lifespan_services

    plugin_backend = _DisposableService()
    core_backend = _DisposableService()
    services = AppServices(cua_backend=core_backend, computer_use=_DisposableService())
    services.service_registry.register("cua_backend", lambda: plugin_backend, owner="plugin:computer")

    with pytest.raises(RuntimeError, match="conflicts with provider 'plugin:computer'"):
        _register_lifespan_services(services)

    assert services.service_registry.resolve("cua_backend") is plugin_backend
    assert services.cua_backend is core_backend
    assert set(services.service_registry.snapshot()) == {"cua_backend"}, (
        "provider preflight must fail before registering core dependents"
    )
    await services.service_registry.unregister_owner_async("plugin:computer")
    assert not services.service_registry.has("cua_backend")
    assert services.cua_backend is core_backend


@pytest.mark.asyncio
async def test_core_teardown_flushes_plugin_dependents_and_continues_after_errors() -> None:
    from atlas.api.app_services import AppServices

    closed: list[str] = []
    services = AppServices()

    async def close_memory() -> None:
        closed.append("memory.close")

    async def failing_plugin_flush() -> None:
        closed.append("plugin.failure.flush")
        raise RuntimeError("injected plugin flush failure")

    async def plugin_flush() -> None:
        closed.append("plugin.flush")

    services.service_registry.register(
        "memory", lambda: object(), owner="core:lifespan", disposer=close_memory,
    )
    services.service_registry.register(
        "plugin.failure", lambda: object(), owner="plugin:dependent",
        depends_on=("memory",), disposer=failing_plugin_flush,
    )
    services.service_registry.register(
        "plugin.consumer", lambda: object(), owner="plugin:dependent",
        depends_on=("memory",), disposer=plugin_flush,
    )

    with pytest.raises(ExceptionGroup, match="1 failure"):
        await services.service_registry.unregister_owner_async("core:lifespan")

    assert closed == ["plugin.failure.flush", "plugin.flush", "memory.close"]
    assert services.service_registry.snapshot() == {}
