"""Per-Atlas-lifespan MemoryOS child-process supervision.

Atlas and MemoryOS stay separate Python environments; readiness is established
only through the MemoryOS HTTP health contract.  A lifecycle instance stops
only the process it created itself.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections import deque
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

DEFAULT_SERVICE_DIR = Path(r"D:\MemoryOS")
DEFAULT_SERVICE_URL = "http://127.0.0.1:8099"
STARTUP_TIMEOUT_SECONDS = 12.0
HEALTH_TIMEOUT_SECONDS = 0.5
HEALTH_POLL_SECONDS = 0.2
SHUTDOWN_TIMEOUT_SECONDS = 4.0
CAPTURED_OUTPUT_BYTES = 12_000

_HealthProbe = Callable[[str], Awaitable[bool]]
_ProcessFactory = Callable[..., Awaitable[asyncio.subprocess.Process]]


class MemoryOSServiceLifecycle:
    """Start MemoryOS when enabled, and own only the child started here."""

    def __init__(
        self,
        config: Any,
        *,
        health_probe: _HealthProbe | None = None,
        process_factory: _ProcessFactory | None = None,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        startup_timeout: float = STARTUP_TIMEOUT_SECONDS,
    ) -> None:
        self._config = config
        self._health_probe = health_probe or self._probe_memoryos
        self._process_factory = process_factory or asyncio.create_subprocess_exec
        self._sleep = sleep
        self._monotonic = monotonic
        self._startup_timeout = startup_timeout
        self._process: asyncio.subprocess.Process | None = None
        self._owns_process = False
        self._start_task: asyncio.Task[Any] | None = None
        self._output_task: asyncio.Task[None] | None = None
        self._output_chunks: deque[bytes] = deque()
        self._output_size = 0
        self.state = "disabled"
        self.last_error: str | None = None

    @property
    def enabled(self) -> bool:
        return bool(self._config.get("memory.unified.enabled", False))

    @property
    def service_url(self) -> str:
        return str(self._config.get("memory.unified.service_url") or DEFAULT_SERVICE_URL)

    @property
    def health_url(self) -> str:
        return f"{self.service_url.rstrip('/')}/v1/health"

    @property
    def service_dir(self) -> Path:
        configured = self._config.get("memory.unified.service_dir")
        return Path(str(configured or DEFAULT_SERVICE_DIR)).expanduser().resolve()

    @property
    def owned_process(self) -> asyncio.subprocess.Process | None:
        """Expose ownership for lifecycle tests and diagnostics."""
        return self._process if self._owns_process else None

    def note_http_ready(self) -> None:
        """A successful service request proves an externally recovered service."""
        self.state = "ready"
        self.last_error = None

    async def _probe_memoryos(self, url: str) -> bool:
        """A generic open port is insufficient; require the unified MemoryOS API."""
        root_url = url.removesuffix("/v1/health") + "/"
        hostname = urlsplit(url).hostname
        trust_env = hostname not in {"127.0.0.1", "localhost", "::1"}
        try:
            async with httpx.AsyncClient(
                timeout=HEALTH_TIMEOUT_SECONDS, trust_env=trust_env) as client:
                root_response, health_response, unified_status = await asyncio.gather(
                    client.get(root_url), client.get(url),
                    client.get(root_url + "v1/unified/status"))
        except (httpx.HTTPError, OSError):
            return False
        if not root_response.is_success or not health_response.is_success:
            return False
        try:
            identity = root_response.json()
            health = health_response.json()
        except ValueError:
            return False
        if not isinstance(identity, dict) or not isinstance(health, dict):
            return False
        return (
            identity.get("service") == "MemoryOS Service"
            and str(health.get("status", "")).casefold() in {"ok", "healthy"}
            and (unified_status.is_success or unified_status.status_code == 401)
        )

    def _launch_command(self) -> tuple[list[str], Path]:
        parts = urlsplit(self.service_url)
        if parts.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise RuntimeError("automatic MemoryOS launch requires a loopback service_url")
        if parts.scheme != "http":
            raise RuntimeError("automatic MemoryOS launch requires an http service_url")
        if parts.path not in {"", "/"}:
            raise RuntimeError("automatic MemoryOS launch requires a root service_url path")
        port = parts.port or (443 if parts.scheme == "https" else 80)

        service_dir = self.service_dir / "service"
        app_path = service_dir / "app.py"
        python = (service_dir / ".venv" / "Scripts" / "python.exe"
                  if os.name == "nt" else service_dir / ".venv" / "bin" / "python")
        if not app_path.is_file():
            raise FileNotFoundError(f"MemoryOS service app not found: {app_path}")
        if not python.is_file():
            raise FileNotFoundError(f"MemoryOS service Python not found: {python}")
        return [str(python), "-m", "uvicorn", "app:app", "--host", parts.hostname or "127.0.0.1",
                "--port", str(port)], service_dir

    async def start(self) -> None:
        """Track the deferred startup task so shutdown can cancel it before stop."""
        task = asyncio.current_task()
        if task is not None:
            self._start_task = task
        try:
            await self._start()
        finally:
            if self._start_task is task:
                self._start_task = None

    async def _start(self) -> None:
        """Probe, launch if needed, and wait only on the deferred-startup path."""
        if not self.enabled:
            self.state = "disabled"
            self.last_error = None
            return

        self.state = "starting"
        self.last_error = None
        if await self._health_probe(self.health_url):
            self.state = "ready"
            return

        try:
            command, cwd = self._launch_command()
            env = os.environ.copy()
            self._output_chunks.clear()
            self._output_size = 0
            self._process = await self._process_factory(
                *command,
                cwd=str(cwd),
                env=env,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            self._owns_process = True
            output = getattr(self._process, "stdout", None)
            if output is not None:
                self._output_task = asyncio.create_task(
                    self._capture_child_output(output), name="memoryos-child-output")
            deadline = self._monotonic() + self._startup_timeout
            while self._monotonic() < deadline:
                if self._process.returncode is not None:
                    raise RuntimeError(
                        f"MemoryOS child exited during startup ({self._process.returncode})")
                if await self._health_probe(self.health_url):
                    self.state = "ready"
                    return
                await self._sleep(HEALTH_POLL_SECONDS)
            raise TimeoutError(
                f"MemoryOS did not pass /v1/health within {self._startup_timeout:g}s")
        except Exception as exc:
            self.state = "offline"
            output = self._captured_child_output()
            self.last_error = f"{exc}; child output: {output}" if output else str(exc)
            raise

    async def _capture_child_output(self, stream: Any) -> None:
        while True:
            chunk = await stream.read(2048)
            if not chunk:
                return
            self._output_chunks.append(chunk)
            self._output_size += len(chunk)
            while self._output_size > CAPTURED_OUTPUT_BYTES and self._output_chunks:
                removed = self._output_chunks.popleft()
                self._output_size -= len(removed)

    def _captured_child_output(self) -> str:
        return b"".join(self._output_chunks).decode("utf-8", errors="replace").strip()

    async def stop(self) -> None:
        """Terminate and reap only the direct child created by this instance."""
        startup = self._start_task
        current = asyncio.current_task()
        if startup is not None and startup is not current and not startup.done():
            startup.cancel()
            await asyncio.gather(startup, return_exceptions=True)
        process = self._process
        if not self._owns_process or process is None:
            self.state = "stopped" if self.state != "disabled" else "disabled"
            return
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=SHUTDOWN_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        output_task = self._output_task
        if output_task is not None:
            await asyncio.gather(output_task, return_exceptions=True)
            self._output_task = None
        self._process = None
        self._owns_process = False
        self.state = "stopped"

