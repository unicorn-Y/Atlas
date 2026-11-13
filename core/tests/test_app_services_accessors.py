"""``AppServices`` guarded accessors.

The failure these exist for: a handler calls ``services.memory.recall(...)`` while
the lifespan never bound ``memory``. The result is
``AttributeError: 'NoneType' object has no attribute 'recall'`` — a 500 whose
traceback names the *attribute* and never the field that was actually missing.
Each test here pins the message that replaces it.
"""

from __future__ import annotations

import pytest

from atlas.api.app_services import AppServices


def test_require_names_the_unwired_field() -> None:
    services = AppServices()
    with pytest.raises(LookupError, match="memory"):
        services.require("memory")


def test_require_names_a_missing_field_differently() -> None:
    """A typo and an unwired dependency are different bugs, so they say so."""
    services = AppServices()
    with pytest.raises(LookupError, match="没有字段"):
        services.require("memroy")


def test_require_returns_the_bound_service() -> None:
    services = AppServices()
    sentinel = object()
    services.memory = sentinel
    assert services.require("memory") is sentinel


def test_has_separates_declared_from_bound() -> None:
    services = AppServices()
    assert services.has("memory") is False
    services.memory = object()
    assert services.has("memory") is True
    assert services.has("typo") is False


def test_maybe_is_none_for_both_cases() -> None:
    services = AppServices()
    assert services.maybe("memory") is None
    assert services.maybe("typo") is None
    services.memory = "bound"
    assert services.maybe("memory") == "bound"


def test_missing_lists_undeclared_before_unbound() -> None:
    """Order matters: the typo is fixed in the caller, the unbound field in wiring."""
    services = AppServices()
    assert services.missing("memory", "typo") == ["typo", "memory"]


def test_missing_is_empty_when_both_are_bound() -> None:
    services = AppServices()
    services.memory = object()
    assert services.missing("memory") == []


def test_wired_reports_types_not_values() -> None:
    services = AppServices()
    services.model_mgr = object()
    wired = services.wired()
    assert wired["model_mgr"] == "object"
    assert "memory" not in wired


def test_every_container_has_a_projections_registry() -> None:
    """The default factory must bind at construction, not at lifespan.

    A bare container is what tests and the CLI build, and introspection over it
    must still find a usable registry rather than reporting it absent.
    """
    services = AppServices()
    assert services.has("session_projections")
    assert "session_projections" in services.wired()


def test_two_containers_do_not_share_projections() -> None:
    first, second = AppServices(), AppServices()
    first.session_projections.register(
        "demo", lambda key, _s=None: key, depends_on=("run.completed",)
    )
    assert list(first.session_projections.names()) == ["demo", "session.summary"]
    assert list(second.session_projections.names()) == ["session.summary"]


def test_unwired_and_wired_partition_the_declared_fields() -> None:
    services = AppServices()
    declared = set(type(services).__slots__)
    wired = set(services.wired())
    unwired = set(services.unwired())
    assert wired | unwired == declared
    assert wired & unwired == set()
