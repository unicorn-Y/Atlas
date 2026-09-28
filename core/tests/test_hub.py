"""Background Hub smoke coverage: real subprocess, real scheduler, clean shutdown."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from atlas.runtime.hub import create_hub_app

CORE_DIR = Path(__file__).resolve().parents[1]


async def test_hub_app_endpoints_around_a_scheduler(tmp_path: Path) -> None:
    from atlas.scheduler import AtlasScheduler

    calls: list[tuple[str, str]] = []

    async def callback(task_id: str, message: str) -> None:
        calls.append((task_id, message))

    scheduler = AtlasScheduler(
        agent_callback=callback, schedules_path=tmp_path / "hub-schedules.toml",
    )
    app = create_hub_app(scheduler)

    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://hub") as client:
        health = (await client.get("/health")).json()
        assert health == {"status": "ok", "role": "hub"}

        created = (await client.post("/tasks", json={
            "id": "e2e-hub-check", "name": "E2E hub check",
            "message": "report readiness", "trigger_type": "interval",
            "trigger_args": {"hours": 1},
        })).json()
        assert created["id"] == "e2e-hub-check"
        assert created["action"] == "agent:report readiness"

        tasks = (await client.get("/tasks")).json()
        assert [t["id"] for t in tasks["tasks"]] == ["e2e-hub-check"]

        triggered = (await client.post("/tasks/e2e-hub-check/run")).json()
        assert triggered["status"] == "triggered"

        deleted = (await client.delete("/tasks/e2e-hub-check")).json()
        assert deleted["status"] == "ok"

        missing = await client.delete("/tasks/e2e-hub-check")
        assert missing.status_code == 404


@pytest.mark.skipif(os.name != "nt", reason="hub smoke tuned for this Windows host")
def test_hub_process_starts_serves_and_shuts_down(tmp_path: Path) -> None:
    port = 18791
    env = {
        **os.environ,
        "ATLAS_DATA_DIR": str(tmp_path),
        "ATLAS_HUB_PORT": str(port),
        "ATLAS_P18X_SKIP_ENV": "1",
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "atlas.runtime.hub"],
        cwd=str(CORE_DIR), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 90
        healthy = False
        while time.monotonic() < deadline:
            if process.poll() is not None:
                pytest.fail("hub process exited before becoming healthy")
            try:
                if httpx.get(
                    f"http://127.0.0.1:{port}/health", timeout=2.0,
                ).json().get("status") == "ok":
                    healthy = True
                    break
            except Exception:
                time.sleep(0.5)
        assert healthy, "hub never became healthy"

        created = httpx.post(
            f"http://127.0.0.1:{port}/tasks",
            json={
                "id": "smoke-hub-task", "name": "smoke",
                "message": "say READY", "trigger_type": "interval",
                "trigger_args": {"hours": 1},
            },
            timeout=5.0,
        )
        assert created.status_code == 200, created.text
        assert created.json()["action"] == "agent:say READY"

        status_body = httpx.get(f"http://127.0.0.1:{port}/status", timeout=5.0).json()
        assert status_body["scheduler_running"] is True
        assert status_body["task_count"] == 1

        assert httpx.post(
            f"http://127.0.0.1:{port}/shutdown", timeout=5.0,
        ).json()["status"] == "shutting_down"
        process.wait(timeout=30)
        assert process.poll() == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
