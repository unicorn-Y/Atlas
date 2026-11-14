"""E25: production idle-maintenance producer wired into the kernel's runMaintenance slot.

Before WAVE5 the kernel slot existed (``AtlasKernel.runMaintenance``) and
``atlas_runtime`` already called it after every successful run, but no host
provided ``maintenance_callback`` so the slot degenerated to a no-op. These
tests pin the producer contract end to end.
"""

from __future__ import annotations

import asyncio

import pytest

from atlas.agent import AgentRunContext
from atlas.engine.kernel.loop import AtlasKernel
from atlas.agent.run_phases import _idle_maintenance_callback


@pytest.mark.unit
def test_run_context_declares_maintenance_callback_defaulting_to_none():
    runtime = AgentRunContext()
    assert runtime.maintenance_callback is None
    runtime.maintenance_callback = lambda: None
    assert callable(runtime.maintenance_callback)


@pytest.mark.unit
def test_producer_runs_state_db_maintenance_and_returns_its_report():
    """The producer runs the throttled SessionDB sweep and surfaces its report."""
    callback = _idle_maintenance_callback()
    assert asyncio.iscoroutinefunction(callback)

    report = asyncio.run(callback())

    assert isinstance(report, dict)
    # The sweep's own contract: idempotent result record with skip/prune counters.
    assert {"skipped", "pruned", "closed", "vacuumed"} <= set(report)


@pytest.mark.unit
def test_producer_survives_a_broken_state_db_without_raising(monkeypatch, tmp_path):
    """Maintenance must never raise into the kernel's idle slot."""
    import atlas.agent.run_phases as run_phases

    def _boom(*args, **kwargs):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(
        "atlas.engine.state.atlas_state.SessionDB", _boom, raising=False,
    )
    report = asyncio.run(run_phases._idle_maintenance_callback()())
    assert report["skipped"] is True
    assert "database is locked" in report["error"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_kernel_slot_runs_the_producer_while_public_state_stays_idle(tmp_path):
    """The kernel's runMaintenance slot accepts the producer; active runs stay 0."""
    kernel = AtlasKernel(data_dir=tmp_path)
    callback = _idle_maintenance_callback()

    ran = await kernel.runMaintenance(callback)

    assert ran is True
    assert kernel._active_runs == 0
    assert kernel._maintenance_active is False
