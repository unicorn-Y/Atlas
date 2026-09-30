"""Optional Agent lifecycle, context, delegation, CodeAct, and review adapters."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import secrets
import sys
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger()

HOOK_POINTS = (
    "before_model", "after_model", "before_tool", "after_tool", "before_compact",
    "after_compact", "before_response", "after_response", "agent_stop",
    "subagent_start", "subagent_end",
)


class HookBus:
    """Ordered, optional lifecycle hooks. A failing hook never blocks Agent work."""

    def __init__(self) -> None:
        self._hooks: dict[str, list[Callable[..., Any]]] = defaultdict(list)

    def register(self, point: str, handler: Callable[..., Any]) -> None:
        if point not in HOOK_POINTS:
            raise ValueError(f"Unknown hook point: {point}")
        self._hooks[point].append(handler)

    async def emit(self, point: str, **payload: Any) -> list[dict[str, str]]:
        if point not in HOOK_POINTS:
            raise ValueError(f"Unknown hook point: {point}")
        errors: list[dict[str, str]] = []
        for handler in tuple(self._hooks[point]):
            try:
                result = handler(**payload)
                if hasattr(result, "__await__"):
                    await result
            except Exception as exc:
                item = {"hook": getattr(handler, "__name__", repr(handler)), "error": str(exc)}
                errors.append(item)
                log.warning("agent.hook.failed", point=point, **item)
        return errors


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
        read_only: bool = False,
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
                    log.warning("agent.checkpoint.failed", path=str(target), error=str(exc))


class CodeActRuntime:
    """Run short Python workflows in a child process with a loopback Atlas tool bridge."""

    def __init__(self, bridge: AtlasToolBridge, *, timeout: float = 30.0) -> None:
        self.bridge = bridge
        self.timeout = max(0.1, min(timeout, 120.0))

    async def execute(
        self, code: str, *, run_id: str | None = None,
        conversation_id: str | None = None,
        tool_allow: list[str] | None = None, tool_deny: list[str] | None = None,
        read_only: bool = False,
    ) -> dict[str, Any]:
        if not isinstance(code, str) or not code.strip():
            raise ValueError("code must be non-empty text")
        token = secrets.token_urlsafe(24)
        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
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
                result = await self.bridge.call_tool(
                    str(request["name"]), dict(request.get("arguments", {})),
                    run_id=run_id, conversation_id=conversation_id,
                    tool_allow=tool_allow, tool_deny=tool_deny, read_only=read_only,
                )
                payload = json.dumps(result, ensure_ascii=False, default=str).encode("utf-8")
                response_body = len(payload).to_bytes(4, "big") + payload
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\n"
                    + f"Content-Length: {len(response_body)}\r\nConnection: close\r\n\r\n".encode()
                    + response_body
                )
                await writer.drain()
            except Exception as exc:
                payload = json.dumps({"error": str(exc), "is_error": True}).encode()
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
        runner = (
            "import asyncio,json,sys,urllib.request\n"
            f"TOKEN={token!r}\nPORT={port}\n"
            "class Bridge:\n"
            " def call_tool(self,name,arguments=None):\n"
            "  body=json.dumps({'token':TOKEN,'name':name,'arguments':arguments or {}}).encode()\n"
            "  req=urllib.request.Request(f'http://127.0.0.1:{PORT}/',data=body,method='POST')\n"
            "  with urllib.request.urlopen(req,timeout=15) as r: data=r.read()\n"
            "  n=int.from_bytes(data[:4],'big'); return json.loads(data[4:4+n])\n"
            "atlas=Bridge()\n"
            "async def _run():\n"
            " ns={'atlas':atlas}\n"
            " exec(compile(sys.stdin.read(),'<atlas-codeact>','exec'),ns,ns)\n"
            " result=ns.get('result')\n"
            " if asyncio.iscoroutine(result): result=await result\n"
            " print('ATLAS_RESULT:'+json.dumps(result,ensure_ascii=False,default=str))\n"
            "asyncio.run(_run())\n"
        )
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-u", "-c", runner,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(code.encode("utf-8")), timeout=self.timeout,
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            raise TimeoutError(f"CodeAct exceeded {self.timeout:g}s") from None
        finally:
            server.close()
            await server.wait_closed()
        out = stdout.decode("utf-8", errors="replace")[-16000:]
        err = stderr.decode("utf-8", errors="replace")[-8000:]
        result: Any = None
        for line in out.splitlines():
            if line.startswith("ATLAS_RESULT:"):
                with contextlib.suppress(json.JSONDecodeError):
                    result = json.loads(line.removeprefix("ATLAS_RESULT:"))
        return {"exit_code": process.returncode, "stdout": out, "stderr": err, "result": result}


class DelegationService:
    """One disposable child session using Atlas's existing AgentBackendHost."""

    def __init__(self, host: Any, hooks: HookBus, *, timeout: float = 90.0) -> None:
        self.host, self.hooks, self.timeout = host, hooks, timeout

    async def delegate_task(
        self, goal: str, context: str | None = None, tool_profile: list[str] | None = None,
        *, backend: str | None = None, cwd: str | None = None,
        on_started: Callable[..., Any] | None = None,
        on_progress: Callable[..., Any] | None = None,
        on_completed: Callable[..., Any] | None = None,
    ) -> dict[str, Any]:
        if not goal.strip():
            raise ValueError("goal must be non-empty")
        name = backend or (
            "hermes" if "hermes" in self.host.backends else next(iter(self.host.backends))
        )
        await self.hooks.emit("subagent_start", goal=goal, backend=name)
        session = None
        subtask_id = secrets.token_hex(8)
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
                cancel = on_started(subtask_id, goal, name)
                if hasattr(cancel, "__await__"):
                    cancel = await cancel
                if isinstance(cancel, asyncio.Event):
                    cancel_event = cancel
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
                        progress = on_progress(subtask_id, text)
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
            return {"backend": name, "session_id": session.id, "subtask_id": subtask_id, "status": status, "result": text,
                    "evidence": events}
        except asyncio.TimeoutError:
            status = "failed"
            raise
        except Exception as exc:
            completion_summary = str(exc)[:1000] or completion_summary
            raise
        finally:
            if cancel_event.is_set():
                status = "cancelled"
            if session is not None:
                await self.host.close(session.id)
            await self.hooks.emit(
                "subagent_end", goal=goal, backend=name,
                session_id=session.id if session is not None else None,
            )
            if on_completed:
                completed = on_completed(subtask_id, status, completion_summary,
                                         int((asyncio.get_running_loop().time() - started_at) * 1000))
                if hasattr(completed, "__await__"):
                    await completed


