# Ported from openai/codex@806d9732c974bc8a51b8317c1bd8985544fe627c: codex-rs/core/src/unified_exec/process_manager.rs (Apache-2.0)
# Ported from openai/codex@806d9732c974bc8a51b8317c1bd8985544fe627c: codex-rs/core/src/unified_exec/head_tail_buffer.rs (Apache-2.0)
# Ported from zai-org/ZCode@29628c9acdb81b703bbd4080c207a0e7ce5e276ede: apps/zcode-cli/packages/core/src/tool/bash-timeout-policy.ts (Apache-2.0)
# SPDX-License-Identifier: Apache-2.0
"""Unified handles and durable bounded output for the existing local executor.

Dispatch must call the existing orchestrator's permission-checked local execution
route. This module neither spawns subprocesses nor creates another permission
policy. The native executor still owns Windows shells, PTY and process trees.
"""
from __future__ import annotations

import asyncio
import math
import os
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_BASH_TIMEOUT_MS = 120_000
DEFAULT_BASH_MAX_TIMEOUT_MS = 600_000


class HeadTailBuffer:
    """Codex stable 50% prefix and rolling 50% suffix, measured in bytes."""
    def __init__(self, max_bytes: int = 10_000) -> None:
        self.max_bytes = max(0, int(max_bytes))
        self.head = bytearray()
        self.tail = bytearray()
        self.omitted_bytes = 0

    def push_chunk(self, chunk: bytes) -> None:
        take = min(len(chunk), self.max_bytes // 2 - len(self.head))
        self.head.extend(chunk[:take])
        self.tail.extend(chunk[take:])
        excess = max(0, len(self.tail) - (self.max_bytes - self.max_bytes // 2))
        if excess:
            del self.tail[:excess]
            self.omitted_bytes += excess

    def text(self) -> str:
        marker = f"\n... {self.omitted_bytes} bytes omitted; see full output file ...\n".encode() if self.omitted_bytes else b""
        return (bytes(self.head) + marker + bytes(self.tail)).decode("utf-8", errors="replace")


def command_timeout(command: str, requested: Any = None) -> float:
    def positive_env(name: str, default: int) -> int:
        try:
            value = int(os.environ.get(name, ""))
            return value if value > 0 else default
        except ValueError:
            return default
    default_ms = positive_env("BASH_DEFAULT_TIMEOUT_MS", DEFAULT_BASH_TIMEOUT_MS)
    max_ms = max(default_ms, positive_env("BASH_MAX_TIMEOUT_MS", DEFAULT_BASH_MAX_TIMEOUT_MS))
    # Atlas adaptation: installs/builds have the upstream maximum; cheap reads
    # use a shorter default. Explicit caller timeouts always take precedence.
    if requested is None:
        if re.search(r"\b(install|build|compile|test|pytest|cargo|pip)\b", command, re.I):
            requested = max_ms / 1000
        elif re.match(r"\s*(ls|dir|pwd|cat|type|rg|Get-Content|Get-ChildItem)\b", command, re.I):
            requested = min(30, default_ms / 1000)
        else:
            requested = default_ms / 1000
    if isinstance(requested, bool):
        raise ValueError("timeout must be positive seconds")
    seconds = float(requested)
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("timeout must be positive seconds")
    return min(seconds, max_ms / 1000)


@dataclass(slots=True)
class ExecHandle:
    execution_id: str
    output_path: Path
    buffer: HeadTailBuffer
    timeout: float
    started: float = field(default_factory=time.monotonic)
    offsets: dict[str, int] = field(default_factory=lambda: {"stdout": 0, "stderr": 0})
    outcome: str = "running"
    timed_out: bool = False
    exit_code: int | None = None
    watcher: asyncio.Task[Any] | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class ExecManager:
    def __init__(self, dispatch: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]],
                 *, output_dir: str | Path, run_id: str | None = None,
                 max_output_bytes: int = 10_000, local_runtime: Any = None) -> None:
        self.dispatch = dispatch
        self.output_dir = Path(output_dir)
        self.run_id = run_id
        self.max_output_bytes = max_output_bytes
        self.local_runtime = local_runtime
        self.handles: dict[str, ExecHandle] = {}

    async def start(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = dict(arguments)
        direct_process_start = args.get("action") == "start"
        command = str(args.get("command") or args.get("cmd") or args.get("executable") or "")
        timeout = command_timeout(command, args.get("timeout"))
        args["action"] = "start"
        args.setdefault("detached", True if direct_process_start else False)
        args.setdefault("keep_stdin", True)
        if "cmd" in args:
            args["command"] = args.pop("cmd")
        if "workdir" in args:
            args["cwd"] = args.pop("workdir")
        if "command" in args:
            args.setdefault("shell", "auto")
        result = await self.dispatch("local_process", args)
        if result.get("is_error"):
            return result
        data = result.get("data") or {}
        execution_id = str(data.get("execution_id") or "")
        if not execution_id:
            return {"is_error": True, "error": "Executor returned no process handle", "outcome": "unknown"}
        # Do not let externally supplied handle strings escape the output root.
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", execution_id)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"{safe_id}.log"
        path.touch(exist_ok=False)
        handle = ExecHandle(execution_id, path, HeadTailBuffer(self.max_output_bytes), timeout)
        self.handles[execution_id] = handle
        handle.watcher = asyncio.create_task(self._watch(handle))
        return await self.poll(execution_id)

    async def _capture(self, handle: ExecHandle) -> None:
        # Native logs are complete; read every chunk, never only native result tail.
        # Prefer original bytes over the model-facing text API: UTF-8 characters
        # can cross its 64KiB chunk boundary. This reads only already-authorized
        # process output, not workspace files or a second execution route.
        record = getattr(self.local_runtime, "_processes", {}).get(handle.execution_id)
        if record is not None:
            for stream in ("stdout", "stderr"):
                path = getattr(record, f"{stream}_path")
                with path.open("rb") as source, handle.output_path.open("ab") as output:
                    source.seek(handle.offsets[stream])
                    while chunk := source.read(65536):
                        output.write(chunk)
                        handle.buffer.push_chunk(chunk)
                        handle.offsets[stream] += len(chunk)
            return
        for stream in ("stdout", "stderr"):
            while True:
                result = await self.dispatch("local_process", {
                    "action": "read", "execution_id": handle.execution_id,
                    "stream": stream, "offset": handle.offsets[stream], "limit": 65536,
                })
                if result.get("is_error"):
                    raise RuntimeError(str(result.get("error") or result))
                data = result.get("data") or {}
                next_offset = int(data.get("next_offset", handle.offsets[stream]))
                if next_offset <= handle.offsets[stream]:
                    break
                chunk = str(data.get("text") or "").encode("utf-8")
                with handle.output_path.open("ab") as output:
                    output.write(chunk)
                handle.buffer.push_chunk(chunk)
                handle.offsets[stream] = next_offset
                if data.get("complete"):
                    break

    def _result(self, handle: ExecHandle) -> dict[str, Any]:
        data = {"execution_id": handle.execution_id, "state": handle.outcome,
                "outcome": handle.outcome, "exit_code": handle.exit_code,
                "timed_out": handle.timed_out, "output": handle.buffer.text(),
                "output_ref": str(handle.output_path.resolve()),
                "duration_seconds": round(time.monotonic() - handle.started, 3)}
        return {"data": data, "outcome": handle.outcome,
                "output_ref": data["output_ref"], "is_error": handle.outcome in {"failed", "unknown"},
                "content": [{"type": "text", "text": f"{data['output']}\nFull output: {data['output_ref']}\nProcess: {handle.execution_id} ({handle.outcome})"}]}

    async def poll(self, execution_id: str) -> dict[str, Any]:
        handle = self.handles[execution_id]
        async with handle.lock:
            result = await self.dispatch("local_process", {"action": "status", "execution_id": execution_id})
            if result.get("is_error"):
                return result
            await self._capture(handle)
            data = result.get("data") or {}
            handle.exit_code = data.get("exit_code")
            if handle.outcome == "running" and data.get("state") != "running":
                if data.get("state") == "cancelled":
                    handle.outcome = "unknown"
                else:
                    handle.outcome = "completed" if handle.exit_code == 0 else "failed"
            return self._result(handle)

    async def _watch(self, handle: ExecHandle) -> None:
        try:
            while handle.outcome == "running":
                await self.poll(handle.execution_id)
                if handle.outcome != "running":
                    break
                if time.monotonic() - handle.started >= handle.timeout:
                    handle.timed_out = True
                    await self.kill(handle.execution_id)
                    break
                await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            raise
        except Exception:
            handle.outcome = "unknown"
            # A failed output/poll watcher must not leave an untracked child alive.
            try:
                await self.dispatch("local_process", {"action": "cancel", "execution_id": handle.execution_id})
            except Exception:
                pass

    async def write_stdin(self, execution_id: str, data: str) -> dict[str, Any]:
        result = await self.dispatch("local_process", {"action": "write_stdin", "execution_id": execution_id, "data": data})
        return result if result.get("is_error") else await self.poll(execution_id)

    async def kill(self, execution_id: str) -> dict[str, Any]:
        handle = self.handles[execution_id]
        handle.outcome = "unknown"
        result = await self.dispatch("local_process", {"action": "cancel", "execution_id": execution_id})
        await self.poll(execution_id)
        return result if result.get("is_error") else self._result(handle)

    async def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        args = dict(arguments)
        if name == "local_process" and args.get("action") == "start":
            return await self.start(args)
        if name in {"terminal", "local_shell", "local_exec", "exec_command"}:
            result = await self.start(args)
            if result.get("is_error"):
                return result
            execution_id = result["data"]["execution_id"]
            if args.get("background") or args.get("detached"):
                return result
            try:
                await asyncio.shield(self.handles[execution_id].watcher)
            except asyncio.CancelledError:
                await self.kill(execution_id)
                raise
            return await self.poll(execution_id)
        execution_id = str(args.get("execution_id") or args.get("session_id") or "")
        action = args.get("action", "poll")
        if name == "local_process" and execution_id not in self.handles:
            return await self.dispatch(name, args)
        if action in {"poll", "status"}:
            return await self.poll(execution_id)
        if action in {"write", "write_stdin"}:
            return await self.write_stdin(execution_id, str(args.get("data") or args.get("chars") or ""))
        if action in {"kill", "cancel"}:
            return await self.kill(execution_id)
        if action in {"read", "log", "wait"}:
            native_action = "read" if action == "log" else action
            result = await self.dispatch("local_process", {**args, "action": native_action})
            if not result.get("is_error") and execution_id in self.handles:
                handle = self.handles[execution_id]
                async with handle.lock:
                    await self._capture(handle)
                data = result.get("data")
                if isinstance(data, dict):
                    data.setdefault("output_ref", str(handle.output_path.resolve()))
            return result
        return await self.dispatch("local_process", args)

    async def shutdown(self) -> None:
        for handle in self.handles.values():
            if handle.outcome == "running":
                await self.kill(handle.execution_id)
            if handle.watcher is not None:
                handle.watcher.cancel()
        await asyncio.gather(*(h.watcher for h in self.handles.values() if h.watcher is not None), return_exceptions=True)
