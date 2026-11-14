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
