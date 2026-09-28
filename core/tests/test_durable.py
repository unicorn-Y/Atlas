"""DBOS durable backend coverage, including a real cross-process crash resume."""

from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from pathlib import Path

import pytest

from atlas.capabilities.durable.dbos_backend import DurableBackend, status

CORE_DIR = Path(__file__).resolve().parents[1]

CHILD_SCRIPT = f"""
import asyncio, sys
sys.path.insert(0, r"{str(CORE_DIR)}")
from atlas.capabilities.durable.dbos_backend import DurableBackend


async def main() -> None:
    db_path, marker = sys.argv[1], sys.argv[2]

    async def dispatcher(payload: dict) -> dict:
        Path = __import__("pathlib").Path
        Path(marker).write_text("started", encoding="utf-8")
        await asyncio.sleep(600)  # never completes; the process gets killed
        return {{}}

    backend = DurableBackend(db_path)
    backend.set_dispatcher(dispatcher, asyncio.get_running_loop())
    backend.start()
    await backend.run_agent_task({{"task_id": "goal-1", "message": "long task"}})


asyncio.run(main())
"""


async def test_status_probe_reports_dependency() -> None:
    probe = status()
    assert probe["available"] is True
    assert probe["error"] is None


async def test_start_requires_registered_dispatcher(tmp_path: Path) -> None:
    backend = DurableBackend(tmp_path / "dbos.sqlite")
    result = backend.start()
    assert result["started"] is False
    assert "dispatcher" in (result["start_error"] or "")
    with pytest.raises(RuntimeError, match="not started"):
        await backend.run_agent_task({"task_id": "x", "message": "y"})


async def test_durable_task_resumes_after_real_process_crash(tmp_path: Path) -> None:
    system_db = tmp_path / "dbos.sqlite"
    marker = tmp_path / "child-started.marker"

    # Phase A: a child "Atlas process" starts a durable task and dies mid-run.
    child = subprocess.Popen(
        [sys.executable, "-c", CHILD_SCRIPT, str(system_db), str(marker)],
        cwd=str(CORE_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline and not marker.exists():
            await asyncio.sleep(0.3)
        assert marker.exists(), "child process never started the durable task"
    finally:
        child.kill()
        child.wait(timeout=15)

    # Phase B: the restarted process recovers the RUNNING workflow.
    calls: list[dict] = []

    async def resumed_dispatcher(payload: dict) -> dict:
        calls.append(payload)
        return {"status": "completed", "payload": payload}

    backend = DurableBackend(system_db)
    backend.set_dispatcher(resumed_dispatcher, asyncio.get_running_loop())
    try:
        assert backend.start()["started"] is True
        deadline = asyncio.get_running_loop().time() + 30
        while asyncio.get_running_loop().time() < deadline and not calls:
            await asyncio.sleep(0.5)
        assert calls, "DBOS recovery did not re-run the crashed workflow"
        assert calls[0]["task_id"] == "goal-1"
        assert backend.status()["system_db_exists"] is True
    finally:
        backend.stop()
