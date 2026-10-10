# Ported from openai/codex@6c0c6759d0617d7670826b61aca0a931bbb6db1f: codex-rs/core/src/unified_exec/ (Apache-2.0)
# Ported from zai-org/ZCode@aac4755666d09fdcd70272fcf063c077a639015f: apps/zcode-cli/packages/core/src/tool/bash-timeout-policy.ts (Apache-2.0)
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
DEFAULT_MAX_OUTPUT_BYTES = 1024 * 1024


class HeadTailBuffer:
    """Codex stable 50% prefix and rolling 50% suffix, measured in bytes."""
    def __init__(self, max_bytes: int = DEFAULT_MAX_OUTPUT_BYTES) -> None:
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
        marker = f"\n... {self.omitted_bytes} bytes omitted ...\n".encode() if self.omitted_bytes else b""
        return (bytes(self.head) + marker + bytes(self.tail)).decode("utf-8", errors="replace")


def command_timeout(command: str, requested: Any = None) -> float:
    def positive_env(name: str, default: int) -> int:
        try:
            match = re.match(r"\s*([+-]?\d+)", os.environ.get(name, ""))
            value = int(match.group(1)) if match else 0
            return value if value > 0 else default
        except (TypeError, ValueError):
            return default
    default_ms = positive_env("BASH_DEFAULT_TIMEOUT_MS", DEFAULT_BASH_TIMEOUT_MS)
    max_ms = max(default_ms, positive_env("BASH_MAX_TIMEOUT_MS", DEFAULT_BASH_MAX_TIMEOUT_MS))
    # Atlas local-process APIs express timeouts in seconds; ZCode's equivalent
    # Bash request uses milliseconds. A zero request follows its `timeout ||`
    # defaulting rule.
    if isinstance(requested, bool):
        raise ValueError("timeout must be positive seconds")
    if requested is None:
        requested = default_ms / 1000
    seconds = float(requested)
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("timeout must be positive seconds")
    if seconds == 0:
        seconds = default_ms / 1000
    return min(seconds, max_ms / 1000)


