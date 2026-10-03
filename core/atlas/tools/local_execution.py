"""Atlas-owned FULL_ACCESS local shell, process, filesystem, and Git tools.

Hermes process actions adapted from tools/process_registry.py@562ad75:
write, submit, close, and handoff map to Atlas process IDs and the shared local
execution runtime. Windows PTY input/output uses the existing optional pywinpty.
"""

from __future__ import annotations

import asyncio
import base64
import codecs
import glob as glob_module
import json
import math
import os
import shutil
import signal
import subprocess
import tempfile
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from atlas.config import get_config

log = structlog.get_logger()
OutputCallback = Callable[[str, str, str], Awaitable[None] | None]


def _find_git_bash() -> str | None:
    """Find MSYS/Git Bash, preferring the installation paired with Git on PATH."""
    candidates: list[Path] = []
    git = shutil.which("git.exe") or shutil.which("git")
    if git:
        git_root = Path(git).resolve().parent.parent
        candidates.extend((git_root / "bin" / "bash.exe", git_root / "usr" / "bin" / "bash.exe"))
    for candidate in (shutil.which("bash.exe"), shutil.which("bash")):
        if candidate:
            candidates.append(Path(candidate))
    for candidate in candidates:
        normalized = str(candidate).lower().replace("/", "\\")
        if os.name == "nt" and ("\\windowsapps\\" in normalized or "\\system32\\" in normalized):
            continue
        if candidate.is_file() or shutil.which(str(candidate)):
            return str(candidate)
    return None


def _effective_shell(shell: str, git_bash: str | None, *, windows: bool) -> tuple[str, str | None]:
    if shell == "auto":
        if git_bash:
            return "bash", git_bash
        return ("powershell", None) if windows else ("bash", None)
    if shell == "bash":
        if windows and not git_bash:
            raise ValueError("Git Bash is not installed; choose PowerShell or cmd explicitly.")
        return "bash", git_bash
    return shell, None