class MemoryReflectionBridge:
    """Turn completed-task evidence into governed MemoryOS candidates, never promotions."""

    def __init__(self, memory: Any) -> None:
        self.memory = memory

    async def reflect(
        self, *, conversation_id: str, goal: str, task_result: str,
        reviewer_evidence: list[dict[str, Any]] | None = None,
        memory_candidates: list[dict[str, Any]] | None = None,
        source_run_id: str | None = None,
    ) -> dict[str, Any]:
        candidates = [{
            "type": "experience", "category": "reusable_experience",
            "summary": task_result.strip()[:500], "goal": goal,
            "reviewer_evidence": reviewer_evidence or [],
            "status": "proposed", "advisory_only": True,
        }]
        labels = {
            "fact memory": "fact", "project state": "project_state",
            "decision": "decision", "preference": "preference",
        }
        for line in task_result.splitlines():
            key, separator, value = line.partition(":")
            category = labels.get(key.strip().casefold())
            if separator and category and value.strip():
                candidates.append({
                    "type": category, "category": category,
                    "summary": value.strip()[:500], "goal": goal,
                    "reviewer_evidence": reviewer_evidence or [],
                    "status": "proposed", "advisory_only": True,
                })
        if conversation_id:
            candidates[0]["memory_candidates"] = memory_candidates
            if memory_candidates is None:
                candidates[0]["memory_candidates"] = (
                    await self.memory.extract_conversation_candidates(conversation_id)
                )
            persist = getattr(type(self.memory), "persist_reflection_proposals", None)
            if callable(persist):
                proposal_ids = await self.memory.persist_reflection_proposals(
                    candidates, conversation_id=conversation_id,
                    source_run_id=source_run_id,
                    reviewer_evidence=reviewer_evidence or [],
                )
                for candidate, proposal_id in zip(candidates, proposal_ids):
                    candidate["proposal_id"] = proposal_id
        return {"candidates": candidates, "promoted": False}
