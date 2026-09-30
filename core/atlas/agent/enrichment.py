"""Optional Agent lifecycle, context, delegation, CodeAct, and review adapters."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import secrets
import sys
import subprocess
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger()


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
        self._status_cache: dict[str, Any] = {}
        self.atlas_runner: Callable[..., Any] | None = None

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
    ) -> dict[str, Any]:
        if not goal.strip():
            raise ValueError("goal must be non-empty")
        name = backend or executor
        if name == "atlas":
            if self.atlas_runner is None:
                raise RuntimeError("Atlas 子任务执行器尚未就绪。")
            subtask_id = secrets.token_hex(8)
            await self.hooks.emit("subagent_start", goal=goal, backend="atlas")
            started_at = asyncio.get_running_loop().time()
            status, summary = "failed", "子任务没有返回结果。"
            cancel_event = asyncio.Event()
            parent_cancel = (atlas_options or {}).get("cancel_event")
            parent_cancel_task = None
            try:
                start_args = (subtask_id, goal, "atlas")
                registered_cancel = await _call_callback(
                    on_started, *(start_args + ((event_metadata,) if event_metadata is not None else ())),
                )
                if isinstance(registered_cancel, asyncio.Event):
                    cancel_event = registered_cancel
                if parent_cancel is not None:
                    parent_cancel_task = asyncio.create_task(
                        _relay_cancel(parent_cancel, cancel_event),
                    )
                result = await self.atlas_runner(
                    goal=goal, context=context, cwd=cwd, subtask_id=subtask_id,
                    atlas_options={**(atlas_options or {}), "cancel_event": cancel_event},
                    on_progress=lambda text: _call_callback(
                        on_progress, subtask_id, _human_subtask_text(text),
                        *((event_metadata,) if event_metadata is not None else ()),
                    ),
                )
                status = str(result.get("status", "completed"))
                summary = str(result.get("result", ""))[:1000] or "子任务已完成。"
                return {"backend": "atlas", "session_id": None,
                        "subtask_id": subtask_id, "status": status,
                        "result": result.get("result", ""),
                        "evidence": result.get("evidence", [])}
            except asyncio.CancelledError:
                status, summary = "cancelled", "子任务已取消。"
                raise
            except Exception as exc:
                summary = str(exc)[:1000] or summary
                raise
            finally:
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
                cancel = (
                    on_started(subtask_id, goal, name, event_metadata)
                    if event_metadata is not None else on_started(subtask_id, goal, name)
                )
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
    ) -> dict[str, Any]:
        if not isinstance(tasks, list) or not 1 <= len(tasks) <= 8:
            raise ValueError("delegate_parallel accepts one to eight tasks")
        if not isinstance(max_concurrency, int) or not 1 <= max_concurrency <= 4:
            raise ValueError("max_concurrency must be between 1 and 4")
        if any(not isinstance(item, dict) or not str(item.get("goal", "")).strip()
               or not str(item.get("title", "")).strip() for item in tasks):
            raise ValueError("each parallel task requires a title and goal")

        # Pick the worker Agent once: with none installed, fail the whole group up front.
        worker_backend = executor
        group_id = secrets.token_hex(8)
        semaphore = asyncio.Semaphore(max_concurrency)
        worktree_lock = asyncio.Lock()
        worker_cancels: dict[int, asyncio.Event] = {}
        is_git = False
        git_root: Path | None = None
        base_commit: str | None = None
        if cwd:
            probe = await asyncio.to_thread(
                subprocess.run,
                ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, check=False,
            )
            if probe.returncode == 0:
                git_root = Path(probe.stdout.strip()).resolve()
                is_git = True
                head = await asyncio.to_thread(
                    subprocess.run,
                    ["git", "-C", str(git_root), "rev-parse", "HEAD"],
                    capture_output=True, text=True, check=False,
                )
                if head.returncode == 0:
                    base_commit = head.stdout.strip()

        async def call(callback: Callable[..., Any] | None, *args: Any) -> Any:
            if callback is None:
                return None
            value = callback(*args)
            return await value if hasattr(value, "__await__") else value

        async def run_one(index: int, item: dict[str, Any]) -> dict[str, Any]:
            title = str(item["title"])
            goal = str(item["goal"])
            metadata = {"group_id": group_id, "index": index, "title": title}
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
                shared_before: dict[str, str] | None = None
                if is_git and git_root is not None and cwd:
                    worktree = git_root.parent / ".atlas-worktrees" / git_root.name / "parallel" / f"{group_id}-{index}"
                    try:
                        relative_cwd = Path(cwd).resolve().relative_to(git_root)
                    except ValueError:
                        return await setup_failed(
                            "Worker directory is outside the Git repository.",
                        )
                    worktree.parent.mkdir(parents=True, exist_ok=True)
                    async with worktree_lock:
                        add = await asyncio.to_thread(
                            subprocess.run,
                            ["git", "-C", str(git_root), "worktree", "add", "--detach",
                             str(worktree), base_commit or "HEAD"],
                            capture_output=True, text=True, check=False,
                        )
                    if add.returncode:
                        return await setup_failed(
                            add.stderr.strip() or "Could not create worker worktree.",
                        )
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
                elif worktree is not None:
                    worker_context += (
                        "\nThis worker has an isolated git worktree. Do not merge or commit "
                        "your changes; return your patch for coordinator review."
                    )
                try:
                    result = await self.delegate_task(
                        goal, worker_context or None,
                        backend=str(item.get("executor", worker_backend)), cwd=worker_cwd,
                        on_started=started, on_progress=progress, on_completed=completed,
                        event_metadata=metadata, atlas_options=atlas_options,
                    )
                    status = str(result.get("status", "completed"))
                    summary = str(result.get("result", ""))[:1000]
                except asyncio.CancelledError:
                    status, summary, result = "cancelled", "Worker cancelled.", {}
                except Exception as exc:
                    status, summary, result = "failed", str(exc)[:1000], {}

                changed_files: list[str] = []
                patch_text = ""
                if worktree is not None:
                    try:
                        await asyncio.to_thread(
                            subprocess.run,
                            ["git", "-C", str(worktree), "add", "-N", "--all"],
                            capture_output=True, text=True, check=False,
                        )
                        status_result = await asyncio.to_thread(
                            subprocess.run,
                            ["git", "-C", str(worktree), "status", "--porcelain"],
                            capture_output=True, text=True, check=False,
                        )
                        changed_files = [
                            line[3:].strip().replace("\\", "/")
                            for line in status_result.stdout.splitlines() if len(line) > 3
                        ]
                        committed = await asyncio.to_thread(
                            subprocess.run,
                            ["git", "-C", str(worktree), "diff", "--name-only",
                             base_commit or "HEAD"],
                            capture_output=True, text=True, check=False,
                        )
                        changed_files = sorted(set(changed_files) | {
                            line.strip().replace("\\", "/")
                            for line in committed.stdout.splitlines() if line.strip()
                        })
                        diff = await asyncio.to_thread(
                            subprocess.run,
                            ["git", "-C", str(worktree), "diff", "--binary",
                             base_commit or "HEAD"],
                            capture_output=True, text=True, check=False,
                        )
                        patch_text = diff.stdout
                    finally:
                        async with worktree_lock:
                            await asyncio.to_thread(
                                subprocess.run,
                                ["git", "-C", str(git_root), "worktree", "remove",
                                 "--force", str(worktree)],
                                capture_output=True, text=True, check=False,
                            )
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