@dataclass(slots=True)
class ExecHandle:
    execution_id: str
    output_path: Path
    buffer: HeadTailBuffer
    timeout: float | None
    detached: bool = False
    started: float = field(default_factory=time.monotonic)
    offsets: dict[str, int] = field(default_factory=lambda: {"stdout": 0, "stderr": 0})
    outcome: str = "running"
    timed_out: bool = False
    exit_code: int | None = None
    watcher: asyncio.Task[Any] | None = None
    interaction_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class ExecManager:
    def __init__(self, dispatch: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]],
                 *, output_dir: str | Path, run_id: str | None = None,
                 max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES, local_runtime: Any = None) -> None:
        self.dispatch = dispatch
        self.output_dir = Path(output_dir)
        self.run_id = run_id
        self.max_output_bytes = max_output_bytes
        self.local_runtime = local_runtime
        self.handles: dict[str, ExecHandle] = {}

    async def start(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = dict(arguments)
        direct_process_start = args.get("action") == "start"
        if args.get("background"):
            args["detached"] = True
        args.pop("background", None)
        command = str(args.get("command") or args.get("cmd") or args.get("executable") or "")
        # A resumable start returns a process handle; its default yield/poll
        # window is not a lifetime timeout. Keep an explicitly requested Atlas
        # timeout for compatibility, while detached starts have no implicit cap.
        has_explicit_timeout = args.get("timeout") is not None
        timeout = (
            command_timeout(command, args.get("timeout"))
            if has_explicit_timeout or not (direct_process_start or args.get("detached"))
            else None
        )
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
        handle = ExecHandle(
            execution_id, path, HeadTailBuffer(self.max_output_bytes), timeout,
            detached=bool(args.get("detached")),
        )
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
                "backgrounded": handle.detached,
                "output_ref": str(handle.output_path.resolve()),
                "duration_seconds": round(time.monotonic() - handle.started, 3)}
        return {"data": data, "outcome": handle.outcome,
                "output_ref": data["output_ref"], "is_error": handle.outcome in {"failed", "unknown"},
                "content": [{"type": "text", "text": f"{data['output']}\nFull output: {data['output_ref']}\nProcess: {handle.execution_id} ({handle.outcome})"}]}

    async def poll(self, execution_id: str) -> dict[str, Any]:
        handle = self.handles[execution_id]
        async with handle.interaction_lock:
            return await self._poll_locked(handle)

    async def _poll_locked(self, handle: ExecHandle) -> dict[str, Any]:
        result = await self.dispatch("local_process", {
            "action": "status", "execution_id": handle.execution_id,
        })
        if result.get("is_error"):
            return result
        await self._capture(handle)
        data = result.get("data") or {}
        if data.get("exit_code") is not None:
            handle.exit_code = data.get("exit_code")
        if data.get("timed_out"):
            handle.timed_out = True
        if handle.outcome == "running" and data.get("state") != "running":
            if handle.timed_out:
                handle.outcome = "timed_out"
                handle.exit_code = 124
            elif data.get("state") == "cancelled":
                handle.outcome = "cancelled"
            elif data.get("state") == "failed":
                handle.outcome = "failed"
            else:
                handle.outcome = "completed" if handle.exit_code == 0 else "failed"
        return self._result(handle)

    async def _watch(self, handle: ExecHandle) -> None:
        try:
            while handle.outcome == "running":
                await self.poll(handle.execution_id)
                if handle.outcome != "running":
                    break
                if handle.timeout is not None and time.monotonic() - handle.started >= handle.timeout:
                    handle.timed_out = True
                    await self._timeout(handle)
                    break
                await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            raise
        except Exception:
            if handle.outcome == "running":
                handle.outcome = "unknown"
            # A failed output/poll watcher must not leave an untracked child alive.
            try:
                await self.dispatch("local_process", {"action": "cancel", "execution_id": handle.execution_id})
            except Exception:
                pass

    async def write_stdin(self, execution_id: str, data: str) -> dict[str, Any]:
        handle = self.handles[execution_id]
        async with handle.interaction_lock:
            result = await self.dispatch("local_process", {
                "action": "write_stdin", "execution_id": execution_id, "data": data,
            })
            if result.get("is_error"):
                # The process can exit between the caller's last poll and this
                # write. Preserve its final output/status when that race occurs.
                status = await self.dispatch("local_process", {
                    "action": "status", "execution_id": execution_id,
                })
                if status.get("is_error") or (status.get("data") or {}).get("state") == "running":
                    return result
            return await self._poll_locked(handle)

    async def _timeout(self, handle: ExecHandle) -> dict[str, Any]:
        async with handle.interaction_lock:
            if handle.outcome != "running":
                return self._result(handle)
            result = await self.dispatch("local_process", {
                "action": "cancel", "execution_id": handle.execution_id,
            })
            if result.get("is_error"):
                handle.outcome = "unknown"
                return result
            handle.timed_out = True
            handle.outcome = "timed_out"
            await self._poll_locked(handle)
            # Match Codex's timeout exit status even when the native backend
            # reports a platform-specific signal/termination code.
            handle.exit_code = 124
            return self._result(handle)

    async def kill(self, execution_id: str) -> dict[str, Any]:
        handle = self.handles[execution_id]
        async with handle.interaction_lock:
            if handle.outcome != "running":
                return self._result(handle)
            result = await self.dispatch("local_process", {
                "action": "cancel", "execution_id": execution_id,
            })
            if result.get("is_error"):
                handle.outcome = "unknown"
                return result
            await self._poll_locked(handle)
            if handle.outcome == "running":
                handle.outcome = "cancelled"
            return self._result(handle)

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
                handle = self.handles[execution_id]
                if not handle.detached:
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
        if action in {"read", "log"}:
            native_action = "read" if action == "log" else action
            handle = self.handles.get(execution_id)
            if handle is None:
                return await self.dispatch("local_process", {**args, "action": native_action})
            async with handle.interaction_lock:
                result = await self.dispatch("local_process", {**args, "action": native_action})
                if result.get("is_error"):
                    return result
                await self._capture(handle)
                data = result.get("data")
                if isinstance(data, dict):
                    data.setdefault("output_ref", str(handle.output_path.resolve()))
            return result
        if action == "wait":
            return await self.dispatch("local_process", {**args, "action": action})
        return await self.dispatch("local_process", args)

    async def shutdown(self) -> None:
        for handle in self.handles.values():
            if handle.outcome == "running" and not handle.detached:
                await self.kill(handle.execution_id)
            if handle.watcher is not None and not handle.detached:
                handle.watcher.cancel()
        await asyncio.gather(*(
            h.watcher for h in self.handles.values()
            if h.watcher is not None and not h.detached
        ), return_exceptions=True)