def _tool(
    name: str, description: str, properties: dict[str, Any], required: list[str]
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


LOCAL_TOOLS = [
    _tool(
        "local_shell",
        (
            "Run a command locally. Windows defaults to Git Bash, then PowerShell. Set cwd for any accessible directory. "
            "Nonzero exit codes are returned as results."
        ),
        {
            "shell": {"type": "string", "enum": ["powershell", "cmd", "bash"]},
            "command": {"type": "string"},
            "cwd": {"type": "string"},
            "env": {"type": "object", "additionalProperties": {"type": "string"}},
            "stdin": {"type": "string"},
            "timeout": {"type": "number"},
            "detached": {"type": "boolean"},
            "keep_stdin": {"type": "boolean"},
            "pty": {"type": "boolean"},
        },
        ["shell", "command"],
    ),
    _tool(
        "local_exec",
        (
            "Run an installed local executable with argv (without shell quoting). Supports "
            "Python, Node, npm, npx, Git, and other commands."
        ),
        {
            "executable": {"type": "string"},
            "args": {"type": "array", "items": {"type": "string"}},
            "cwd": {"type": "string"},
            "env": {"type": "object", "additionalProperties": {"type": "string"}},
            "stdin": {"type": "string"},
            "timeout": {"type": "number"},
            "detached": {"type": "boolean"},
        },
        ["executable"],
    ),
    _tool(
        "local_process",
        (
            "Start, inspect, read full stdout/stderr logs, wait for, cancel, or list processes "
            "started by Atlas, and write, submit, close stdin, or hand off a running process."
        ),
        {
            "action": {
                "type": "string",
                "enum": [
                    "start", "status", "read", "wait", "cancel", "list",
                    "write_stdin", "submit_stdin", "close_stdin", "handoff",
                ],
            },
            "execution_id": {"type": "string"},
            "executable": {"type": "string"},
            "args": {"type": "array", "items": {"type": "string"}},
            "shell": {"type": "string", "enum": ["powershell", "cmd", "bash"]},
            "command": {"type": "string"},
            "cwd": {"type": "string"},
            "env": {"type": "object", "additionalProperties": {"type": "string"}},
            "stdin": {"type": "string"},
            "timeout": {"type": "number"},
            "detached": {"type": "boolean"},
            "keep_stdin": {"type": "boolean"},
            "pty": {"type": "boolean"},
            "data": {"type": "string"},
            "stream": {"type": "string", "enum": ["stdout", "stderr"]},
            "offset": {"type": "integer", "minimum": 0},
            "limit": {"type": "integer", "minimum": 1, "maximum": 65536},
        },
        ["action"],
    ),
    _tool(
        "local_file",
        (
            "Read, write, append, list, search, create, copy, move, stat, glob, and delete files "
            "or directories at arbitrary local paths."
        ),
        {
            "action": {
                "type": "string",
                "enum": [
                    "read",
                    "write",
                    "append",
                    "mkdir",
                    "copy",
                    "move",
                    "delete",
                    "list",
                    "glob",
                    "search",
                    "stat",
                ],
            },
            "path": {"type": "string"},
            "destination": {"type": "string"},
            "cwd": {"type": "string"},
            "content": {"type": "string"},
            "encoding": {"type": "string"},
            "binary": {"type": "boolean"},
            "recursive": {"type": "boolean"},
            "pattern": {"type": "string"},
            "query": {"type": "string"},
        },
        ["action", "path"],
    ),
    _tool(
        "local_edit",
        (
            "Make a precise string-replacement edit in an existing text file. "
            "You must local_file-read the file first; old_string must match exactly "
            "and uniquely unless replace_all is set."
        ),
        {
            "path": {"type": "string"},
            "old_string": {"type": "string"},
            "new_string": {"type": "string"},
            "replace_all": {"type": "boolean"},
            "encoding": {"type": "string"},
            "cwd": {"type": "string"},
        },
        ["path", "old_string", "new_string"],
    ),
    _tool(
        "local_git",
        (
            "Use the installed Git CLI in any local repository. Supports status, diff, log, "
            "branch, add, commit, pull, fetch, and push."
        ),
        {
            "action": {
                "type": "string",
                "enum": [
                    "status",
                    "diff",
                    "log",
                    "branch",
                    "add",
                    "commit",
                    "pull",
                    "fetch",
                    "push",
                ],
            },
            "repo": {"type": "string"},
            "args": {"type": "array", "items": {"type": "string"}},
            "message": {"type": "string"},
            "paths": {"type": "array", "items": {"type": "string"}},
            "timeout": {"type": "number"},
        },
        ["action", "repo"],
    ),
]


class _PtyReader:
    def __init__(self, process: Any) -> None:
        self.process = process

    async def read(self, size: int) -> bytes:
        try:
            value = await asyncio.to_thread(self.process.read, size)
        except EOFError:
            return b""
        return value.encode("utf-8")


class _PtyWriter:
    def __init__(self, process: Any) -> None:
        self.process = process
        self._pending = bytearray()
        self._closing = False

    def write(self, data: bytes) -> None:
        if self._closing:
            raise ValueError("PTY stdin is closed")
        self._pending.extend(data)

    async def drain(self) -> None:
        payload = bytes(self._pending).decode("utf-8", errors="replace")
        self._pending.clear()
        if payload:
            await asyncio.to_thread(self.process.write, payload)

    def is_closing(self) -> bool:
        return self._closing

    def close(self) -> None:
        self._closing = True

    async def wait_closed(self) -> None:
        if self._closing:
            await asyncio.to_thread(self.process.sendcontrol, "z")
            await asyncio.to_thread(self.process.write, "\r")


class _AsyncPtyProcess:
    def __init__(self, process: Any) -> None:
        self._pty = process
        self.pid = process.pid
        self.returncode: int | None = None
        self.stdin = _PtyWriter(process)
        self.stdout = _PtyReader(process)
        self.stderr = None

    async def wait(self) -> int:
        if self.returncode is None:
            self.returncode = await asyncio.to_thread(self._pty.wait)
        return self.returncode or 0

    def send_signal(self, _signal: int) -> None:
        self._pty.sendintr()


@dataclass
class LocalProcess:
    execution_id: str
    process: Any
    command: str
    cwd: str
    started_monotonic: float
    started_at: str
    owner_run_id: str | None
    detached: bool
    state: str = "running"
    exit_code: int | None = None
    stdout_path: Path = field(default_factory=Path)
    stderr_path: Path = field(default_factory=Path)
    stdout_size: int = 0
    stderr_size: int = 0
    pump_tasks: list[asyncio.Task[None]] = field(default_factory=list)
    wait_task: asyncio.Task[None] | None = None
    cancelled: bool = False
    handoff_note: str = ""
    notification_callback: Any = None
    conversation_id: str = ""
    notification_task: asyncio.Task[None] | None = None
    notification_sequence: int = 0
    notify_on_complete: bool = False
    watch_patterns: list[str] = field(default_factory=list)
    watch_tail: str = ""

    def summary(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "pid": self.process.pid,
            "command": self.command,
            "cwd": self.cwd,
            "state": self.state,
            "exit_code": self.exit_code,
            "started_at": self.started_at,
            "duration_seconds": round(time.monotonic() - self.started_monotonic, 3),
            "detached": self.detached,
            "handoff_note": self.handoff_note,
        }


class LocalExecutionRuntime:
    """Owns only processes it starts and exposes arbitrary-path local tools."""

    def __init__(self, output_callback: OutputCallback | None = None) -> None:
        self.permission_mode = get_config().local_execution_permission_mode
        self.output_callback = output_callback
        self._processes: dict[str, LocalProcess] = {}
        self._closed = False
        self._read_paths: set[str] = set()

    def get_tools_for_llm(self) -> list[dict[str, Any]]:
        return LOCAL_TOOLS

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        run_id: str | None = None,
        output_callback: OutputCallback | None = None,
        event_callback: Any = None,
    ) -> dict[str, Any]:
        args = arguments or {}
        output_callback = output_callback or self.output_callback
        if self.permission_mode != "full_access":
            return self._error(
                f"Local execution is disabled by permission_mode={self.permission_mode!r}."
            )
        if self._closed:
            return self._error("Local execution runtime is shutting down.")
        try:
            self._validate_execution_args(name, args)
            if name == "local_file":
                data = await asyncio.to_thread(self._file_operation, args)
            elif name == "local_edit":
                data = await asyncio.to_thread(self._edit_operation, args)
            elif name == "local_git":
                data = await self._git_operation(args, run_id, output_callback)
            elif name == "local_shell":
                process = await self._start_from_shell(args, run_id, output_callback)
                self._configure_notifications(
                    process, args, event_callback, str(args.get("_atlas_conversation_id") or ""),
                )
                return await self._execute_or_detach(process, args)
            elif name == "local_exec":
                process = await self._start_from_exec(args, run_id, output_callback)
                self._configure_notifications(
                    process, args, event_callback, str(args.get("_atlas_conversation_id") or ""),
                )
                return await self._execute_or_detach(process, args)
            elif name == "local_process":
                return await self._process_operation(args, run_id, output_callback, event_callback)
            else:
                return self._error(f"Unknown local tool: {name}")
            return {
                "data": data,
                "content": [{"type": "text", "text": str(data)}],
                "is_error": False,
            }
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("local_execution.tool_failed", tool=name, error=str(exc))
            return self._error(f"{type(exc).__name__}: {exc}")

    @staticmethod
    def _validate_execution_args(name: str, args: dict[str, Any]) -> None:
        if name not in {"local_shell", "local_exec", "local_process"}:
            return
        for key in ("timeout", "heartbeat"):
            if key not in args or args[key] in (None, ""):
                continue
            if isinstance(args[key], bool):
                raise ValueError(f"{key} must be a finite non-negative number")
            try:
                value = float(args[key])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{key} must be a finite non-negative number") from exc
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{key} must be a finite non-negative number")
        if (
            name in {"local_shell", "local_process"}
            and args.get("shell") not in {None, "auto", "powershell", "cmd", "bash"}
        ):
            raise ValueError(f"Unsupported shell: {args['shell']}")
        patterns = args.get("watch_patterns", [])
        if patterns is not None and (
            not isinstance(patterns, list) or not all(isinstance(item, str) for item in patterns)
        ):
            raise ValueError("watch_patterns must be a list of strings")
        notify = args.get("notify")
        if notify is not None and not isinstance(notify, (bool, list)):
            raise ValueError("notify must be a boolean or list of strings")
        if isinstance(notify, list) and not all(isinstance(item, str) for item in notify):
            raise ValueError("notify patterns must be strings")

    def _configure_notifications(
        self, record: LocalProcess, args: dict[str, Any], callback: Any, conversation_id: str = "",
    ) -> None:
        record.notification_callback = callback
        record.conversation_id = conversation_id
        notify = args.get("notify")
        record.notify_on_complete = bool(args.get("notify_on_complete"))
        record.watch_patterns = list(args.get("watch_patterns") or [])
        if isinstance(notify, bool):
            record.notify_on_complete = notify
        elif isinstance(notify, list):
            # Extend (not clobber): explicit watch_patterns and notify:[...] compose.
            record.watch_patterns = record.watch_patterns + [str(item) for item in notify]
        heartbeat = float(args.get("heartbeat") or 0)
        if heartbeat > 0 and (callback is not None or conversation_id):
            record.notify_on_complete = True
            record.notification_task = asyncio.create_task(self._heartbeat(record, heartbeat))

    async def _notify(self, record: LocalProcess, reason: str, text: str = "") -> None:
        record.notification_sequence += 1
        source_id = f"{record.execution_id}:{reason}:{record.notification_sequence}"
        event = {
            "type": "process.completed" if reason == "completion" else "process.notification",
            "data": {**record.summary(), "reason": reason, "text": text, "source_id": source_id},
            }
        callback_failed = False
        if record.notification_callback is not None:
            try:
                result = record.notification_callback(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                callback_failed = True
                log.warning(
                    "local_execution.notification_callback_failed",
                    execution_id=record.execution_id,
                )
        if record.conversation_id and (record.notification_callback is None or callback_failed):
            try:
                from atlas.engine.notifications import publish_notification

                publish_notification(
                    record.conversation_id,
                    kind=event["type"],
                    content=json.dumps(event["data"], ensure_ascii=False),
                    source_id=source_id,
                )
            except Exception:
                log.warning(
                    "local_execution.notification_persist_failed",
                    execution_id=record.execution_id,
                )

    async def _heartbeat(self, record: LocalProcess, seconds: float) -> None:
        while record.state == "running":
            await asyncio.sleep(seconds)
            if record.state == "running":
                await self._notify(record, "heartbeat", "后台进程仍在运行。")

    @staticmethod
    def _error(message: str) -> dict[str, Any]:
        return {
            "data": {"error": message},
            "content": [{"type": "text", "text": message}],
            "is_error": True,
        }

    @staticmethod
    def _error(message: str) -> dict[str, Any]:
        return {
            "data": {"error": message},
            "content": [{"type": "text", "text": message}],
            "is_error": True,
        }

    def _edit_operation(self, args: dict[str, Any]) -> dict[str, Any]:
        """Precise string-replacement edit: read-before-edit + uniqueness."""
        path = self._path(args.get("path"), args.get("cwd"))
        old_string = str(args.get("old_string", ""))
        new_string = str(args.get("new_string", ""))
        replace_all = bool(args.get("replace_all", False))
        if not old_string:
            raise ValueError("old_string is required (use local_file write for new files)")
        if str(path) not in self._read_paths:
            raise ValueError(
                f"read the file first with local_file action=read ({path})"
            )
        content = path.read_text(encoding=str(args.get("encoding", "utf-8")))
        count = content.count(old_string)
        if count == 0:
            raise ValueError("old_string not found in file (file may have changed)")
        if count > 1 and not replace_all:
            raise ValueError(
                f"old_string matches {count} locations; add more context or set replace_all"
            )
        updated = content.replace(old_string, new_string) if replace_all else (
            content.replace(old_string, new_string, 1)
        )
        path.write_text(updated, encoding=str(args.get("encoding", "utf-8")))
        replacements = count if replace_all else 1
        return {
            "path": str(path),
            "replacements": replacements,
            "size": len(updated.encode(str(args.get("encoding", "utf-8")))),
        }

    @staticmethod
    def _path(raw: str | None, cwd: str | None = None) -> Path:
        if not raw:
            raise ValueError("path is required")
        expanded = Path(os.path.expandvars(os.path.expanduser(raw)))
        if not expanded.is_absolute():
            expanded = Path(cwd or os.getcwd()) / expanded
        return expanded.resolve()

    def _file_operation(self, args: dict[str, Any]) -> dict[str, Any]:
        action = args["action"]
        path = self._path(args.get("path"), args.get("cwd"))
        encoding = str(args.get("encoding", "utf-8"))
        if action == "read":
            raw = path.read_bytes()
            self._read_paths.add(str(path))
            return {
                "path": str(path),
                "size": len(raw),
                "content": base64.b64encode(raw).decode("ascii")
                if args.get("binary")
                else raw.decode(encoding),
                "encoding": "base64" if args.get("binary") else encoding,
            }
        if action in ("write", "append"):
            path.parent.mkdir(parents=True, exist_ok=True)
            mode = "ab" if action == "append" else "wb"
            with path.open(mode) as stream:
                stream.write(str(args.get("content", "")).encode(encoding))
            return {"path": str(path), "size": path.stat().st_size}
        if action == "mkdir":
            path.mkdir(parents=True, exist_ok=True)
            return {"path": str(path), "is_dir": True}
        if action in ("copy", "move"):
            destination = self._path(args.get("destination"), args.get("cwd"))
            destination.parent.mkdir(parents=True, exist_ok=True)
            result = (
                shutil.copy2(path, destination) if action == "copy" and path.is_file() else None
            )
            if action == "copy" and path.is_dir():
                result = shutil.copytree(path, destination, dirs_exist_ok=True)
            if action == "move":
                result = shutil.move(str(path), str(destination))
            return {
                "path": str(path),
                "destination": str(destination),
                "result": str(result or destination),
            }
        if action == "delete":
            if path.is_dir() and not path.is_symlink():
                if args.get("recursive", True):
                    shutil.rmtree(path)
                else:
                    path.rmdir()
            else:
                path.unlink()
            return {"path": str(path), "deleted": True}
        if action == "list":
            return {
                "path": str(path),
                "entries": [
                    {"name": item.name, "path": str(item), "is_dir": item.is_dir()}
                    for item in sorted(path.iterdir(), key=lambda item: item.name.casefold())
                ],
            }
        if action == "glob":
            pattern = args.get("pattern", "*")
            matches = glob_module.glob(str(path / pattern), recursive=True)
            return {"path": str(path), "matches": matches}
        if action == "search":
            query = str(args.get("query", ""))
            matches: list[dict[str, Any]] = []
            for item in path.rglob("*") if path.is_dir() else [path]:
                if not item.is_file():
                    continue
                try:
                    for number, line in enumerate(
                        item.read_text(encoding=encoding).splitlines(), 1
                    ):
                        if query in line:
                            matches.append({"path": str(item), "line": number, "text": line})
                except (OSError, UnicodeError):
                    continue
            return {"path": str(path), "matches": matches}
        if action == "stat":
            if not path.exists():
                return {"path": str(path), "exists": False}
            stat = path.stat()
            return {
                "path": str(path),
                "exists": True,
                "is_file": path.is_file(),
                "is_dir": path.is_dir(),
                "size": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
            }
        raise ValueError(f"Unsupported file action: {action}")

    async def _git_operation(
        self,
        args: dict[str, Any],
        run_id: str | None,
        callback: OutputCallback | None,
    ) -> dict[str, Any]:
        action = args["action"]
        base_args: dict[str, list[str]] = {
            "status": ["status", "--short", "--branch"],
            "diff": ["diff"],
            "log": ["log", "-10", "--oneline", "--decorate"],
            "branch": ["branch", "--show-current"],
            "add": ["add"],
            "commit": ["commit", "-m", str(args.get("message", "Atlas change"))],
            "pull": ["pull"],
            "fetch": ["fetch"],
            "push": ["push"],
        }
        if action not in base_args:
            raise ValueError(f"Unsupported Git action: {action}")
        command = base_args[action]
        if action == "add":
            command.extend([str(item) for item in args.get("paths", ["."])])
        command.extend([str(item) for item in args.get("args", [])])
        process = await self._spawn(
            ["git", *command],
            cwd=self._path(args["repo"]),
            env=None,
            stdin=None,
            detached=False,
            run_id=run_id,
            callback=callback,
        )
        waited = await self._wait_result(process, args.get("timeout"))
        result = waited["data"]
        result["action"] = action
        result["repo"] = str(self._path(args["repo"]))
        return result

    async def _start_from_shell(
        self, args: dict[str, Any], run_id: str | None, callback: OutputCallback | None
    ) -> LocalProcess:
        shell = args["shell"]
        command = str(args["command"])
        shell, resolved_bash = _effective_shell(
            shell, _find_git_bash(), windows=os.name == "nt",
        )
        if shell == "powershell":
            executable = shutil.which("powershell.exe") or shutil.which("pwsh") or "powershell.exe"
            utf8 = (
                "$utf8 = [Text.UTF8Encoding]::new(); "
                "[Console]::OutputEncoding = $utf8; $OutputEncoding = $utf8; "
            )
            argv = [
                executable,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                utf8 + command,
            ]
        elif shell == "cmd":
            argv = [
                os.environ.get("COMSPEC", "cmd.exe"),
                "/d",
                "/s",
                "/c",
                f"chcp 65001>nul & {command}",
            ]
        elif shell == "bash":
            executable = resolved_bash or shutil.which("bash")
            if not executable:
                raise ValueError("bash executable was not found")
            argv = [executable, "-lc", command]
        else:
            raise ValueError(f"Unsupported shell: {shell}")
        return await self._spawn(
            argv,
            self._path(args.get("cwd")) if args.get("cwd") else Path.cwd(),
            args.get("env"),
            args.get("stdin"),
            bool(args.get("detached")),
            run_id,
            callback,
            bool(args.get("keep_stdin")),
            bool(args.get("pty")),
        )

    async def _start_from_exec(
        self, args: dict[str, Any], run_id: str | None, callback: OutputCallback | None
    ) -> LocalProcess:
        executable = os.path.expandvars(os.path.expanduser(str(args["executable"])))
        command_args = [str(item) for item in args.get("args", [])]
        resolved = shutil.which(executable) or executable
        suffix = Path(resolved).suffix.lower()
        if os.name == "nt" and suffix in {".cmd", ".bat"}:
            argv = self._windows_batch_argv(resolved, command_args)
        else:
            argv = [resolved, *command_args]
        return await self._spawn(
            argv,
            self._path(args.get("cwd")) if args.get("cwd") else Path.cwd(),
            args.get("env"),
            args.get("stdin"),
            bool(args.get("detached")),
            run_id,
            callback,
            bool(args.get("keep_stdin")),
            bool(args.get("pty")),
        )

    @staticmethod
    def _windows_batch_argv(executable: str, args: list[str]) -> list[str]:
        """Launch a Windows batch command with Windows argv quoting rules."""
        payload = base64.b64encode(
            json.dumps({"executable": executable, "args": args}).encode("utf-8")
        ).decode("ascii")
        script = (
            "$utf8 = [Text.UTF8Encoding]::new(); "
            "[Console]::OutputEncoding = $utf8; $OutputEncoding = $utf8; "
            f"$payload = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{payload}')) "
            "| ConvertFrom-Json; & $payload.executable @($payload.args); "
            "if ($null -ne $LASTEXITCODE) { exit $LASTEXITCODE }"
        )
        encoded_script = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        shell = shutil.which("powershell.exe") or shutil.which("pwsh") or "powershell.exe"
        return [
            shell,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            encoded_script,
        ]

    async def _spawn(
        self,
        argv: list[str],
        cwd: Path,
        env: dict[str, str] | None,
        stdin: str | None,
        detached: bool,
        run_id: str | None,
        callback: OutputCallback | None,
        keep_stdin: bool = False,
        pty: bool = False,
    ) -> LocalProcess:
        if not cwd.is_dir():
            raise NotADirectoryError(str(cwd))
        process_env = os.environ.copy()
        process_env.update({str(k): str(v) for k, v in (env or {}).items()})
        process_env.setdefault("PYTHONUTF8", "1")
        process_env.setdefault("PYTHONIOENCODING", "utf-8")
        kwargs: dict[str, Any] = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        if pty:
            if os.name != "nt":
                raise ValueError("PTY-backed terminals are available only on Windows.")
            try:
                from winpty import PtyProcess
            except ImportError as exc:
                raise ValueError("pywinpty is required for PTY-backed terminals.") from exc
            native_process = await asyncio.to_thread(
                PtyProcess.spawn, argv, cwd=str(cwd), env=process_env,
            )
            proc = _AsyncPtyProcess(native_process)
        else:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(cwd),
                env=process_env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                **kwargs,
            )
        execution_id = str(uuid.uuid4())
        stdout_file = tempfile.NamedTemporaryFile(prefix=f"atlas-{execution_id}-out-", delete=False)
        stderr_file = tempfile.NamedTemporaryFile(prefix=f"atlas-{execution_id}-err-", delete=False)
        stdout_path, stderr_path = Path(stdout_file.name), Path(stderr_file.name)
        stdout_file.close()
        stderr_file.close()
        record = LocalProcess(
            execution_id=execution_id,
            process=proc,
            command=" ".join(argv),
            cwd=str(cwd),
            started_monotonic=time.monotonic(),
            started_at=datetime.now(UTC).isoformat(),
            owner_run_id=run_id,
            detached=detached,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
        self._processes[execution_id] = record
        record.pump_tasks = [
            asyncio.create_task(self._pump(record, "stdout", proc.stdout, callback)),
            asyncio.create_task(self._pump(record, "stderr", proc.stderr, callback)),
        ]
        if stdin is not None and proc.stdin is not None:
            proc.stdin.write(stdin.encode("utf-8"))
            await proc.stdin.drain()
        if proc.stdin and not keep_stdin:
            proc.stdin.close()
            await proc.stdin.wait_closed()
        record.wait_task = asyncio.create_task(self._watch(record))
        log.info(
            "local_execution.started",
            execution_id=execution_id,
            pid=proc.pid,
            cwd=str(cwd),
            detached=detached,
        )
        return record

    async def _pump(
        self,
        record: LocalProcess,
        name: str,
        reader: asyncio.StreamReader | None,
        callback: OutputCallback | None,
    ) -> None:
        if reader is None:
            return
        path = record.stdout_path if name == "stdout" else record.stderr_path
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        while chunk := await reader.read(4096):
            with path.open("ab") as stream:
                stream.write(chunk)
            if name == "stdout":
                record.stdout_size += len(chunk)
            else:
                record.stderr_size += len(chunk)
            text = decoder.decode(chunk)
            if record.watch_patterns:
                watched = record.watch_tail + text
                matches = [pattern for pattern in record.watch_patterns if pattern in watched]
                if matches:
                    await self._notify(record, "watch", watched[-4096:])
                    record.watch_patterns = [pattern for pattern in record.watch_patterns if pattern not in matches]
                record.watch_tail = watched[-4096:]
            if callback is not None:
                try:
                    result = callback(record.execution_id, name, text)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:
                    log.debug(
                        "local_execution.output_callback_failed", execution_id=record.execution_id
                    )
        if callback is not None:
            remainder = decoder.decode(b"", final=True)
            if remainder:
                result = callback(record.execution_id, name, remainder)
                if asyncio.iscoroutine(result):
                    await result

    async def _watch(self, record: LocalProcess) -> None:
        try:
            record.exit_code = await record.process.wait()
            await asyncio.gather(*record.pump_tasks)
            native_pty = getattr(record.process, "_pty", None)
            if native_pty is not None:
                await asyncio.to_thread(native_pty.close)
            if record.cancelled:
                record.state = "cancelled"
            elif record.exit_code == 0:
                record.state = "exited"
            else:
                record.state = "exited"
            if record.notification_task is not None:
                record.notification_task.cancel()
                await asyncio.gather(record.notification_task, return_exceptions=True)
            if record.notify_on_complete:
                await self._notify(record, "completion")
        except asyncio.CancelledError:
            raise
        except Exception:
            record.state = "failed"
            raise

    async def _wait_result(
        self, record: LocalProcess, timeout: float | None = None
    ) -> dict[str, Any]:
        try:
            if timeout is None:
                await record.wait_task
            else:
                await asyncio.wait_for(asyncio.shield(record.wait_task), timeout=float(timeout))
        except TimeoutError:
            await self._cancel_process(record)
            result = self._result(record)
            result["timed_out"] = True
            return result
        except asyncio.CancelledError:
            await self._cancel_process(record)
            raise
        return self._result(record)

    def _read_log(
        self, record: LocalProcess, stream: str, offset: int = 0, limit: int = 65536
    ) -> dict[str, Any]:
        if stream not in {"stdout", "stderr"}:
            raise ValueError("stream must be stdout or stderr")
        path = record.stdout_path if stream == "stdout" else record.stderr_path
        with path.open("rb") as file:
            file.seek(max(0, offset))
            content = file.read(max(1, min(limit, 65536)))
            next_offset = file.tell()
        return {
            "execution_id": record.execution_id,
            "stream": stream,
            "offset": offset,
            "next_offset": next_offset,
            "text": content.decode("utf-8", errors="replace"),
            "total_bytes": path.stat().st_size,
            "complete": next_offset >= path.stat().st_size,
        }

    def _result(self, record: LocalProcess) -> dict[str, Any]:
        stdout = self._read_log(record, "stdout", max(0, record.stdout_size - 65536), 65536)
        stderr = self._read_log(record, "stderr", max(0, record.stderr_size - 65536), 65536)
        data = record.summary()
        data.update(
            {
                "stdout": stdout["text"],
                "stderr": stderr["text"],
                "stdout_truncated": record.stdout_size > 65536,
                "stderr_truncated": record.stderr_size > 65536,
            }
        )
        return {"data": data, "content": [{"type": "text", "text": str(data)}], "is_error": False}

    async def _execute_or_detach(
        self, record: LocalProcess, args: dict[str, Any]
    ) -> dict[str, Any]:
        if args.get("detached"):
            data = record.summary()
            return {
                "data": data,
                "content": [{"type": "text", "text": str(data)}],
                "is_error": False,
            }
        return await self._wait_result(record, args.get("timeout"))

    async def _process_operation(
        self, args: dict[str, Any], run_id: str | None, callback: OutputCallback | None,
        event_callback: Any = None,
    ) -> dict[str, Any]:
        action = args["action"]
        if action == "list":
            data = {
                "processes": [
                    item.summary() for item in self._processes.values() if item.state == "running"
                ]
            }
            return {
                "data": data,
                "content": [{"type": "text", "text": str(data)}],
                "is_error": False,
            }
        if action == "start":
            args.setdefault("detached", True)
            record = await (
                self._start_from_shell(args, run_id, callback)
                if args.get("shell")
                else self._start_from_exec(args, run_id, callback)
            )
            self._configure_notifications(
                record, args, event_callback, str(args.get("_atlas_conversation_id") or ""),
            )
            data = record.summary()
        else:
            record = self._processes.get(str(args.get("execution_id", "")))
            if record is None:
                return self._error("Unknown Atlas execution_id.")
            if action == "status":
                data = record.summary()
                if args.get("_native_poll"):
                    offset = int(args.get("offset", 0))
                    limit = int(args.get("limit", 100))
                    stdout = self._read_log_lines(record, "stdout", offset, limit)
                    stderr = self._read_log_lines(record, "stderr", offset, limit)
                    data.update({
                        "stdout": stdout["text"], "stderr": stderr["text"],
                        "new_output": stdout["text"], "new_stderr": stderr["text"],
                        "stdout_next_offset": stdout["next_offset"],
                        "stderr_next_offset": stderr["next_offset"],
                        "next_offset": max(stdout["next_offset"], stderr["next_offset"]),
                    })
            elif action == "read":
                if args.get("_line_offsets"):
                    data = self._read_log_lines(
                        record, args.get("stream", "stdout"),
                        int(args.get("offset", 0)), int(args.get("limit", 100)),
                    )
                else:
                    data = self._read_log(
                        record, args.get("stream", "stdout"),
                        int(args.get("offset", 0)), int(args.get("limit", 65536)),
                    )
            elif action == "wait":
                return await self._wait_result(record, args.get("timeout"))
            elif action == "cancel":
                await self._cancel_process(record)
                data = record.summary()
            elif action in {"write_stdin", "submit_stdin", "close_stdin"}:
                data = await self._write_process_stdin(record, action, str(args.get("data", "")))
            elif action == "handoff":
                if record.state != "running":
                    raise ValueError("Only a running process can be handed off.")
                record.detached = True
                record.owner_run_id = None
                record.handoff_note = str(args.get("data", "")).strip()
                record.notification_callback = event_callback
                record.conversation_id = str(args.get("_atlas_conversation_id") or "")
                record.notify_on_complete = True
                data = record.summary()
            else:
                raise ValueError(f"Unsupported process action: {action}")
        return {"data": data, "content": [{"type": "text", "text": str(data)}], "is_error": False}

    def _read_log_lines(
        self, record: LocalProcess, stream: str, offset: int = 0, limit: int = 100,
    ) -> dict[str, Any]:
        if stream not in {"stdout", "stderr"}:
            raise ValueError("stream must be stdout or stderr")
        path = record.stdout_path if stream == "stdout" else record.stderr_path
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(0, offset)
        end = min(len(lines), start + max(1, min(limit, 10000)))
        return {
            "execution_id": record.execution_id, "stream": stream,
            "offset": start, "next_offset": end, "text": "\n".join(lines[start:end]),
            "total_lines": len(lines), "complete": end >= len(lines),
        }

    async def _write_process_stdin(
        self, record: LocalProcess, action: str, data: str,
    ) -> dict[str, Any]:
        writer = record.process.stdin
        if writer is None or writer.is_closing():
            raise ValueError("Process stdin is closed; start the terminal with background=true.")
        if record.state != "running":
            raise ValueError("Process has already exited; stdin is unavailable.")
        if action == "close_stdin":
            writer.close()
            await writer.wait_closed()
            return {"execution_id": record.execution_id, "action": action, "closed": True}
        payload = data
        if action == "submit_stdin":
            payload += "\r\n" if os.name == "nt" else "\n"
        encoded = payload.encode("utf-8")
        writer.write(encoded)
        await writer.drain()
        return {
            "execution_id": record.execution_id,
            "action": action,
            "bytes_written": len(encoded),
        }

    async def _cancel_process(self, record: LocalProcess) -> None:
        if record.state != "running":
            return
        record.cancelled = True
        try:
            if os.name == "nt":
                record.process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                os.killpg(record.process.pid, signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass
        try:
            await asyncio.wait_for(asyncio.shield(record.wait_task), timeout=2.0)
        except TimeoutError:
            if os.name == "nt":
                killer = await asyncio.create_subprocess_exec(
                    "taskkill.exe",
                    "/PID",
                    str(record.process.pid),
                    "/T",
                    "/F",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await killer.wait()
            else:
                try:
                    os.killpg(record.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            await record.wait_task
        record.state = "cancelled"

    async def cancel_run(self, run_id: str) -> None:
        await asyncio.gather(
            *(
                self._cancel_process(process)
                for process in self._processes.values()
                if process.owner_run_id == run_id
                and not process.detached
                and process.state == "running"
            ),
            return_exceptions=False,
        )

    async def shutdown(self) -> None:
        self._closed = True
        await asyncio.gather(
            *(
                self._cancel_process(process)
                for process in self._processes.values()
                if process.state == "running"
            ),
            return_exceptions=False,
        )
        for process in self._processes.values():
            for path in (process.stdout_path, process.stderr_path):
                path.unlink(missing_ok=True)
