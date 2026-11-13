"""The finalizer registry must actually reach a run, not just exist.

``ToolResultFinalizers`` is easy to build and easy to leave unconnected — the
repository's own ledger records that exact failure (a capability built, wired
into nothing, and reported as done). These tests pin the three links that carry a
registration from a host to the kernel:

    AppServices.tool_result_finalizers
        -> RunRequest.tool_result_finalizers
        -> runtime.tool_result_finalizers
        -> the kernel's ``tool_finalizers``

plus the fallback: a runtime without one must get a fresh empty registry, so the
kernel's behaviour is unchanged for every existing caller.
"""

from __future__ import annotations

import pytest

from atlas.agent.run_phases import RunRequest
from atlas.api.app_services import AppServices
from atlas.engine.kernel.tool_finalize import FinalizedOutput, ToolResultFinalizers

pytestmark = pytest.mark.unit


def test_app_services_default_constructs_a_usable_registry():
    services = AppServices()

    assert isinstance(services.tool_result_finalizers, ToolResultFinalizers)
    assert len(services.tool_result_finalizers) == 0

    disposer = services.tool_result_finalizers.register(
        "probe", lambda result, view: FinalizedOutput(f"seen:{result.content}", result.output),
    )
    assert services.tool_result_finalizers.names() == ["probe"]
    disposer()
    assert services.tool_result_finalizers.names() == []


def test_two_containers_do_not_share_a_registry():
    first, second = AppServices(), AppServices()
    first.tool_result_finalizers.register("only-here", lambda r, v: r)

    assert second.tool_result_finalizers.names() == []


def test_run_request_carries_the_registry_by_identity():
    registry = ToolResultFinalizers()
    request = RunRequest(message="hi", conversation_id="c1", tool_result_finalizers=registry)

    assert request.tool_result_finalizers is registry


def test_run_request_defaults_to_none_so_existing_callers_are_unchanged():
    request = RunRequest(message="hi", conversation_id="c1")

    assert request.tool_result_finalizers is None


def test_run_phases_assigns_the_registry_onto_the_run_context():
    """The link that makes the kernel see it: ``runtime.tool_result_finalizers``."""
    source = __import__("pathlib").Path("atlas/agent/run_phases.py").read_text(encoding="utf-8")

    assert "runtime.tool_result_finalizers = request.tool_result_finalizers" in source


def test_kernel_falls_back_to_an_empty_registry_when_the_runtime_has_none():
    source = __import__("pathlib").Path("atlas/engine/kernel/loop.py").read_text(encoding="utf-8")

    assert 'getattr(runtime, "tool_result_finalizers", None)' in source
    # And the fallback must be a real registry, not a sentinel that disables the seam.
    assert "tool_finalizers = ToolResultFinalizers()" in source
