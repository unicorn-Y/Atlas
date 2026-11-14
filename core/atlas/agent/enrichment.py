"""Optional Agent lifecycle, context, delegation, CodeAct, and review adapters."""

from __future__ import annotations

import asyncio
import ast
import contextlib
import json
import os
import secrets
import sys
import subprocess
import tempfile
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

from atlas.engine.tool_permissions import intersect_tool_allow
from atlas.agent.subagent_capacity import get_subagent_capacity
from atlas.agent.mailbox import AgentMailbox, MailMessage, normalize_address

log = structlog.get_logger()


def _codeact_json_value(value: Any) -> Any:
    """Return JSON-safe values without allowing lone surrogates across stdio."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="backslashreplace")
    if isinstance(value, str):
        return value.encode("utf-8", errors="backslashreplace").decode("utf-8")
    if isinstance(value, dict):
        return {_codeact_json_value(key): _codeact_json_value(item)
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_codeact_json_value(item) for item in value]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _codeact_json_value(str(value))

# Delegation lifecycle, bounded schema retry, and child-worktree cleanup follow
# NousResearch/hermes-agent at 330d9d6df9c7bffe125ba0ae64a0abc488a7d2c3
# (MIT), adapted to Atlas run callbacks and workspace permissions.


def _workspace_fingerprint(root: str) -> dict[str, str]:
    base = Path(root).resolve()
    excluded = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache"}
    result: dict[str, str] = {}
    for path in base.rglob("*"):
        if not path.is_file() or any(part in excluded for part in path.relative_to(base).parts):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        result[path.relative_to(base).as_posix()] = f"{stat.st_size}:{stat.st_mtime_ns}"
    return result

HOOK_POINTS = (
    "before_model", "after_model", "before_tool", "after_tool", "before_compact",
    "after_compact", "before_response", "after_response", "agent_stop",
    "subagent_start", "subagent_end",
)

#: How a registered handler participates in :meth:`HookBus.emit`. See HookBus.
_HOOK_MODES = frozenset({"serial", "waterfall", "parallel"})


class HookBus:
    """Ordered, optional lifecycle hooks. A failing hook never blocks Agent work.

    Three modes, because "run my handler" means different things:

    ``serial`` (the default, and what every existing registration gets)
        Handlers run one after another and their return values are ignored. This
        is the telemetry/audit shape and stays byte-identical to the old
        behaviour, so no existing hook changes meaning.

    ``waterfall``
        Each handler receives the previous handler's return value merged over the
        payload, so a later handler can *rewrite* what the agent is about to do —
        the only way to implement "inject a reminder before the model call" or
        "redact a tool argument" without editing the call site.

    ``parallel``
        Handlers run concurrently and their return values are ignored. For side
        effects that are slow and independent (a webhook, a metrics flush), where
        serial execution would add up.

    Registration carries the mode so call sites stay unchanged: ``emit`` looks up
    each handler's mode rather than taking a per-call argument.
    """

    def __init__(self) -> None:
        self._hooks: dict[str, list[Callable[..., Any]]] = defaultdict(list)
        # Modes live in a parallel list rather than a dict keyed by ``id(handler)``:
        # two identical lambdas can share an id once one is garbage collected, and
        # a stale key would silently promote a serial handler to a waterfall one.
        self._modes: dict[str, list[str]] = defaultdict(list)
        #: Payload as seen after waterfall rewriting by the most recent ``emit``.
        #: Call sites read this to pick up handler changes without a return value.
        self.last_payload: dict[str, Any] = {}

    def register(
        self,
        point: str,
        handler: Callable[..., Any],
        *,
        mode: str = "serial",
    ) -> None:
        if point not in HOOK_POINTS:
            raise ValueError(f"Unknown hook point: {point}")
        if mode not in _HOOK_MODES:
            raise ValueError(f"Unknown hook mode: {mode}")
        self._hooks[point].append(handler)
        self._modes[point].append(mode)

    def mode_of(self, point: str, handler: Callable[..., Any]) -> str:
        """Return the mode ``handler`` was registered with, defaulting to serial."""
        modes = self._modes.get(point, [])
        for index, registered in enumerate(self._hooks.get(point, [])):
            if registered is handler and index < len(modes):
                return modes[index]
        return "serial"

    def unregister(self, point: str, handler: Callable[..., Any]) -> bool:
        """Remove one handler; returns whether it was there.

        Needed by plugin hot reload: a reloaded plugin registers its hooks again,
        and without a removal step each reload would leave the previous closures
        attached, so one event would fire several copies of the same handler.
        """
        handlers = self._hooks.get(point)
        if not handlers:
            return False
        modes = self._modes.get(point, [])
        for index, registered in enumerate(handlers):
            if registered is handler:
                del handlers[index]
                if index < len(modes):
                    del modes[index]
                return True
        return False

    def forget_owner(self, owner: str) -> int:
        """Drop every handler tagged ``__atlas_owner__ == owner``; returns the count.

        Plugin functions come back as fresh objects after a reload, so identity
        cannot find the previous generation, and the closure's ``__qualname__`` is
        the same for every plugin — matching on it would drop unrelated plugins'
        hooks too. ``PluginRuntime`` tags each handler it registers with its plugin
        name, which is the only per-plugin handle available.
        """
        if not owner:
            return 0
        removed = 0
        for point in HOOK_POINTS:
            handlers = self._hooks.get(point)
            if not handlers:
                continue
            modes = self._modes.get(point, [])
            keep: list[Callable[..., Any]] = []
            kept_modes: list[str] = []
            for index, handler in enumerate(handlers):
                if getattr(handler, "__atlas_owner__", None) == owner:
                    removed += 1
                    continue
                keep.append(handler)
                if index < len(modes):
                    kept_modes.append(modes[index])
            if len(keep) != len(handlers):
                self._hooks[point] = keep
                self._modes[point] = kept_modes
        return removed

    async def emit(self, point: str, **payload: Any) -> list[dict[str, str]]:
        """Run the point's handlers; returns per-handler errors, never raises.

        Handlers run in registration order. Every handler sees the payload as
        rewritten so far, so a ``waterfall`` handler placed after another one can
        build on its change; a handler that only wants to observe is unaffected
        because serial handlers ignore the return value anyway. Consecutive
        ``parallel`` handlers are gathered as one batch at their position in that
        order, which keeps "parallel here, serial there" meaningful instead of
        hoisting every parallel handler to the end.
        """
        if point not in HOOK_POINTS:
            raise ValueError(f"Unknown hook point: {point}")
        errors: list[dict[str, str]] = []
        handlers = tuple(self._hooks[point])
        modes = tuple(self._modes.get(point, ()))
        current = dict(payload)
        batch: list[Callable[..., Any]] = []

        async def _flush() -> None:
            if not batch:
                return
            frozen = dict(current)
            outcomes = await asyncio.gather(
                *(_call_hook(handler, frozen) for handler in batch),
                return_exceptions=True,
            )
            for handler, outcome in zip(batch, outcomes, strict=False):
                if isinstance(outcome, BaseException):
                    errors.append(_hook_error(handler, outcome))
                    log.warning("agent.hook.failed", point=point, **errors[-1])
            batch.clear()

        for index, handler in enumerate(handlers):
            mode = modes[index] if index < len(modes) else "serial"
            if mode == "parallel":
                batch.append(handler)
                continue
            try:
                await _flush()
                returned = await _call_hook(handler, dict(current))
                # Only a dict return carries an opinion; ``None`` means "observed,
                # nothing to change", which is what most handlers do.
                if mode == "waterfall" and isinstance(returned, Mapping):
                    current.update(returned)
            except Exception as exc:
                errors.append(_hook_error(handler, exc))
                log.warning("agent.hook.failed", point=point, exc_info=True,
                            **errors[-1])
        try:
            await _flush()
        except Exception as exc:  # noqa: BLE001 - gather already isolates handlers
            errors.append(_hook_error(_flush, exc))

        self.last_payload = current
        return errors


def _hook_error(handler: Callable[..., Any], exc: BaseException) -> dict[str, str]:
    return {"hook": getattr(handler, "__name__", repr(handler)), "error": str(exc)}


async def _call_hook(handler: Callable[..., Any], payload: Mapping[str, Any]) -> Any:
    result = handler(**payload)
    if hasattr(result, "__await__"):
        return await result
    return result


@dataclass
class ContextMaintenance:
    """Compact structured task context while retaining the fields needed to resume."""

    hooks: HookBus
    snapshots: list[dict[str, Any]] = field(default_factory=list)

    def should_compact(
        self, messages: list[str], *, message_limit: int = 80, character_limit: int = 80_000,
    ) -> bool:
        return self.compact_trigger(messages, message_limit=message_limit,
                                    character_limit=character_limit)

    async def compact(self, context: Mapping[str, Any]) -> dict[str, Any]:
        preserved = {
            key: context.get(key)
            for key in (
                "goal", "project_state", "unresolved_work", "user_constraints",
                "active_process_refs", "active_tool_refs", "memory_refs",
                "session_summary",
            )
            if context.get(key) is not None
        }
        await self.hooks.emit("before_compact", context=preserved)
        snapshot = {**preserved, "snapshot_id": secrets.token_hex(8)}
        self.snapshots.append(snapshot)
        await self.hooks.emit("after_compact", snapshot=snapshot)
        return snapshot

    @staticmethod
    def compact_trigger(
        messages: list[str], *, message_limit: int = 80, character_limit: int = 80_000,
    ) -> bool:
        return len(messages) >= message_limit or sum(map(len, messages)) >= character_limit


@dataclass(frozen=True)
class ReminderPolicy:
    cadence: int = 8
    max_reminders: int = 1


class SystemReminders:
    """Emit a concise task reminder at configured turn intervals, without repeats."""

    def __init__(self, policy: ReminderPolicy | None = None) -> None:
        self.policy = policy or ReminderPolicy()
        self._emitted: set[int] = set()

    def reset(self) -> None:
        self._emitted.clear()

    def at_turn(self, turn: int, *, goal: str, constraints: list[str] | None = None) -> str | None:
        cadence = max(1, self.policy.cadence)
        slot = turn // cadence
        if turn <= 0 or turn % cadence or slot in self._emitted:
            return None
        if len(self._emitted) >= self.policy.max_reminders:
            return None
        self._emitted.add(slot)
        details = "; ".join((constraints or [])[:3])
        return f"Task reminder: {goal[:240]}" + (f" | Constraints: {details}" if details else "")


class TrajectoryReviewer:
    """Optional reviewer callback with durable, caller-visible review evidence."""

    def __init__(
        self, reviewer: Callable[[list[dict[str, Any]], str], Any] | None = None,
        *, backend: str | None = None, model: str | None = None,
    ) -> None:
        self.reviewer = reviewer
        self.backend, self.model = backend, model
        self.evidence: list[dict[str, Any]] = []

    async def review_trajectory(
        self, recent_events: list[dict[str, Any]], goal: str,
    ) -> dict[str, Any]:
        if self.reviewer is None:
            return {"decision": "continue", "guidance": None, "enabled": False}
        result = self.reviewer(recent_events, goal)
        if hasattr(result, "__await__"):
            result = await result
        if isinstance(result, str):
            result = {"decision": "corrective_guidance", "guidance": result}
        decision = result.get("decision", "continue")
        if decision not in {"continue", "corrective_guidance"}:
            raise ValueError("reviewer decision must be continue or corrective_guidance")
        evidence = {
            "goal": goal,
            "event_count": len(recent_events),
            "decision": decision,
            "guidance": result.get("guidance"),
            "backend": self.backend,
            "model": self.model,
        }
        self.evidence.append(evidence)
        return {**evidence, "enabled": True}


class AtlasToolBridge:
    """Dispatch tool calls through the canonical Atlas local/computer/MCP runtimes."""

    def __init__(
        self, local: Any = None, computer: Any = None, mcp: Any = None,
        checkpoints: Any = None,
    ) -> None:
        self.local, self.computer, self.mcp = local, computer, mcp
        self.checkpoints = checkpoints

    async def call_tool(
        self, name: str, arguments: dict[str, Any], *,
        run_id: str | None = None, conversation_id: str | None = None,
        tool_allow: list[str] | None = None, tool_deny: list[str] | None = None,
        read_only: bool = False, workspace: str | None = None,
    ) -> dict[str, Any]:
        if tool_allow is not None and name not in tool_allow:
            raise PermissionError(f"Tool '{name}' is not allowed by the active profile")
        if name in (tool_deny or []):
            raise PermissionError(f"Tool '{name}' is denied by the active profile")
        if read_only and (
            name not in {"local_file", "coding.repo_map", "coding.ast_grep.run"}
            or (name == "local_file" and arguments.get("action") not in {
                "read", "list", "glob", "search", "stat",
            })
        ):
            raise PermissionError(f"Tool '{name}' is not available in read-only mode")
        if name.startswith("local_") and self.local is not None:
            if workspace:
                arguments = {**arguments}
                arguments.setdefault("cwd", workspace)
            if (name == "local_edit" or (
                name == "local_file" and arguments.get("action") in {
                    "write", "append", "mkdir", "copy", "move", "delete",
                }
            )) and self.checkpoints is not None:
                self._checkpoint_file_targets(arguments, run_id, conversation_id)
            return await self.local.call_tool(name, arguments)
        if name.startswith("computer_") and self.computer is not None:
            return await self.computer.call_tool(name, arguments)
        if self.mcp is not None:
            return await self.mcp.call_tool(name, arguments)
        raise RuntimeError(f"No Atlas tool runtime for {name}")

    def _checkpoint_file_targets(
        self, arguments: dict[str, Any], run_id: str | None = None,
        conversation_id: str | None = None,
    ) -> None:
        cwd = Path(arguments.get("cwd") or Path.cwd())
        targets = [arguments.get("path")]
        if arguments.get("destination") and arguments.get("action") in {"copy", "move"}:
            targets.append(arguments["destination"])
        for raw in targets:
            if not raw:
                continue
            target = Path(os.path.expandvars(os.path.expanduser(str(raw))))
            if not target.is_absolute():
                target = cwd / target
            target = target.resolve()
            root = target.parent
            while not root.exists() and root != root.parent:
                root = root.parent
            if root.is_dir():
                relative = target.relative_to(root).as_posix()
                try:
                    self.checkpoints.create_checkpoint(
                        root, [relative], run_id=run_id,
                        conversation_id=conversation_id,
                    )
                except Exception as exc:
                    log.warning(
                        "agent.checkpoint.failed", path=str(target),
                        error=str(exc), exc_info=True,
                    )


class CodeActRuntime:
    """Run short Python workflows in a child process with a loopback Atlas tool bridge."""

    def __init__(self, bridge: AtlasToolBridge, *, timeout: float = 30.0) -> None:
        self.bridge = bridge
        self.timeout = max(0.1, min(timeout, 120.0))

    async def execute(
        self, code: str, *, run_id: str | None = None,
        conversation_id: str | None = None,
        tool_allow: list[str] | None = None, tool_deny: list[str] | None = None,
        read_only: bool = False, tool_catalog: list[dict[str, Any]] | None = None,
        event_callback: Any = None, cancel_event: Any = None, dry_run: bool = False,
        tool_dispatch: Any = None,
    ) -> dict[str, Any]:
        if not isinstance(code, str) or not code.strip():
            raise ValueError("code must be non-empty text")
        if dry_run:
            tree = ast.parse(code, filename="<atlas-code-mode>")
            calls = []
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "call_tool"
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "atlas"):
                    tool_name = node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) else None
                    calls.append((node.lineno, node.col_offset,
                                  tool_name if isinstance(tool_name, str) else "<dynamic>"))
            calls.sort(key=lambda entry: (entry[0], entry[1]))
            call_names = [entry[2] for entry in calls]
            return {"exit_code": 0, "dry_run": True, "executed": False,
                    "preview": {"tool_calls": call_names, "call_count": len(call_names),
                                "dynamic_names": any(name == "<dynamic>" for name in call_names)},
                    "workspace_isolated": True, "steps": []}
        token = secrets.token_urlsafe(24)
        workspace = tempfile.mkdtemp(prefix="atlas-code-mode-")
        steps: list[dict[str, Any]] = []
        step_lock = asyncio.Lock()

        async def emit(event: dict[str, Any]) -> None:
            if event_callback is not None:
                emitted = event_callback(event)
                if hasattr(emitted, "__await__"):
                    await emitted

        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            step: dict[str, Any] | None = None
            try:
                header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
                headers = header.decode("latin-1").split("\r\n")
                length = next((
                    int(line.split(":", 1)[1].strip()) for line in headers[1:]
                    if line.lower().startswith("content-length:")
                ), 0)
                request = json.loads(await asyncio.wait_for(reader.readexactly(length), timeout=5))
                if request.get("token") != token:
                    raise PermissionError("invalid bridge token")
                if cancel_event is not None and cancel_event.is_set():
                    raise asyncio.CancelledError("Code mode was cancelled")
                name = str(request["name"])
                async with step_lock:
                    step = {"index": len(steps) + 1, "tool": name, "status": "running"}
                    steps.append(step)
                await emit({"type": "code_mode_step", **step})
                if tool_dispatch is not None:
                    result = await tool_dispatch(name, dict(request.get("arguments", {})), workspace)
                else:
                    result = await self.bridge.call_tool(
                        name, dict(request.get("arguments", {})),
                        run_id=run_id, conversation_id=conversation_id,
                        tool_allow=tool_allow, tool_deny=tool_deny, read_only=read_only,
                        workspace=workspace,
                    )
                is_error = bool(result.get("is_error")) if isinstance(result, dict) else False
                data = result.get("data") if isinstance(result, dict) else result
                step.update({"status": "failed" if is_error else "completed",
                             "result_kind": type(data).__name__})
                await emit({"type": "code_mode_step", **step})
                payload = json.dumps(
                    _codeact_json_value(result), ensure_ascii=True, default=str,
                ).encode("utf-8", errors="replace")
                response_body = len(payload).to_bytes(4, "big") + payload
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\n"
                    + f"Content-Length: {len(response_body)}\r\nConnection: close\r\n\r\n".encode()
                    + response_body
                )
                await writer.drain()
            except Exception as exc:
                if step is not None and step.get("status") == "running":
                    step.update({"status": "failed", "error": type(exc).__name__})
                    await emit({"type": "code_mode_step", **step})
                log.debug("agent.codeact.bridge_request_failed",
                          error_type=type(exc).__name__)
                payload = json.dumps({"error": type(exc).__name__, "is_error": True},
                                     ensure_ascii=True).encode("utf-8", errors="replace")
                response_body = len(payload).to_bytes(4, "big") + payload
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\n"
                    + f"Content-Length: {len(response_body)}\r\nConnection: close\r\n\r\n".encode()
                    + response_body
                )
                with contextlib.suppress(Exception):
                    await writer.drain()
            finally:
                writer.close()
                with contextlib.suppress(Exception):
                    await writer.wait_closed()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = int(server.sockets[0].getsockname()[1])
        # The catalog travels through a file, never argv: the whole
        # ``python -c <runner>`` command line is capped at 32767 characters on
        # Windows, and a full tool catalog blows past it (WinError 206).
        catalog_path = Path(workspace) / "_atlas_tool_catalog.json"
        catalog_path.write_text(
            json.dumps(tool_catalog or [], ensure_ascii=False), encoding="utf-8",
        )
        runner = (
            "import asyncio,json,sys,urllib.request\n"
            f"TOKEN={token!r}\nPORT={port}\n"
            f"WORKSPACE={workspace!r}\n"
            f"TOOLS_PATH={str(catalog_path)!r}\n"
            "class Bridge:\n"
            " def list_tools(self):\n"
            "  with open(TOOLS_PATH,encoding='utf-8') as f: return json.load(f)\n"
            " @property\n"
            " def workspace(self): return WORKSPACE\n"
            " def call_tool(self,name,arguments=None):\n"
            "  body=json.dumps({'token':TOKEN,'name':name,'arguments':arguments or {}},ensure_ascii=True).encode('utf-8',errors='replace')\n"
            "  req=urllib.request.Request(f'http://127.0.0.1:{PORT}/',data=body,method='POST')\n"
            "  with urllib.request.urlopen(req,timeout=15) as r: data=r.read()\n"
            "  n=int.from_bytes(data[:4],'big'); return json.loads(data[4:4+n].decode('utf-8',errors='replace'))\n"
            "atlas=Bridge()\n"
            "async def _run():\n"
            " ns={'atlas':atlas}\n"
            " exec(compile(sys.stdin.read(),'<atlas-codeact>','exec'),ns,ns)\n"
            " result=ns.get('result')\n"
            " if asyncio.iscoroutine(result): result=await result\n"
            " print('ATLAS_RESULT:'+json.dumps(result,ensure_ascii=True,default=str))\n"
            "asyncio.run(_run())\n"
        )
        from atlas.engine.tools.environments.local import hermes_subprocess_env

        process = await asyncio.create_subprocess_exec(
            sys.executable, "-u", "-c", runner,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=workspace,
            env={**hermes_subprocess_env(inherit_credentials=False),
                 "PYTHONIOENCODING": "utf-8:replace", "PYTHONUTF8": "1"},
        )

        async def read_tail(reader: asyncio.StreamReader, limit: int) -> bytes:
            tail = bytearray()
            while chunk := await reader.read(8192):
                tail.extend(chunk)
                if len(tail) > limit:
                    del tail[:-limit]
            return bytes(tail)

        try:
            assert process.stdin is not None
            process.stdin.write(code.encode("utf-8", errors="replace"))
            await process.stdin.drain()
            process.stdin.close()
            stdout_task = asyncio.create_task(read_tail(process.stdout, 16000))
            stderr_task = asyncio.create_task(read_tail(process.stderr, 8000))
            wait_task = asyncio.create_task(process.wait())
            deadline = asyncio.get_running_loop().time() + self.timeout
            while not wait_task.done():
                if cancel_event is not None and cancel_event.is_set():
                    process.kill()
                    await wait_task
                    raise asyncio.CancelledError("Code mode was cancelled")
                if asyncio.get_running_loop().time() >= deadline:
                    process.kill()
                    await wait_task
                    raise TimeoutError(f"CodeAct exceeded {self.timeout:g}s") from None
                await asyncio.sleep(0.05)
            stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
        except TimeoutError:
            raise TimeoutError(f"CodeAct exceeded {self.timeout:g}s") from None
        finally:
            server.close()
            await server.wait_closed()
            import shutil
            shutil.rmtree(workspace, ignore_errors=True)
        out = stdout.decode("utf-8", errors="replace")[-16000:]
        err = stderr.decode("utf-8", errors="replace")[-8000:]
        result: Any = None
        for line in out.splitlines():
            if line.startswith("ATLAS_RESULT:"):
                with contextlib.suppress(json.JSONDecodeError):
                    result = json.loads(line.removeprefix("ATLAS_RESULT:"))
        return {"exit_code": process.returncode,
                "stdout": _codeact_json_value(out),
                "stderr": _codeact_json_value(err),
                "result": _codeact_json_value(result),
                "steps": _codeact_json_value(steps), "workspace_isolated": True}


class DelegationService:
    """One disposable child session using Atlas's existing AgentBackendHost."""

    def __init__(self, host: Any, hooks: HookBus, *, timeout: float = 90.0) -> None:
        self.host, self.hooks, self.timeout = host, hooks, timeout
        self._status_cache: dict[str, Any] = {}
        self.atlas_runner: Callable[..., Any] | None = None
        self._subtasks: dict[str, dict[str, Any]] = {}
        self._background_tasks: dict[str, asyncio.Task[Any]] = {}
        self._steer_queues: dict[str, asyncio.Queue[dict[str, str]]] = {}
        self.capacity = get_subagent_capacity()
        self.mailbox = AgentMailbox()
        self._mailbox_pumps: dict[str, asyncio.Task[Any]] = {}

    async def send_agent_message(self, sender: str, recipient: str, content: str) -> MailMessage:
        """Deliver a FIFO message to an agent address and wake a waiting child."""
        return await self.mailbox.send(sender, recipient, content)

    async def receive_agent_messages(
        self, address: str, *, wait: bool = False, limit: int = 100,
    ) -> list[MailMessage]:
        """Read queued messages for an agent, optionally waiting for delivery."""
        return await self.mailbox.receive(address, wait=wait, limit=limit)

    def _start_mailbox_pump(self, subtask_id: str, address: str,
                            steer_queue: asyncio.Queue[dict[str, str]]) -> None:
        task = self._mailbox_pumps.get(subtask_id)
        if task is not None and not task.done():
            return

        async def pump() -> None:
            while True:
                messages = await self.mailbox.receive(address, wait=True)
                for message in messages:
                    steer_queue.put_nowait({
                        "content": message.content,
                        "event_id": f"mail-{message.revision}",
                        "sender": message.sender,
                        "mail_revision": message.revision,
                    })

        self._mailbox_pumps[subtask_id] = asyncio.create_task(
            pump(), name=f"atlas-mailbox-{subtask_id}",
        )

    async def _stop_mailbox_pump(self, subtask_id: str) -> None:
        task = self._mailbox_pumps.pop(subtask_id, None)
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def subtask_status(self, subtask_id: str) -> dict[str, Any] | None:
        """Return the live summary surface for one child, without its control objects."""
        record = self._subtasks.get(subtask_id)
        if record is None:
            return None
        return {key: value for key, value in record.items()
                if key not in {"cancel_event", "steer_queue"}}

    def list_subtasks(self) -> list[dict[str, Any]]:
        """Return this run's team roster in creation order, without control objects.

        This is the model-visible Agent Teams roster: one row per live child with
        its identity, goal, and status. Closed children are included until
        ``close_subtask`` consumes them, so the caller sees the full team.
        """
        return [
            {key: value for key, value in record.items()
             if key not in {"cancel_event", "steer_queue"}}
            for record in self._subtasks.values()
        ]

    def roster_status_signature(self) -> dict[str, str]:
        """Compact per-member status map used by team-wide waits."""
        return {
            subtask_id: str(record.get("status") or "")
            for subtask_id, record in self._subtasks.items()
        }

    async def wait_background(self, subtask_id: str) -> None:
        """Wait for one background child; primarily useful to lifecycle owners and tests."""
        task = self._background_tasks.get(subtask_id)
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    def cancel_subtask(self, subtask_id: str) -> bool:
        record = self._subtasks.get(subtask_id)
        if record is None or record.get("status") != "running":
            return False
        cancel_event = record.get("cancel_event")
        if cancel_event is not None and hasattr(cancel_event, "set"):
            cancel_event.set()
        task = self._background_tasks.get(subtask_id)
        if task is not None and not task.done() and cancel_event is None:
            task.cancel()
        return True

    def close_subtask(self, subtask_id: str) -> bool:
        record = self._subtasks.get(subtask_id)
        if record is None or record.get("status") == "running":
            return False
        self._subtasks.pop(subtask_id, None)
        self._steer_queues.pop(subtask_id, None)
        task = self._background_tasks.pop(subtask_id, None)
        if task is not None and not task.done():
            task.cancel()
        return True

    def steer_subtask(self, subtask_id: str, text: str) -> bool:
        """Send an addressed mailbox message for the child's next model turn."""
        record = self._subtasks.get(subtask_id)
        if not text.strip() or record is None or record.get("status") != "running":
            return False
        address = record.get("agent_address")
        if not address:
            return False
        try:
            self.mailbox.send_nowait("parent@atlas", str(address), text)
            return True
        except ValueError:
            return False

    async def _pick_backend(self) -> str:
        """First installed external Agent, Hermes preferred; a clear error when none is installed."""
        names = list(getattr(self.host, "backends", {}) or {})
        if not names:
            raise RuntimeError("没有配置可用的子 Agent。")
        try:
            from atlas.runtime.external_agents import AGENT_COMMANDS, external_agent_status

            status = await asyncio.to_thread(external_agent_status, self._status_cache)
            available = {item["id"] for item in status["agents"] if item["available"]}
            known = set(AGENT_COMMANDS)
        except Exception:
            log.debug("agent.external_backend_status_unavailable", exc_info=True)
            return "hermes" if "hermes" in names else names[0]
        ordered = sorted(names, key=lambda name: (name != "hermes", names.index(name)))
        for name in ordered:
            # Adapters that aren't CLI-backed (tests, custom hosts) are taken as available.
            if name in available or name not in known:
                return name
        raise RuntimeError(
            "子任务需要一个外部 Agent 来执行，但这台电脑上没有装 Hermes、Claude Code、Codex 等命令行程序。"
            "请安装其中一个，或者直接让 Atlas 自己按顺序完成这些事。"
        )

    async def delegate_task(
        self, goal: str, context: str | None = None, tool_profile: list[str] | None = None,
        *, backend: str | None = None, cwd: str | None = None,
        on_started: Callable[..., Any] | None = None,
        on_progress: Callable[..., Any] | None = None,
        on_completed: Callable[..., Any] | None = None,
        event_metadata: dict[str, Any] | None = None,
        executor: str = "atlas",
        atlas_options: dict[str, Any] | None = None,
        background: bool = False,
        output_schema: dict[str, Any] | str | None = None,
        _subtask_id: str | None = None,
    ) -> dict[str, Any]:
        if not goal.strip():
            raise ValueError("goal must be non-empty")
        # Config is read at admission time so persisted changes survive process
        # restarts and newly queued children observe the latest global limit.
        from atlas import agent as agent_module

        configured_limit = agent_module.load_user_settings().get("subagent_max_concurrent", 8)
        if type(configured_limit) is not int or configured_limit < 1:
            configured_limit = 8
        await self.capacity.set_limits(max_concurrent=configured_limit)
        from atlas.agent.delegation_output_schema import (
            append_output_contract, build_retry_message, coerce_output_schema,
            validate_output,
        )

        schema, schema_error = coerce_output_schema(output_schema)
        if schema_error:
            raise ValueError(schema_error)
        subtask_id = _subtask_id or secrets.token_hex(8)
        steer_queue = self._steer_queues.setdefault(subtask_id, asyncio.Queue())
        team_id = str((atlas_options or {}).get("team_id") or "atlas")
        agent_address = normalize_address(f"{subtask_id}@{team_id}")
        self._start_mailbox_pump(subtask_id, agent_address, steer_queue)
        record = self._subtasks.setdefault(subtask_id, {
            "subtask_id": subtask_id, "goal": goal, "status": "running",
            "progress": "等待子 Agent 启动。", "result": None,
            "background": background, "steer_queue": steer_queue,
        })
        record.update({"goal": goal, "status": "running", "agent_address": agent_address})
        if _subtask_id is None:
            record["background"] = background
        if _subtask_id is None and background:
            async def child_callback(callback: Callable[..., Any] | None, *args: Any) -> Any:
                return await _call_callback(callback, *args)

            async def run_background() -> None:
                record = self._subtasks[subtask_id]

                async def on_start(child_id: str, child_goal: str, child_backend: str,
                                   metadata: dict[str, Any] | None = None) -> Any:
                    record.update({"backend": child_backend, "progress": "子 Agent 已启动。"})
                    return await child_callback(on_started, child_id, child_goal, child_backend,
                                                metadata) if event_metadata is not None else await child_callback(
                                                    on_started, child_id, child_goal, child_backend)

                async def on_update(child_id: str, text: str,
                                    metadata: dict[str, Any] | None = None) -> Any:
                    record["progress"] = text
                    return await child_callback(on_progress, child_id, text, metadata) \
                        if event_metadata is not None else await child_callback(on_progress, child_id, text)

                async def on_finish(child_id: str, status: str, summary: str, duration_ms: int,
                                    metadata: dict[str, Any] | None = None) -> Any:
                    record.update({"status": status, "result": summary,
                                   "duration_ms": duration_ms, "progress": summary})
                    try:
                        if event_metadata is not None:
                            await child_callback(on_completed, child_id, status, summary,
                                                 duration_ms, metadata)
                        else:
                            await child_callback(on_completed, child_id, status, summary,
                                                 duration_ms)
                    finally:
                        await self._stop_mailbox_pump(subtask_id)
                        self._steer_queues.pop(subtask_id, None)

                try:
                    result = await self.delegate_task(
                        goal, context, tool_profile, backend=backend, cwd=cwd,
                        on_started=on_start, on_progress=on_update, on_completed=on_finish,
                        event_metadata=event_metadata, executor=executor,
                        atlas_options={**(atlas_options or {}), "steer_queue": steer_queue},
                        background=False, output_schema=schema, _subtask_id=subtask_id,
                    )
                    record.update({"status": result.get("status", "completed"),
                                   "result": result.get("result", "")})
                except asyncio.CancelledError:
                    record.update({"status": "cancelled", "result": "子任务已取消。"})
                    raise
                except Exception as exc:
                    log.warning(
                        "agent.background_subtask_failed",
                        subtask_id=subtask_id, error=str(exc), exc_info=True,
                    )
                    record.update({"status": "failed", "result": str(exc)[:1000]})
                finally:
                    if record.get("status") == "running":
                        record.update({"status": "failed", "result": "子任务未能完成。"})
                    await self._stop_mailbox_pump(subtask_id)
                    self._steer_queues.pop(subtask_id, None)

            self._background_tasks[subtask_id] = asyncio.create_task(
                run_background(), name=f"atlas-subtask-{subtask_id}",
            )
            return {"backend": "atlas", "session_id": None, "subtask_id": subtask_id,
                    "status": "running", "background": True}
        name = backend or executor
        if name != "atlas" and atlas_options is not None and (
            atlas_options.get("permission_mode", "full_access") != "full_access"
            or atlas_options.get("tool_allow") is not None
            or atlas_options.get("tool_deny")
            or atlas_options.get("agent_type", "general") != "general"
        ):
            # ACP backends do not expose Atlas's permission/tool allowlist contract; route
            # constrained children through the native worker loop instead of widening access.
            name = "atlas"
        # Models sometimes fill the executor with "default", "auto" or a made-up name; anything that
        # isn't a configured external Agent runs on Atlas itself.
        if name not in (getattr(self.host, "backends", None) or {}):
            name = "atlas"
        if name == "atlas" and self.atlas_runner is None:
            raise RuntimeError("Atlas 子任务执行器尚未就绪。")
        record.update({"status": "queued", "progress": "等待子 Agent 容量槽位。"})
        capacity_ticket = await self.capacity.acquire(
            parent_id=str((atlas_options or {}).get("parent_subtask_id") or "root"),
            depth=int((atlas_options or {}).get("depth", 1) or 1),
        )
        record.update({"status": "running", "progress": "子 Agent 已取得容量槽位。"})
        if name == "atlas":
            task_context = append_output_contract(context, schema) if schema else context
            record["backend"] = "atlas"
            await self.hooks.emit("subagent_start", goal=goal, backend="atlas")
            started_at = asyncio.get_running_loop().time()
            status, summary = "failed", "子任务没有返回结果。"
            cancel_event = asyncio.Event()
            # Make the live cancellation handle visible before `on_started` fires.
            # Budget owners (such as /ultraplan) can then stop a foreground child
            # that is currently inside the Atlas runner, not just background jobs.
            record["cancel_event"] = cancel_event
            parent_cancel = (atlas_options or {}).get("cancel_event")
            parent_cancel_task = None
            try:
                start_args = (subtask_id, goal, "atlas")
                registered_cancel = await _call_callback(
                    on_started, *(start_args + ((event_metadata,) if event_metadata is not None else ())),
                )
                if isinstance(registered_cancel, asyncio.Event):
                    cancel_event = registered_cancel
                    record["cancel_event"] = cancel_event
                if parent_cancel is not None:
                    parent_cancel_task = asyncio.create_task(
                        _relay_cancel(parent_cancel, cancel_event),
                    )
                child_context = task_context
                for attempt in range(2 if schema else 1):
                    progress_seen = False

                    async def report_child_progress(text: str) -> Any:
                        nonlocal progress_seen
                        progress_seen = True
                        return await _call_callback(
                            on_progress, subtask_id, _human_subtask_text(text),
                            *((event_metadata,) if event_metadata is not None else ()),
                        )

                    # A child that fails before publishing any progress has not
                    # exposed a tool call or result to the parent. Give that
                    # startup failure one bounded restart. Once progress starts,
                    # the outcome may include side effects, so fail closed.
                    crash_attempt = 0
                    while True:
                        try:
                            result = await self.atlas_runner(
                                goal=goal, context=child_context, cwd=cwd,
                                subtask_id=subtask_id,
                                atlas_options={**(atlas_options or {}),
                                               "cancel_event": cancel_event},
                                on_progress=report_child_progress,
                            )
                            break
                        except asyncio.CancelledError:
                            raise
                        except Exception:
                            if crash_attempt or progress_seen or cancel_event.is_set():
                                raise
                            crash_attempt += 1
                            await _call_callback(
                                on_progress, subtask_id,
                                "子 Agent 启动失败，按一次性崩溃预算重新启动。",
                                *((event_metadata,) if event_metadata is not None else ()),
                            )
                    if schema is None:
                        break
                    valid, errors = validate_output(str(result.get("result", "")), schema)
                    result["schema_valid"] = valid
                    if valid:
                        break
                    result["schema_errors"] = errors
                    if attempt == 0:
                        child_context = (
                            f"{task_context or ''}\n\n上一次回复：\n"
                            f"{result.get('result', '')}\n\n{build_retry_message(errors)}"
                        )
                status = str(result.get("status", "completed"))
                summary = str(result.get("result", ""))[:1000] or "子任务已完成。"
                record.update({"status": status, "progress": summary,
                               "result": result.get("result", "")})
                return {"backend": "atlas", "session_id": result.get("session_id"),
                        "subtask_id": subtask_id, "status": status,
                        "result": result.get("result", ""),
                        "evidence": result.get("evidence", []),
                        **{key: result[key] for key in (
                            "changed_files", "changed_files_complete", "tokens",
                            "duration_ms", "log_path",
                        ) if key in result},
                        **({"schema_valid": result["schema_valid"]} if schema else {}),
                        **({"schema_errors": result["schema_errors"]}
                           if schema and not result.get("schema_valid") else {})}
            except asyncio.CancelledError:
                status, summary = "cancelled", "子任务已取消。"
                raise
            except Exception as exc:
                summary = str(exc)[:1000] or summary
                raise
            finally:
                await self.capacity.release(capacity_ticket)
                await self._stop_mailbox_pump(subtask_id)
                record.update({"status": status, "progress": summary, "result": summary})
                self._steer_queues.pop(subtask_id, None)
                if parent_cancel_task:
                    parent_cancel_task.cancel()
                    await asyncio.gather(parent_cancel_task, return_exceptions=True)
                await self.hooks.emit("subagent_end", goal=goal, backend="atlas")
                completed_args = (
                    subtask_id, status, summary,
                    int((asyncio.get_running_loop().time() - started_at) * 1000),
                )
                await _call_callback(
                    on_completed, *(completed_args + (
                        (event_metadata,) if event_metadata is not None else ()
                    )),
                )
        await self.hooks.emit("subagent_start", goal=goal, backend=name)
        session = None
        record["backend"] = name
        started_at = asyncio.get_running_loop().time()
        cancel_event = asyncio.Event()
        status = "failed"
        completion_summary = "Subtask did not produce a result."
        last_progress = 0.0
        prompt = (
            "Investigate this task in an independent session. Use the Atlas shared tool bridge "
            "when repository evidence is needed. Return concise findings and evidence.\n"
            f"Goal: {goal}\nContext: {context or '(none)'}\n"
            f"Preferred tool profile: {json.dumps(tool_profile or [], ensure_ascii=False)}"
        )
        try:
            if on_started:
                cancel = (
                    on_started(subtask_id, goal, name, event_metadata)
                    if event_metadata is not None else on_started(subtask_id, goal, name)
                )
                if hasattr(cancel, "__await__"):
                    cancel = await cancel
                if isinstance(cancel, asyncio.Event):
                    cancel_event = cancel
                    record["cancel_event"] = cancel_event
            session = await asyncio.wait_for(
                self.host.start(name, cwd), timeout=min(self.timeout, 30),
            )
            if not cancel_event.is_set():
                await asyncio.wait_for(
                    self.host.send(session.id, prompt), timeout=min(self.timeout, 30),
                )
            events: list[dict[str, Any]] = []
            async def collect() -> None:
                nonlocal last_progress
                iterator = self.host.events(session.id).__aiter__()
                next_event = asyncio.create_task(iterator.__anext__())
                while not cancel_event.is_set():
                    steer_queue = self._steer_queues.get(subtask_id)
                    if steer_queue is not None:
                        while not steer_queue.empty():
                            steering = steer_queue.get_nowait()
                            await self.host.send(session.id, steering["content"])
                    done, _ = await asyncio.wait({next_event}, timeout=0.1)
                    if not done:
                        continue
                    try:
                        event = next_event.result()
                    except StopAsyncIteration:
                        return
                    entry = {"type": event.type, "data": event.data}
                    events.append(entry)
                    text = next((str(event.data.get(key)) for key in ("text", "content", "message")
                                 if isinstance(event.data, dict) and event.data.get(key)), "")
                    now = asyncio.get_running_loop().time()
                    if text and on_progress and now - last_progress >= 0.5:
                        last_progress = now
                        record["progress"] = text
                        progress = (
                            on_progress(subtask_id, text, event_metadata)
                            if event_metadata is not None else on_progress(subtask_id, text)
                        )
                        if hasattr(progress, "__await__"):
                            await progress
                    next_event = asyncio.create_task(iterator.__anext__())
                if not next_event.done():
                    next_event.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await next_event
            await asyncio.wait_for(collect(), timeout=self.timeout)
            status = "cancelled" if cancel_event.is_set() else "completed"
            text = "\n".join(
                str(e["data"].get(key, "")) for e in events
                for key in ("text", "content", "message") if e["data"].get(key)
            )
            completion_summary = text[:1000] or (
                "Subtask cancelled." if status == "cancelled" else "Subtask completed without text output."
            )
            record.update({"status": status, "progress": completion_summary,
                           "result": completion_summary})
            return {"backend": name, "session_id": session.id, "subtask_id": subtask_id, "status": status, "result": text,
                    "evidence": events}
        except asyncio.TimeoutError:
            status = "failed"
            raise
        except Exception as exc:
            completion_summary = str(exc)[:1000] or completion_summary
            raise
        finally:
            await self.capacity.release(capacity_ticket)
            await self._stop_mailbox_pump(subtask_id)
            if cancel_event.is_set():
                status = "cancelled"
            record.update({"status": status, "progress": completion_summary,
                           "result": completion_summary})
            self._steer_queues.pop(subtask_id, None)
            if session is not None:
                await self.host.close(session.id)
            await self.hooks.emit(
                "subagent_end", goal=goal, backend=name,
                session_id=session.id if session is not None else None,
            )
            if on_completed:
                duration_ms = int((asyncio.get_running_loop().time() - started_at) * 1000)
                completed = (
                    on_completed(
                        subtask_id, status, completion_summary, duration_ms, event_metadata,
                    )
                    if event_metadata is not None else on_completed(
                        subtask_id, status, completion_summary, duration_ms,
                    )
                )
                if hasattr(completed, "__await__"):
                    await completed

    async def delegate_parallel(
        self,
        tasks: list[dict[str, Any]],
        *,
        max_concurrency: int = 3,
        cwd: str | None = None,
        cancel_event: asyncio.Event | None = None,
        summarize: Callable[[list[dict[str, Any]]], Any] | None = None,
        on_started: Callable[..., Any] | None = None,
        on_progress: Callable[..., Any] | None = None,
        on_completed: Callable[..., Any] | None = None,
        on_group_completed: Callable[..., Any] | None = None,
        executor: str = "atlas",
        atlas_options: dict[str, Any] | None = None,
        verify: dict[str, Any] | None = None,
        background: bool = False,
        _batch_background: bool = False,
    ) -> dict[str, Any]:
        if not isinstance(tasks, list) or not 1 <= len(tasks) <= 8:
            raise ValueError("delegate_parallel accepts one to eight tasks")
        if not isinstance(max_concurrency, int) or not 1 <= max_concurrency <= 16:
            raise ValueError("max_concurrency must be between 1 and 16")
        if any(not isinstance(item, dict) or not str(item.get("goal", "")).strip()
               or not str(item.get("title", "")).strip() for item in tasks):
            raise ValueError("each parallel task requires a title and goal")

        if background:
            group_id = secrets.token_hex(8)
            record = {"subtask_id": group_id, "status": "running", "background": True,
                      "progress": "后台 Worker 组已排队。", "result": None,
                      "group": True}
            self._subtasks[group_id] = record

            async def finish_group(payload: dict[str, Any]) -> None:
                summary = str(payload.get("summary", ""))[:2000]
                record.update({"status": "completed", "progress": summary, "result": summary})
                payload.update({"background": True, "subtask_id": group_id})
                await _call_callback(on_group_completed, payload)

            async def run_group() -> None:
                try:
                    result = await self.delegate_parallel(
                        tasks, max_concurrency=max_concurrency, cwd=cwd,
                        cancel_event=cancel_event, summarize=summarize,
                        on_started=on_started, on_progress=on_progress,
                        on_completed=on_completed, on_group_completed=finish_group,
                        executor=executor, atlas_options=atlas_options,
                        verify=verify, background=False,
                        _batch_background=True,
                    )
                    record.update({"status": "completed", "result": result["summary"],
                                   "progress": result["summary"]})
                except asyncio.CancelledError:
                    record.update({"status": "cancelled", "result": "后台 Worker 组已取消。"})
                    raise
                except Exception as exc:
                    log.warning(
                        "agent.background_group_failed",
                        group_id=group_id, error=str(exc), exc_info=True,
                    )
                    record.update({"status": "failed", "result": str(exc)[:1000]})

            self._background_tasks[group_id] = asyncio.create_task(
                run_group(), name=f"atlas-subtask-group-{group_id}",
            )
            return {"group_id": group_id, "subtask_id": group_id,
                    "status": "running", "background": True}

        # Pick the worker Agent once: with none installed, fail the whole group up front.
        worker_backend = executor
        group_id = secrets.token_hex(8)
        semaphore = asyncio.Semaphore(max_concurrency)
        worktree_lock = asyncio.Lock()
        worker_cancels: dict[int, asyncio.Event] = {}
        is_git = False
        git_root: Path | None = None
        if cwd:
            probe = await asyncio.to_thread(
                subprocess.run,
                ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
            )
            if probe.returncode == 0:
                git_root = Path(probe.stdout.strip()).resolve()
                is_git = True

        async def call(callback: Callable[..., Any] | None, *args: Any) -> Any:
            if callback is None:
                return None
            value = callback(*args)
            return await value if hasattr(value, "__await__") else value

        async def run_one(index: int, item: dict[str, Any]) -> dict[str, Any]:
            title = str(item["title"])
            goal = str(item["goal"])
            metadata = {"group_id": group_id, "index": index, "title": title,
                        "agent": str(item.get("agent", "general")),
                        "role": str(item.get("agent_role", "leaf")), "background": _batch_background,
                        "model": item.get("agent_model"), "depth": int((atlas_options or {}).get("depth", 0)) + 1,
                        "recipe_id": item.get("recipe_id"),
                        **({"warning": item["agent_warning"]} if item.get("agent_warning") else {})}
            async with semaphore:
                async def setup_failed(summary: str) -> dict[str, Any]:
                    subtask_id = f"{group_id}-{index}"
                    backend = "hermes" if "hermes" in (getattr(self.host, "backends", {}) or {}) else "unknown"
                    await call(on_started, subtask_id, goal, backend, metadata)
                    await call(
                        on_completed, subtask_id, "failed", summary, 0, metadata,
                    )
                    return {
                        "index": index, "title": title, "status": "failed",
                        "summary": summary, "changed_files": [], "patch": "",
                    }

                if cancel_event and cancel_event.is_set():
                    return {
                        "index": index, "title": title, "status": "cancelled",
                        "summary": "Worker cancelled before start.", "changed_files": [],
                        "patch": "",
                    }
                worker_cwd = cwd
                worktree: Path | None = None
                worktree_info: dict[str, str] | None = None
                shared_before: dict[str, str] | None = None
                if is_git and git_root is not None and cwd:
                    try:
                        relative_cwd = Path(cwd).resolve().relative_to(git_root)
                    except ValueError:
                        return await setup_failed(
                            "Worker directory is outside the Git repository.",
                        )
                    from atlas.agent.subagent_worktree import create_subagent_worktree

                    async with worktree_lock:
                        worktree_info = await asyncio.to_thread(
                            create_subagent_worktree, cwd, f"{group_id}-{index}",
                        )
                    if worktree_info is None:
                        return await setup_failed(
                            "无法创建子 Agent 的隔离 worktree。",
                        )
                    worktree = Path(worktree_info["path"])
                    worker_cwd = str(worktree / relative_cwd)
                elif cwd:
                    shared_before = await asyncio.to_thread(_workspace_fingerprint, cwd)

                async def started(subtask_id: str, child_goal: str, backend: str, _meta: Any) -> Any:
                    child_cancel = await call(on_started, subtask_id, child_goal, backend, metadata)
                    if isinstance(child_cancel, asyncio.Event):
                        worker_cancels[index] = child_cancel
                        if cancel_event and cancel_event.is_set():
                            child_cancel.set()
                    return child_cancel

                async def progress(subtask_id: str, text: str, _meta: Any) -> Any:
                    return await call(on_progress, subtask_id, text, metadata)

                async def completed(
                    subtask_id: str, status: str, summary: str, duration_ms: int, _meta: Any,
                ) -> Any:
                    return await call(
                        on_completed, subtask_id, status, summary, duration_ms, metadata,
                    )

                worker_context = str(item.get("context") or "")
                if not is_git:
                    worker_context += (
                        "\nShared non-git workspace: only edit files explicitly assigned in "
                        "this task's context; if ownership is unclear, return findings without edits."
                    )
                elif worktree_info is not None:
                    worker_context += (
                        f"\n当前 Worker 使用隔离 Git worktree：{worktree_info['path']}。"
                        "不要合并这个分支；父 Agent 会检查改动。"
                    )
                try:
                    task_options = {**(atlas_options or {}),
                                    "agent_type": str(item.get("agent", "general")),
                                    "agent_role": str(item.get("agent_role", "leaf")),
                                    "depth": metadata["depth"],
                                    "tool_allow": intersect_tool_allow(
                                        (atlas_options or {}).get("tool_allow"), item.get("agent_tools"),
                                        (atlas_options or {}).get("available_tools", [])),
                                    "model": item.get("agent_model") or (atlas_options or {}).get("model"),
                                    "reasoning_effort": item.get("reasoning_effort")
                                    or (atlas_options or {}).get("reasoning_effort"),
                                    "max_spawn_depth": min(
                                        int((atlas_options or {}).get("max_spawn_depth", 4)),
                                        int(metadata["depth"]) + int(item.get("max_depth", 4)),
                                    )}
                    parent_permission = str(task_options.get("permission_mode", "full_access"))
                    child_permission = item.get("agent_permission")
                    permission_rank = {"full_access": 0, "auto_file": 1, "ask_writes": 2, "ask_each": 3, "plan": 4, "read_only": 5}
                    if (child_permission in permission_rank and
                            permission_rank[child_permission] > permission_rank.get(parent_permission, 0)):
                        task_options["permission_mode"] = child_permission
                    result = await self.delegate_task(
                        goal, worker_context or None,
                        backend=str(item.get("executor", worker_backend)), cwd=worker_cwd,
                        on_started=started, on_progress=progress, on_completed=completed,
                        event_metadata=metadata, atlas_options=task_options,
                        output_schema=item.get("output_schema"),
                    )
                    status = str(result.get("status", "unknown"))
                    summary = str(result.get("result", ""))[:1000]
                except asyncio.CancelledError:
                    status, summary, result = "cancelled", "Worker cancelled.", {}
                except Exception as exc:
                    log.warning("agent.parallel_worker_failed", error=str(exc), exc_info=True)
                    status, summary, result = "failed", str(exc)[:1000], {}

                changed_files: list[str] = []
                patch_text = ""
                worktree_payload: dict[str, Any] = {}
                if worktree is not None:
                    try:
                        await asyncio.to_thread(
                            subprocess.run,
                            ["git", "-C", str(worktree), "add", "-N", "--all"],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
                        )
                        status_result = await asyncio.to_thread(
                            subprocess.run,
                            ["git", "-C", str(worktree), "status", "--porcelain"],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
                        )
                        changed_files = [
                            line[3:].strip().replace("\\", "/")
                            for line in status_result.stdout.splitlines() if len(line) > 3
                        ]
                        committed = await asyncio.to_thread(
                            subprocess.run,
                            ["git", "-C", str(worktree), "diff", "--name-only",
                             worktree_info["base_commit"]],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
                        )
                        changed_files = sorted(set(changed_files) | {
                            line.strip().replace("\\", "/")
                            for line in committed.stdout.splitlines() if line.strip()
                        })
                        diff = await asyncio.to_thread(
                            subprocess.run,
                            ["git", "-C", str(worktree), "diff", "--binary",
                             worktree_info["base_commit"]],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
                        )
                        patch_text = diff.stdout
                    finally:
                        from atlas.agent.subagent_worktree import finalize_subagent_worktree

                        async with worktree_lock:
                            worktree_payload = await asyncio.to_thread(
                                finalize_subagent_worktree, worktree_info,
                            )
                    if worktree_payload.get("inspection_failed"):
                        summary = f"{summary}\n{worktree_payload['note']}"
                else:
                    if shared_before is not None and cwd:
                        shared_after = await asyncio.to_thread(_workspace_fingerprint, cwd)
                        changed_files = sorted(
                            path for path in shared_before.keys() | shared_after.keys()
                            if shared_before.get(path) != shared_after.get(path)
                        )
                    else:
                        changed_files = list(result.get("changed_files", []))
                return {
                    "index": index, "title": title, "status": status,
                    "summary": summary, "changed_files": changed_files, "patch": patch_text,
                    **({"worktree": worktree_payload} if worktree is not None else {}),
                    **({"schema_valid": result["schema_valid"]}
                       if "schema_valid" in result else {}),
                    **({"schema_errors": result["schema_errors"]}
                       if result.get("schema_errors") else {}),
                }

        worker_tasks = [
            asyncio.create_task(run_one(index, item))
            for index, item in enumerate(tasks)
        ]
        aggregate = asyncio.gather(*worker_tasks)
        cancel_waiter = asyncio.create_task(cancel_event.wait()) if cancel_event else None
        try:
            if cancel_waiter:
                done, _ = await asyncio.wait(
                    {asyncio.ensure_future(aggregate), cancel_waiter},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if cancel_waiter in done and cancel_event and cancel_event.is_set():
                    for child_cancel in worker_cancels.values():
                        child_cancel.set()
                results = await aggregate
            else:
                results = await aggregate
        finally:
            if cancel_waiter:
                cancel_waiter.cancel()
                await asyncio.gather(cancel_waiter, return_exceptions=True)

        if summarize:
            summary = await call(summarize, results)
        else:
            summary = "; ".join(
                f"{item['title']}: {item['summary']}" for item in results
            )
        if verify:
            from atlas.agent.delegation_output_schema import extract_json_candidate

            criteria = str(verify.get("criteria", "")).strip()
            if not criteria:
                raise ValueError("verify.criteria must be non-empty")
            verdict_schema = {"type": "object", "properties": {
                "verified": {"type": "boolean"}, "note": {"type": "string"},
            }, "required": ["verified", "note"], "additionalProperties": False}
            for index, item in enumerate(results):
                verdict_result = await self.delegate_task(
                    f"验收并行任务 {item['title']}",
                    f"成功标准：{criteria}\n\n任务目标：{tasks[index]['goal']}\n\n产出：{item['summary']}\n\n请仅按标准判断是否通过。",
                    backend="atlas", cwd=cwd, output_schema=verdict_schema,
                    event_metadata={"agent": "verifier", "role": "leaf",
                                    "background": False, "depth": 1},
                    atlas_options=atlas_options,
                    on_started=on_started, on_progress=on_progress,
                    on_completed=on_completed,
                )
                try:
                    verdict = json.loads(extract_json_candidate(str(verdict_result.get("result", ""))))
                except (ValueError, TypeError):
                    verdict = {"verified": False, "note": "verifier returned invalid structured output"}
                item["verified"] = bool(
                    item.get("status") == "completed"
                    and item.get("schema_valid", True) is not False
                    and verdict_result.get("status") == "completed"
                    and verdict.get("verified")
                )
                item["verifier_note"] = str(verdict.get("note", ""))[:1000]
                item["accepted"] = item["verified"]
                if not item["verified"]:
                    retry_task = {**tasks[index], "context": (
                        str(tasks[index].get("context") or "") +
                        f"\n\nVerifier feedback (single retry): {item['verifier_note']}"
                    )}
                    retried = await run_one(index, retry_task)
                    retry_verdict_result = await self.delegate_task(
                        f"复验并行任务 {item['title']}",
                        f"成功标准：{criteria}\n\n任务目标：{tasks[index]['goal']}\n\n重派产出：{retried['summary']}",
                        backend="atlas", cwd=cwd, output_schema=verdict_schema,
                        event_metadata={"agent": "verifier", "role": "leaf",
                                        "background": False, "depth": 1},
                        atlas_options=atlas_options,
                    )
                    try:
                        retry_verdict = json.loads(extract_json_candidate(
                            str(retry_verdict_result.get("result", "")),
                        ))
                    except (ValueError, TypeError):
                        retry_verdict = {"verified": False, "note": "verifier returned invalid structured output"}
                    retried["verified"] = bool(
                        retried.get("status") == "completed"
                        and retried.get("schema_valid", True) is not False
                        and retry_verdict_result.get("status") == "completed"
                        and retry_verdict.get("verified")
                    )
                    retried["verifier_note"] = str(retry_verdict.get("note", ""))[:1000]
                    retried["accepted"] = retried["verified"]
                    results[index] = retried
        else:
            for item in results:
                item["accepted"] = False
                item["verification_status"] = "not_requested"
        payload = {
            "group_id": group_id,
            "results": results,
            "summary": str(summary),
        }
        await call(on_group_completed, payload)
        return payload


async def _call_callback(callback: Callable[..., Any] | None, *args: Any) -> Any:
    if callback is None:
        return None
    value = callback(*args)
    return await value if hasattr(value, "__await__") else value


async def _relay_cancel(parent: asyncio.Event, child: asyncio.Event) -> None:
    await parent.wait()
    child.set()


def _human_subtask_text(value: Any) -> str:
    text = str(value or "").strip().replace("\n", " ")
    return text[:240] or "正在处理子任务"


