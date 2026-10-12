from __future__ import annotations

import asyncio
import os
import socket
import subprocess
from pathlib import Path

import httpx
import pytest

from atlas.memory.service_lifecycle import MemoryOSServiceLifecycle


def _available_loopback_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.mark.asyncio
async def test_existing_real_memoryos_is_verified_over_http_and_not_owned(tmp_path: Path) -> None:
    service_root = Path(r"D:\MemoryOS")
    service_dir = service_root / "service"
    python = service_dir / ".venv" / "Scripts" / "python.exe"
    if os.name != "nt" or not python.is_file():
        pytest.skip("requires the isolated MemoryOS service venv on Windows")

    port = _available_loopback_port()
    isolated_data = tmp_path / "memoryos-data"
    isolated_data.mkdir()
    env = os.environ.copy()
    test_token = "atlas-memory-v1-lifecycle-test-token"
    env["MEMORYOS_DATA_ROOT"] = str(isolated_data)
    env["MEMORYOS_DB_PATH"] = str(isolated_data / "db" / "memoryos.sqlite3")
    env["MEMORYOS_INTERNAL_TOKEN"] = test_token
    process = subprocess.Popen(
        [str(python), "-m", "uvicorn", "app:app", "--host", "127.0.0.1",
         "--port", str(port)],
        cwd=service_dir,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    service_url = f"http://127.0.0.1:{port}"
    try:
        deadline = asyncio.get_running_loop().time() + 20
        async with httpx.AsyncClient(timeout=0.5) as client:
            while asyncio.get_running_loop().time() < deadline:
                if process.poll() is not None:
                    output = process.stdout.read(12000).decode("utf-8", errors="replace")
                    pytest.fail(f"isolated MemoryOS exited {process.returncode}: {output}")
                try:
                    root = await client.get(service_url + "/")
                    health = await client.get(service_url + "/v1/health")
                    if root.is_success and health.is_success:
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.1)
            else:
                pytest.fail("isolated MemoryOS did not become healthy over HTTP")

        lifecycle = MemoryOSServiceLifecycle({
            "memory.unified.enabled": True,
            "memory.unified.service_url": service_url,
            "memory.unified.service_dir": str(service_root),
        })
        assert await lifecycle._probe_memoryos(lifecycle.health_url), (
            f"root={root.json()} health={health.json()}"
        )
        await lifecycle.start()
        assert lifecycle.state == "ready"
        assert lifecycle.owned_process is None
        from atlas.memory.unified_client import UnifiedMemoryClient
        from atlas.memory.unified_facade import UnifiedMemoryFacade

        client = UnifiedMemoryClient(service_url, internal_token=test_token)
        try:
            status = await client.get_status()
            assert isinstance(status, dict)
            facade = UnifiedMemoryFacade({
                "memory.unified.enabled": True,
                "memory.unified.service_url": service_url,
                "memory.unified.internal_token": test_token,
            }, client)
            recall = await facade.recall_for_conversation("isolated lifecycle probe")
            assert recall["enabled"] is True
            assert isinstance(recall["read_id"], str)
        finally:
            await client.aclose()
        await lifecycle.stop()
        assert process.poll() is None, "stop must leave the pre-existing service alone"
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if process.stdout:
            process.stdout.close()


class _FakeChild:
    def __init__(self) -> None:
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    async def wait(self) -> int:
        return self.returncode or 0


@pytest.mark.asyncio
async def test_stop_cancels_unready_start_before_terminating_owned_child() -> None:
    probe_waiting = asyncio.Event()
    child = _FakeChild()
    probe_calls = 0

    async def probe(_url: str) -> bool:
        nonlocal probe_calls
        probe_calls += 1
        if probe_calls == 1:
            return False
        probe_waiting.set()
        await asyncio.Event().wait()

    async def spawn(*_args: object, **_kwargs: object) -> _FakeChild:
        return child

    lifecycle = MemoryOSServiceLifecycle(
        {"memory.unified.enabled": True},
        health_probe=probe,
        process_factory=spawn,  # type: ignore[arg-type]
    )
    startup = asyncio.create_task(lifecycle.start())
    await probe_waiting.wait()
    await lifecycle.stop()

    assert startup.cancelled()
    assert child.terminated
    assert lifecycle.owned_process is None


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [(200, True), (401, True), (403, False), (307, False), (500, False)],
)
@pytest.mark.asyncio
async def test_health_probe_requires_unified_route_success_or_auth_challenge(
    status_code: int, expected: bool, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(200, json={"service": "MemoryOS Service"})
        if request.url.path == "/v1/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/v1/unified/status":
            return httpx.Response(status_code, json={"status": "probe"})
        return httpx.Response(404)

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        "atlas.memory.service_lifecycle.httpx.AsyncClient",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(respond), **kwargs),
    )
    lifecycle = MemoryOSServiceLifecycle({"memory.unified.enabled": True})
    assert await lifecycle._probe_memoryos(
        "http://127.0.0.1:8099/v1/health") is expected


def test_ipv6_loopback_start_binds_the_configured_host(tmp_path: Path) -> None:
    service_root = tmp_path / "MemoryOS"
    service_dir = service_root / "service"
    service_dir.mkdir(parents=True)
    (service_dir / "app.py").write_text("app = None", encoding="utf-8")
    python = service_dir / ".venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"test executable marker")

    lifecycle = MemoryOSServiceLifecycle({
        "memory.unified.enabled": True,
        "memory.unified.service_url": "http://[::1]:9123",
        "memory.unified.service_dir": str(service_root),
    })
    command, _cwd = lifecycle._launch_command()
    assert command[command.index("--host") + 1] == "::1"


@pytest.mark.asyncio
async def test_readiness_probe_does_not_run_full_freshness_audit(monkeypatch) -> None:
    paths = []

    async def respond(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/":
            return httpx.Response(200, json={"service": "MemoryOS Service"})
        if request.url.path == "/v1/ready":
            return httpx.Response(200, json={"status": "ready"})
        if request.url.path == "/v1/unified/status":
            return httpx.Response(401)
        raise AssertionError("readiness must not perform a full freshness audit")

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        "atlas.memory.service_lifecycle.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    lifecycle = MemoryOSServiceLifecycle({"memory.unified.enabled": True})
    assert await lifecycle._probe_memoryos(lifecycle.health_url)
    assert "/v1/health" not in paths


@pytest.mark.asyncio
async def test_existing_warming_service_is_waited_for_without_competing_child(monkeypatch) -> None:
    probes = 0

    async def respond(request: httpx.Request) -> httpx.Response:
        nonlocal probes
        if request.url.path == "/":
            return httpx.Response(200, json={"service": "MemoryOS Service"})
        if request.url.path == "/v1/ready":
            probes += 1
            return httpx.Response(503 if probes == 1 else 200, json={"status": "ready"})
        return httpx.Response(401)

    async def forbidden_spawn(*args, **kwargs):
        raise AssertionError("must not start a second MemoryOS on an occupied port")

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        "atlas.memory.service_lifecycle.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    lifecycle = MemoryOSServiceLifecycle({"memory.unified.enabled": True}, process_factory=forbidden_spawn)
    await lifecycle.start()
    assert lifecycle.state == "ready"
    assert lifecycle.owned_process is None
    assert probes == 2
