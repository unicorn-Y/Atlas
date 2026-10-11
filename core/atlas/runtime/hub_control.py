"""Control-plane helpers for the background Hub.

Shared by the FastAPI server endpoints and the CLI: read the control file
written at hub start, probe health, spawn/stop the detached process, and
proxy task CRUD to the hub's localhost API.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from atlas.config import get_config

import logging

logger = logging.getLogger(__name__)

DEFAULT_PORT = 8793


def control_file() -> Path:
    return get_config().db_path.parent / "hub.json"


def read_control() -> dict[str, Any]:
    try:
        data = json.loads(control_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def hub_port() -> int:
    info = read_control()
    try:
        return int(info.get("port") or os.environ.get("ATLAS_HUB_PORT") or DEFAULT_PORT)
    except (TypeError, ValueError):
        return DEFAULT_PORT


async def _request(method: str, path: str, port: int | None = None) -> dict[str, Any]:
    # Loopback only: never route through a system proxy, and fail fast when nothing listens
    # (Windows retries a refused connect for ~2 s, which stalled every status poll).
    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=0.5), trust_env=False) as client:
        response = await client.request(method, f"http://127.0.0.1:{port or hub_port()}{path}")
        response.raise_for_status()
        return response.json()


async def health(port: int | None = None) -> dict[str, Any] | None:
    try:
        probe = await _request("GET", "/health", port)
    except Exception:
        return None
    # The Hub identifies itself with role="hub". A foreign service squatting on the port
    # (e.g. an OpenAI-compatible relay that also answers {"status":"ok"} on /health) must
    # not be mistaken for a running Hub — otherwise start() reports a phantom success and
    # stop() fires POST /shutdown at an unrelated process.
    return probe if probe.get("role") == "hub" else None


async def status() -> dict[str, Any]:
    port = hub_port()
    probe = await health(port)
    result: dict[str, Any] = {"running": probe is not None, "port": port}
    if probe is not None:
        try:
            detail = await _request("GET", "/status", port)
            result.update({
                "scheduler_running": detail.get("scheduler_running"),
                "task_count": detail.get("task_count"),
                "observability": detail.get("observability", {}),
            })
        except Exception:
            logger.debug("atlas.runtime.hub_control: ignored error", exc_info=True)
    return result


async def start(timeout: float = 30.0) -> dict[str, Any]:
    probe = await health()
    if probe is not None:
        return {**(await status()), "spawned": False}
    port = hub_port()
    env = {**os.environ, "ATLAS_HUB_PORT": str(port)}
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    process = subprocess.Popen(
        [sys.executable, "-m", "atlas.runtime.hub"],
        env=env, creationflags=flags, cwd=os.getcwd(),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if await health(port) is not None:
            control_file().parent.mkdir(parents=True, exist_ok=True)
            control_file().write_text(
                json.dumps({"pid": process.pid, "port": port}), encoding="utf-8",
            )
            return {**(await status()), "spawned": True, "pid": process.pid}
        if process.poll() is not None:
            return {"running": False, "port": port, "spawned": False,
                    "error": f"hub process exited with {process.returncode}"}
        await asyncio.sleep(0.5)
    return {"running": False, "port": port, "spawned": False, "error": "hub not healthy in time"}


async def stop() -> dict[str, Any]:
    if await health() is None:
        control_file().unlink(missing_ok=True)
        return {"running": False, "stopped": False}
    try:
        await _request("POST", "/shutdown")
    except Exception:
        logger.debug("atlas.runtime.hub_control: ignored error", exc_info=True)
    control_file().unlink(missing_ok=True)
    return {"running": False, "stopped": True}


async def list_tasks() -> list[dict[str, Any]]:
    return (await _request("GET", "/tasks")).get("tasks", [])


async def create_task(payload: dict[str, Any]) -> dict[str, Any]:
    return await _request("POST", "/tasks", json=payload)


async def run_task(task_id: str) -> dict[str, Any]:
    return await _request("POST", f"/tasks/{task_id}/run")


async def delete_task(task_id: str) -> dict[str, Any]:
    return await _request("DELETE", f"/tasks/{task_id}")
