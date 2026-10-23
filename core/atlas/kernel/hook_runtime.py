"""Shell and lifecycle policy shared by Atlas command-hook execution."""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
from collections.abc import Awaitable, Mapping
from pathlib import Path
from typing import Any

from atlas.kernel.exec import hook_timeout_ms

_ALLOWED_SHELLS = frozenset({"bash", "powershell"})
_logger = logging.getLogger(__name__)


def resolve_hook_shell(value: Any) -> str:
    """Accept only the documented shell names; unknown values use Bash."""
    if value is None or not str(value).strip():
        return "bash"
    shell = str(value or "bash").strip().lower()
    if shell not in _ALLOWED_SHELLS:
        _logger.warning("Ignoring unsupported Hook shell %r; using bash", value)
        return "bash"
    return shell


def windows_path_to_posix(path: str) -> str:
    """Convert drive paths for Git Bash while preserving UNC and POSIX paths."""
    if path.startswith("\\\\"):
        return "//" + path[2:].replace("\\", "/")
    match = re.match(r"^([A-Za-z]):[\\/](.*)$", path)
    if match:
        return f"/{match.group(1).lower()}/{match.group(2).replace(chr(92), '/') }"
    return path.replace("\\", "/") if path.startswith("/") else path


def prepare_hook_command(
    command: str, *, shell: str, cwd: str | None, plugin_root: str | None,
    environment: Mapping[str, str] | None = None, windows: bool | None = None,
) -> tuple[str, dict[str, str]]:
    """Apply Hook path substitutions and bash-only command conventions."""
    selected = resolve_hook_shell(shell)
    is_windows = os.name == "nt" if windows is None else windows
    to_hook_path = windows_path_to_posix if is_windows and selected == "bash" else (lambda value: value)
    project = to_hook_path(str(Path(cwd).expanduser().resolve())) if cwd else ""
    plugin = to_hook_path(str(Path(plugin_root).expanduser().resolve())) if plugin_root else ""
    command = command.replace("${CLAUDE_PROJECT_DIR}", project)
    command = command.replace("${CLAUDE_PLUGIN_ROOT}", plugin)
    env = dict(os.environ if environment is None else environment)
    if project:
        env["CLAUDE_PROJECT_DIR"] = project
    if plugin:
        env["CLAUDE_PLUGIN_ROOT"] = plugin
    if is_windows and selected == "bash" and re.search(r"\.sh(?:\s|$|\")", command.strip()):
        if not command.strip().lower().startswith("bash "):
            command = f"bash {command}"
    prefix = env.get("CLAUDE_CODE_SHELL_PREFIX")
    if selected == "bash" and prefix:
        command = f"{prefix} {command}"
    return command, env


def hook_command_argv(command: str, shell: str, *, windows: bool | None = None) -> list[str]:
    """Build explicit interpreter argv, keeping PowerShell arguments native."""
    selected = resolve_hook_shell(shell)
    is_windows = os.name == "nt" if windows is None else windows
    if selected == "powershell":
        executable = shutil.which("pwsh") or shutil.which("powershell")
        if not executable and is_windows:
            executable = "powershell.exe"
        if not executable:
            raise FileNotFoundError("Hook requests PowerShell, but pwsh/powershell was not found on PATH")
        return [executable, "-NoProfile", "-NonInteractive", "-Command", command]
    if is_windows:
        system_bash = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "bash.exe"
        path_bash = shutil.which("bash")
        if path_bash and Path(path_bash).resolve() == system_bash.resolve():
            path_bash = None
        candidates = [
            str(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"),
            str(Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Git" / "bin" / "bash.exe"),
            path_bash,
        ]
        executable = next((item for item in candidates if item and Path(item).is_file()), None)
        if not executable:
            raise FileNotFoundError("Bash hook requires Git Bash or bash on PATH")
        return [executable, "-lc", command]
    return ["sh", "-lc", command]


def hook_environment(
    spec: Mapping[str, Any], base: Mapping[str, str], *, shell: str,
) -> dict[str, str]:
    """Add sanitized plugin option variables without changing inherited keys."""
    env = dict(base)
    options = spec.get("options")
    if isinstance(options, Mapping):
        for key, value in options.items():
            safe = re.sub(r"[^A-Za-z0-9_]", "_", str(key)).upper()
            env[f"CLAUDE_PLUGIN_OPTION_{safe}"] = str(value)
    return env


async def await_hook_with_timeout(
    awaitable: Awaitable[Any], timeout_ms: int, *, parent_event: asyncio.Event | None = None,
) -> Any:
    """Await a Hook operation under its timeout and optional parent cancellation."""
    task = asyncio.ensure_future(awaitable)
    parent_waiter: asyncio.Task[bool] | None = None
    try:
        waiters: set[asyncio.Future[Any]] = {task}
        if parent_event is not None:
            parent_waiter = asyncio.create_task(parent_event.wait())
            waiters.add(parent_waiter)
        done, _ = await asyncio.wait(
            waiters, timeout=max(0.001, timeout_ms / 1000),
            return_when=asyncio.FIRST_COMPLETED,
        )
        if task in done:
            return await task
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        if parent_waiter is not None and parent_waiter in done:
            raise asyncio.CancelledError("parent hook operation cancelled")
        raise TimeoutError(f"Hook timed out after {timeout_ms}ms")
    finally:
        if parent_waiter is not None:
            parent_waiter.cancel()
            await asyncio.gather(parent_waiter, return_exceptions=True)


def timeout_for(spec: Mapping[str, Any], *, event: str, kind: str = "command") -> int:
    return hook_timeout_ms(spec.get("timeout"), event=event, kind=kind)


__all__ = [
    "await_hook_with_timeout", "hook_command_argv", "hook_environment",
    "prepare_hook_command", "resolve_hook_shell", "timeout_for",
]
