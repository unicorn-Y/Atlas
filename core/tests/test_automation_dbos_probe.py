"""DBOS 3.0.0 capability probe for the automation engine (lane W4).

This file decides the test-lane lifecycle strategy:

1. Can this process create + launch + destroy the process-wide DBOS singleton
   more than once?  If yes, tests may use a module-scoped DBOS fixture; if no,
   all tests in a module must share a single DBOS instance.
2. Does the DBOS 3.0.0 installed here actually support every API the
   AutomationEngine relies on (dynamic schedules, queues with deduplication,
   attribute-filtered run history, delayed enqueue, fixed-id start)?

Run: cd core && python -m pytest tests/test_automation_dbos_probe.py -q
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("dbos")


def _dbos_config(tmp_path: Path) -> dict:
    return {
        "name": "atlas-automation-probe",
        "system_database_url": f"sqlite:///{(tmp_path / 'dbos.sqlite').as_posix()}",
        "db_engine_kwargs": {"connect_args": {"timeout": 30}},
        "scheduler_polling_interval_sec": 1.0,
    }


async def _wait_until(predicate, timeout: float = 15.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.2)
    return predicate()


def test_dbos_multiple_init_launch_destroy_cycles(tmp_path: Path) -> None:
    """Probe: two full DBOS lifecycles in one process must both work."""
    from dbos import DBOS

    results: list[bool] = []
    for cycle in range(2):
        (tmp_path / f"cycle{cycle}").mkdir(parents=True, exist_ok=True)
        DBOS(config=_dbos_config(tmp_path / f"cycle{cycle}"))
        DBOS.launch()

        @DBOS.workflow(name="_probe_wf")
        async def _probe_wf(payload: dict) -> dict:
            return {"seen": payload.get("v")}

        handle = DBOS.start_workflow(_probe_wf, {"v": cycle})
        results.append(handle.get_result() == {"seen": cycle})
        DBOS.destroy(destroy_registry=True)
    assert results == [True, True]


async def test_dbos_automation_surface(tmp_path: Path) -> None:
    """Probe every DBOS API the AutomationEngine uses, on one live instance."""
    from dbos import DBOS, EnqueueOptions, SetWorkflowID

    db_dir = tmp_path / "surface"
    db_dir.mkdir(parents=True, exist_ok=True)
    DBOS(config=_dbos_config(db_dir))
    DBOS.launch()

    calls: list[dict] = []

    try:
        # -- queue registered post-launch (engine receives a launched DBOS);
        #      async context => the check_async-guarded calls need *_async --
        await DBOS.register_queue_async("atlas-automation", global_concurrency=2)

        # -- workflows defined as closures post-launch (dbos_backend pattern) --
        @DBOS.step(name="_probe_step")
        async def _probe_step(payload: dict) -> dict:
            await asyncio.sleep(0.01)
            calls.append(dict(payload))
            return {"ok": True, "echo": payload}

        @DBOS.workflow(name="_probe_run")
        async def _probe_run(automation_id: str, trigger: str = "manual") -> dict:
            return await _probe_step({"automation_id": automation_id, "trigger": trigger})

        @DBOS.workflow(name="_probe_scheduled")
        async def _probe_scheduled(scheduled_time: datetime, context: dict | None = None) -> dict:
            return await _probe_step({"scheduled": scheduled_time.isoformat(), **(context or {})})

        @DBOS.workflow(name="_probe_loop")
        async def _probe_loop(automation_id: str) -> dict:
            for _ in range(2):
                await DBOS.sleep_async(0.05)
            return {"loop_done": automation_id}

        # -- enqueue with deduplication_id + return-existing (no duplicate fire) --
        handle = await DBOS.enqueue_workflow_with_options_async(
            EnqueueOptions(
                workflow_name="_probe_run",
                queue_name="atlas-automation",
                workflow_id="atlas-auto-run-probe-1",
                deduplication_id="atlas-auto-run-probe",
                duplication_policy="return-existing",
                attributes={"automation_id": "probe"},
            ),
            "probe",
            "manual",
        )
        assert await handle.get_result() == {
            "ok": True,
            "echo": {"automation_id": "probe", "trigger": "manual"},
        }
        status = await DBOS.get_workflow_status_async("atlas-auto-run-probe-1")
        assert status is not None and status.status == "SUCCESS"
        assert status.attributes == {"automation_id": "probe"}

        # -- attribute-filtered run history (contains semantics) --
        await DBOS.enqueue_workflow_with_options_async(
            EnqueueOptions(
                workflow_name="_probe_run",
                queue_name="atlas-automation",
                workflow_id="atlas-auto-run-probe-2",
                attributes={"automation_id": "probe", "trigger": "event"},
            ),
            "probe",
            "event",
        )
        assert await DBOS.get_result_async("atlas-auto-run-probe-2") is not None
        # attributes filtering is NOT supported on SQLite (dbos 3.0.0 raises);
        # run history therefore filters by workflow_id prefix instead.
        runs = await DBOS.list_workflows_async(workflow_id_prefix="atlas-auto-run-probe")
        assert {r.workflow_id for r in runs} >= {
            "atlas-auto-run-probe-1",
            "atlas-auto-run-probe-2",
        }
        with pytest.raises(Exception, match="attributes"):
            await DBOS.list_workflows_async(attributes={"automation_id": "probe"})

        # -- delayed enqueue (date trigger): stays DELAYED, dedup id held --
        delayed = await DBOS.enqueue_workflow_with_options_async(
            EnqueueOptions(
                workflow_name="_probe_run",
                queue_name="atlas-automation",
                workflow_id="atlas-auto-run-probe-date",
                deduplication_id="atlas-auto-run-probe-date",
                delay_seconds=0.2,
                attributes={"automation_id": "probe", "trigger": "date"},
            ),
            "probe",
            "date",
        )
        pre = await DBOS.get_workflow_status_async("atlas-auto-run-probe-date")
        assert pre is not None and pre.status in {"DELAYED", "ENQUEUED", "PENDING"}
        assert await delayed.get_result() == {
            "ok": True,
            "echo": {"automation_id": "probe", "trigger": "date"},
        }

        # -- fixed-id start is exactly-once (interval loop basis) --
        with SetWorkflowID("atlas-auto-interval-probe"):
            first = await DBOS.start_workflow_async(_probe_loop, "probe")
        with SetWorkflowID("atlas-auto-interval-probe"):
            second = await DBOS.start_workflow_async(_probe_loop, "probe")
        assert first.workflow_id == second.workflow_id == "atlas-auto-interval-probe"
        assert await second.get_result() == {"loop_done": "probe"}

        # -- dynamic cron schedule: create / get / duplicate-name / fire / delete --
        DBOS.create_schedule(
            schedule_name="atlas-auto-probe",
            workflow_fn=_probe_scheduled,
            schedule="* * * * *",
            context={"automation_id": "probe"},
            automatic_backfill=False,
            queue_name="atlas-automation",
        )
        schedule = DBOS.get_schedule("atlas-auto-probe")
        assert schedule is not None
        assert schedule["schedule"] == "* * * * *"
        assert schedule["status"] == "ACTIVE"

        with pytest.raises(Exception):
            DBOS.create_schedule(
                schedule_name="atlas-auto-probe",
                workflow_fn=_probe_scheduled,
                schedule="*/5 * * * *",
            )

        DBOS.pause_schedule("atlas-auto-probe")
        assert DBOS.get_schedule("atlas-auto-probe")["status"] == "PAUSED"
        DBOS.resume_schedule("atlas-auto-probe")

        # immediate one-shot fire (run receipt = the new workflow id)
        fired = DBOS.trigger_schedule("atlas-auto-probe")
        assert fired.workflow_id
        assert await DBOS.get_result_async(fired.workflow_id) is not None

        cron_runs = await DBOS.list_workflows_async(schedule_name="atlas-auto-probe")
        assert cron_runs, "scheduled run must be recorded under schedule_name"

        DBOS.delete_schedule("atlas-auto-probe")
        assert DBOS.get_schedule("atlas-auto-probe") is None

        # -- cancel a running workflow --
        blocked = asyncio.Event()

        @DBOS.step(name="_blocking_step")
        async def _blocking_step() -> bool:
            blocked.set()
            await asyncio.sleep(30)
            return True

        @DBOS.workflow(name="_slow_run")
        async def _slow_run() -> bool:
            return await _blocking_step()

        slow = await DBOS.start_workflow_async(_slow_run)
        await _wait_until(blocked.is_set)
        await DBOS.cancel_workflow_async(slow.workflow_id)

        async def _cancelled() -> bool:
            status = await DBOS.get_workflow_status_async(slow.workflow_id)
            return status is not None and status.status == "CANCELLED"

        assert await _wait_until(_cancelled)
    finally:
        DBOS.destroy(destroy_registry=True)
