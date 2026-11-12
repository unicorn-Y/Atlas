# Codex hook runtime reference: openai/codex@6c0c6759d0617d7670826b61aca0a931bbb6db1f
# (codex-rs/core/src/hook_runtime.rs; Apache-2.0).
# Claude Code v2.1.296 hooks behavior (closed source):
# https://docs.anthropic.com/en/docs/claude-code/hooks
"""Atlas command hooks with Claude Code settings compatibility."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import subprocess
import threading
import time
import tomllib
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from atlas.engine.kernel.hook_runtime import (
    hook_command_argv,
    hook_environment,
    prepare_hook_command,
    resolve_hook_shell,
    timeout_for,
    await_hook_with_timeout,
)


# Claude-compatible events with a real Atlas lifecycle trigger.
CLAUDE_HOOK_EVENTS = frozenset({
    "SessionStart", "InstructionsLoaded", "UserPromptSubmit",
    "MessageDisplay", "PreToolUse", "PermissionRequest",
    "PostToolUse", "PostToolUseFailure", "PostToolBatch", "PermissionDenied",
    "Notification", "SubagentStart", "SubagentStop", "TaskCreated", "TaskCompleted",
    "Stop", "StopFailure", "ConfigChange", "CwdChanged", "DirectoryAdded",
    "FileChanged", "WorktreeCreate", "WorktreeRemove", "PreCompact", "PostCompact",
    "PreModelSwitch", "PostModelSwitch", "SessionEnd",
})

_ATLAS_TO_CLAUDE = {
    "run.started": "SessionStart",
    "tool.before": "PreToolUse",
    "tool.after": "PostToolUse",
    "run.completed": "Stop",
    "run.failed": "StopFailure",
}
_BLOCKING_EXIT_EVENTS = {
    "PreToolUse", "UserPromptSubmit", "Stop",
    "SubagentStop", "TaskCreated", "TaskCompleted",
    "PostToolBatch", "PreCompact", "ConfigChange", "PreModelSwitch",
    "WorktreeCreate", "WorktreeRemove",
}
_MATCH_FIELDS = {
    "PreToolUse": "tool_name", "PostToolUse": "tool_name",
    "PostToolUseFailure": "tool_name", "PermissionRequest": "tool_name",
    "PermissionDenied": "tool_name", "SessionStart": "source",
    "SessionEnd": "reason", "Notification": "notification_type",
    "SubagentStart": "agent_type", "SubagentStop": "agent_type",
    "PreCompact": "trigger", "PostCompact": "trigger",
    "PreModelSwitch": "model", "PostModelSwitch": "model",
    "ConfigChange": "source", "DirectoryAdded": "source", "FileChanged": "file_path",
    "StopFailure": "error_type", "InstructionsLoaded": "load_reason",
}
_EXACT_MATCHER = re.compile(r"^[A-Za-z0-9_\- ,|]*$")
_ASYNC_HOOK_TASKS: set[asyncio.Task[Any]] = set()


def _track_async_hook(task: asyncio.Task[Any]) -> None:
    _ASYNC_HOOK_TASKS.add(task)

    def finished(completed: asyncio.Task[Any]) -> None:
        _ASYNC_HOOK_TASKS.discard(completed)
        try:
            completed.result()
        except (asyncio.CancelledError, Exception):
            # Fire-and-forget hook failures are isolated from their caller.
            pass

    task.add_done_callback(finished)


def parse_claude_hooks(
    config: Mapping[str, Any], *, source: str = "",
) -> list[dict[str, Any]]:
    """Normalize Claude settings/plugin hooks into event/matcher/handler records."""
    events = config.get("hooks", config)
    if not isinstance(events, Mapping):
        return []
    normalized: list[dict[str, Any]] = []
    for event, groups in events.items():
        if not isinstance(event, str) or not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, Mapping):
                continue
            hooks = group.get("hooks")
            if not isinstance(hooks, list):
                continue
            commands = [dict(item) for item in hooks if isinstance(item, Mapping)]
            if commands:
                item = {
                    "event": event,
                    "matcher": group.get("matcher"),
                    "hooks": commands,
                    "source": source,
                }
                item["id"] = _claude_hook_id(item)
                normalized.append(item)
    return normalized


def claude_hook_settings(
    project_dir: str | Path | None = None,
    user_settings_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Read user and project Claude settings without modifying their source files."""
    paths: list[tuple[str, Path]] = []
    user_path = Path(user_settings_path).expanduser() if user_settings_path else Path.home() / ".claude" / "settings.json"
    paths.append(("user", user_path))
    if project_dir is not None:
        project = Path(project_dir).expanduser()
        paths.extend((
            ("project", project / ".claude" / "settings.json"),
            ("local", project / ".claude" / "settings.local.json"),
        ))
    result: list[dict[str, Any]] = []
    for scope, path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if isinstance(data, Mapping):
            result.extend(parse_claude_hooks(data, source=f"claude:{scope}:{path}"))
    return result


def _event_payload(event: str, payload: Mapping[str, Any], cwd: str | None) -> dict[str, Any]:
    data = dict(payload)
    data["hook_event_name"] = event
    if "session_id" not in data and data.get("conversation_id"):
        data["session_id"] = data["conversation_id"]
    if cwd:
        data.setdefault("cwd", cwd)
    if "parameters" in data and "tool_input" not in data:
        data["tool_input"] = data["parameters"]
    if "tool_response" not in data and "result" in data:
        data["tool_response"] = data["result"]
    return data


def _matches(matcher: Any, event: str, payload: Mapping[str, Any]) -> bool:
    if matcher is None or matcher in ("", "*"):
        return True
    if not isinstance(matcher, str):
        return False
    field = _MATCH_FIELDS.get(event)
    if field is None:
        return True
    value = payload.get(field)
    if value is None and field == "file_path":
        value = payload.get("file") or payload.get("path")
    if value is None and field == "error_type" and isinstance(payload.get("error"), Mapping):
        value = payload["error"].get("type")
    if value is None:
        return False
    value = str(value)
    if _EXACT_MATCHER.fullmatch(matcher):
        return value in [item.strip() for item in re.split(r"[|,]", matcher)]
    try:
        return re.search(matcher, value) is not None
    except re.error:
        return False


def _matches_if(condition: Any, event: str, payload: Mapping[str, Any]) -> bool:
    if condition is None or condition == "":
        return True
    if not isinstance(condition, str):
        return False
    # Claude Code's command-hook `if` form is ToolName(argument-pattern).
    match = re.fullmatch(r"([A-Za-z0-9_.:-]+)\((.*)\)", condition)
    if not match:
        return True
    tool_name, pattern = match.groups()
    if str(payload.get("tool_name") or "") != tool_name:
        return False
    tool_input = payload.get("tool_input")
    command = tool_input.get("command", "") if isinstance(tool_input, Mapping) else ""
    if pattern.endswith("*"):
        return str(command).startswith(pattern[:-1])
    return str(command) == pattern


def _claude_hook_id(item: Mapping[str, Any]) -> str:
    identity = json.dumps(
        {key: item.get(key) for key in ("source", "event", "matcher", "hooks")},
        sort_keys=True, ensure_ascii=False, default=str,
    )
    return "claude-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


def _json_decision(event: str, value: Any) -> dict[str, Any]:
    outcome: dict[str, Any] = {"blocked": False, "reason": ""}
    if not isinstance(value, Mapping):
        return outcome
    specific = value.get("hookSpecificOutput")
    specific = specific if isinstance(specific, Mapping) else {}
    if event == "PreToolUse":
        decision = specific.get("permissionDecision")
        if decision is None:
            decision = value.get("decision")
            decision = {"block": "deny", "approve": "allow"}.get(decision, decision)
        if isinstance(decision, str) and decision in {"allow", "deny", "ask", "defer"}:
            outcome["permission_decision"] = decision
        if decision == "allow":
            outcome["allowed"] = True
        if decision == "deny":
            outcome.update(blocked=True, reason=str(
                specific.get("permissionDecisionReason") or value.get("reason") or "Blocked by hook"
            ))
        elif decision == "ask":
            outcome["ask_user"] = True
            outcome["reason"] = str(specific.get("permissionDecisionReason") or "Hook 要求人工确认")
        updated = specific.get("updatedInput")
        if isinstance(updated, Mapping):
            outcome["updated_input"] = dict(updated)
        context = specific.get("additionalContext") or value.get("additionalContext")
        if isinstance(context, str) and context:
            outcome["additional_context"] = context
    elif event == "PermissionRequest":
        decision = specific.get("decision")
        if isinstance(decision, Mapping):
            if decision.get("behavior") == "deny":
                outcome.update(blocked=True, reason=str(
                    decision.get("message") or "Permission denied by hook"
                ))
                outcome["interrupt"] = bool(decision.get("interrupt", False))
            elif decision.get("behavior") == "ask":
                outcome["ask_user"] = True
            elif decision.get("behavior") == "allow":
                outcome["allowed"] = True
                updated = decision.get("updatedInput")
                if isinstance(updated, Mapping):
                    outcome["updated_input"] = dict(updated)
    elif event == "PermissionDenied":
        outcome["retry"] = specific.get("retry") is True
    elif event == "PostToolUse":
        if value.get("decision") == "block":
            outcome["feedback"] = str(value.get("reason") or "")
        if "updatedToolOutput" in specific:
            outcome["updated_tool_output"] = specific["updatedToolOutput"]
        elif "updatedMCPToolOutput" in specific:
            outcome["updated_tool_output"] = specific["updatedMCPToolOutput"]
        context = specific.get("additionalContext") or value.get("additionalContext")
        if isinstance(context, str) and context:
            outcome["additional_context"] = context
    elif event in {"SessionStart", "SubagentStart", "CwdChanged", "PostModelSwitch"}:
        context = specific.get("additionalContext") or value.get("additionalContext")
        if isinstance(context, str) and context:
            outcome["additional_context"] = context
        if event in {"SessionStart", "CwdChanged"}:
            for source, target in (
                ("initialUserMessage", "initial_user_message"),
                ("sessionTitle", "session_title"),
                ("watchPaths", "watch_paths"),
                ("reloadSkills", "reload_skills"),
            ):
                if source in specific:
                    outcome[target] = specific[source]
    elif event == "MessageDisplay":
        if isinstance(specific.get("displayContent"), str):
            outcome["display_content"] = specific["displayContent"]
    elif event == "WorktreeCreate":
        worktree_path = specific.get("worktreePath")
        if isinstance(worktree_path, str) and worktree_path:
            outcome["worktree_path"] = worktree_path
    elif event == "Stop":
        if value.get("decision") == "block":
            outcome.update(blocked=True, reason=str(value.get("reason") or "Blocked by hook"))
        context = specific.get("additionalContext") or value.get("additionalContext")
        if isinstance(context, str) and context:
            outcome["additional_context"] = context
    elif event in {
        "UserPromptSubmit", "InstructionsLoaded", "PostToolUseFailure", "PostToolBatch",
        "SubagentStop", "ConfigChange", "PreCompact", "TaskCreated", "TaskCompleted",
        "PreModelSwitch",
    }:
        if value.get("decision") == "block" and event == "PostToolUseFailure":
            outcome["feedback"] = str(value.get("reason") or "")
        elif value.get("decision") == "block":
            outcome.update(blocked=True, reason=str(value.get("reason") or "Blocked by hook"))
        context = specific.get("additionalContext") or value.get("additionalContext")
        if isinstance(context, str) and context:
            outcome["additional_context"] = context
        if event == "PostToolBatch" and value.get("continue") is False:
            outcome.update(blocked=True, reason=str(
                value.get("reason") or value.get("stopReason") or "Stopped by PostToolBatch hook"
            ))
        if event == "TaskCompleted" and value.get("continue") is False:
            outcome.update(blocked=True, reason=str(
                value.get("stopReason") or value.get("reason") or "Stopped by hook"
            ))
        if event == "PreModelSwitch":
            decision = specific.get("permissionDecision") or value.get("decision")
            if decision in {"deny", "block"}:
                outcome.update(blocked=True, reason=str(
                    specific.get("permissionDecisionReason") or value.get("reason") or "Model switch blocked by hook"
                ))
            elif decision == "ask":
                outcome["ask_user"] = True
    if isinstance(value.get("systemMessage"), str) and value["systemMessage"]:
        outcome["system_message"] = value["systemMessage"]
    if value.get("continue") is False:
        outcome["continue"] = False
        outcome["stop_reason"] = str(value.get("stopReason") or "")
    return outcome


async def _run_command(
    spec: Mapping[str, Any], input_data: dict[str, Any], *, cwd: str | None,
    plugin_root: str | None,
) -> tuple[int, str, str]:
    command = str(spec.get("command") or "")
    if not command:
        return 1, "", "hook command is empty"
    replacements = {
        "${CLAUDE_PROJECT_DIR}": cwd or "",
        "${CLAUDE_PLUGIN_ROOT}": plugin_root or "",
    }
    command = _substitute(command, replacements)
    args = spec.get("args")
    selected_shell = resolve_hook_shell(spec.get("shell"))
    command, env = prepare_hook_command(
        command, shell=selected_shell, cwd=cwd, plugin_root=plugin_root,
    )
    env = hook_environment(spec, env, shell=selected_shell)
    timeout_ms = timeout_for(spec, event=str(spec.get("event") or ""))
    if isinstance(args, list):
        argv = [command, *[_substitute(str(arg), replacements) for arg in args]]
    else:
        argv = hook_command_argv(command, selected_shell)
    safe_cwd = cwd
    if safe_cwd and not Path(safe_cwd).is_dir():
        safe_cwd = str(Path.cwd())
    proc = None

    async def stop_process_tree() -> None:
        if proc is None or proc.returncode is not None:
            return
        if os.name == "nt":
            killer = None
            try:
                killer = await asyncio.create_subprocess_exec(
                    "taskkill.exe", "/PID", str(proc.pid), "/T", "/F",
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                await asyncio.wait_for(killer.wait(), timeout=3)
            except (OSError, TimeoutError):
                if killer is not None and killer.returncode is None:
                    killer.kill()
            if proc.returncode is None:
                proc.kill()
                await asyncio.wait_for(proc.wait(), timeout=3)
            return
        proc.kill()
        await asyncio.wait_for(proc.wait(), timeout=3)

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=safe_cwd or None, env=env, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate((json.dumps(input_data, ensure_ascii=False, default=str) + "\n").encode("utf-8")),
            timeout=timeout_ms / 1000,
        )
        return int(proc.returncode or 0), stdout[:4096].decode("utf-8", errors="replace"), stderr[:4096].decode("utf-8", errors="replace")
    except asyncio.CancelledError:
        try:
            await stop_process_tree()
        except (OSError, TimeoutError):
            pass
        raise
    except Exception as exc:
        try:
            await stop_process_tree()
        except (OSError, TimeoutError):
            pass
        return 1, "", str(exc)[:4096]


def _substitute(value: str, replacements: Mapping[str, str]) -> str:
    for key, replacement in replacements.items():
        value = value.replace(key, replacement)
    return value


async def execute_claude_hooks(
    hooks: Iterable[Mapping[str, Any]], event: str, payload: Mapping[str, Any], *,
    cwd: str | None = None, emit: Any = None,
) -> dict[str, Any]:
    """Execute normalized Claude command hooks and combine event decisions."""
    result: dict[str, Any] = {
        "blocked": False, "reason": "", "updated_input": None,
        "additional_context": "", "continue": None, "logs": [],
        "updated_tool_output": None, "feedback": "", "permission_decision": None,
        "allowed": False, "ask_user": False, "retry": False,
    }
    event_payload = _event_payload(event, payload, cwd)
    for group in hooks:
        if group.get("event") != event or not _matches(group.get("matcher"), event, event_payload):
            continue
        for spec in group.get("hooks", []):
            if not isinstance(spec, Mapping) or spec.get("type", "command") != "command":
                continue
            if not _matches_if(spec.get("if"), event, event_payload):
                continue
            started = time.monotonic()
            run_spec = {**spec, "event": event}
            force_sync = spec.get("force_sync_execution", spec.get("forceSyncExecution", False))
            if (spec.get("async") or spec.get("async_rewake") or spec.get("asyncRewake")) and not force_sync:
                requested_async_ms = spec.get("async_timeout", spec.get("asyncTimeout"))
                async_timeout = dict(run_spec)
                if requested_async_ms is None or isinstance(requested_async_ms, bool):
                    async_timeout["timeout"] = None
                else:
                    try:
                        value_ms = float(requested_async_ms)
                        async_timeout["timeout"] = value_ms / 1000 if value_ms > 0 else None
                    except (TypeError, ValueError):
                        async_timeout["timeout"] = None
                timeout_ms = timeout_for(async_timeout, event=event, kind="async")
                task = asyncio.create_task(await_hook_with_timeout(
                    _run_command(run_spec, event_payload, cwd=cwd, plugin_root=group.get("plugin_root")),
                    timeout_ms,
                ))
                _track_async_hook(task)
                code, output, stderr = 0, "", ""
            else:
                code, output, stderr = await _run_command(
                    run_spec, event_payload, cwd=cwd, plugin_root=group.get("plugin_root"),
                )
            try:
                structured = json.loads(output) if output.strip() else None
            except json.JSONDecodeError:
                structured = None
            decision = _json_decision(event, structured)
            if code not in {0, 2}:
                decision = {"blocked": False, "reason": ""}
            if event == "ConfigChange" and event_payload.get("source") == "policy_settings":
                decision.update(blocked=False, reason="")
            if event == "WorktreeCreate" and code != 0:
                decision.update(blocked=True, reason=stderr.strip() or output.strip() or "Worktree creation failed")
            elif event == "WorktreeRemove" and code != 0:
                worktree_path = event_payload.get("worktree_path") or event_payload.get("path")
                if isinstance(worktree_path, str) and os.path.exists(worktree_path):
                    decision.update(blocked=True, reason=stderr.strip() or output.strip() or "Worktree removal failed")
            elif code == 2 and event in _BLOCKING_EXIT_EVENTS:
                if event == "ConfigChange" and event_payload.get("source") == "policy_settings":
                    pass
                else:
                    decision.update(blocked=True, reason=stderr.strip() or output.strip() or "Blocked by hook")
            elif code == 2 and event in {"PostToolUse", "PostToolUseFailure"}:
                if stderr.strip():
                    decision["feedback"] = "\n".join(
                        item for item in (str(decision.get("feedback") or ""), stderr.strip()) if item
                    )
            elif not output.strip() and event in {"SessionStart", "UserPromptSubmit", "PostModelSwitch"} and code == 0:
                decision["additional_context"] = ""
            elif structured is None and code == 0 and event in {"SessionStart", "UserPromptSubmit", "PostModelSwitch"}:
                decision["additional_context"] = output.strip()
            if event == "WorktreeCreate" and code == 0 and not decision.get("worktree_path"):
                worktree_path = output.strip()
                if worktree_path:
                    decision["worktree_path"] = worktree_path
            for key in (
                "updated_tool_output", "permission_decision", "system_message",
                "session_title", "initial_user_message", "watch_paths", "reload_skills",
                "display_content", "action", "content", "retry", "allowed", "ask_user",
                "interrupt", "continue", "stop_reason", "worktree_path",
            ):
                if key in decision:
                    if key in {"watch_paths"} and isinstance(decision[key], list):
                        result[key] = list(dict.fromkeys([*(result.get(key) or []), *decision[key]]))
                    else:
                        result[key] = decision[key]
            if decision.get("updated_input"):
                current = result["updated_input"] or {}
                result["updated_input"] = {**current, **decision["updated_input"]}
            if decision.get("additional_context"):
                result["additional_context"] = "\n".join(
                    item for item in (result["additional_context"], decision["additional_context"]) if item
                )
            if decision.get("feedback"):
                result["feedback"] = "\n".join(
                    item for item in (result["feedback"], decision["feedback"]) if item
                )
            if decision.get("blocked"):
                result.update(blocked=True, reason=decision["reason"])
                if event == "Stop":
                    result["continue"] = False
            log = {
                "event": event, "source": group.get("source", "claude"),
                "exit_code": code, "duration_ms": round((time.monotonic() - started) * 1000),
                "output": output, "stderr": stderr,
            }
            result["logs"].append(log)
            if emit:
                maybe_awaitable = emit("hook.ran", log)
                if asyncio.iscoroutine(maybe_awaitable):
                    await maybe_awaitable
            if result["blocked"]:
                break
        if result["blocked"]:
            break
    return result


async def run_user_hook(
    callback: Callable[[str, Mapping[str, Any]], Any] | None,
    event: str, payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Invoke one user hook callback (Atlas or Claude event) and normalize its outcome."""
    if callback is None:
        return {}
    outcome = callback(event, dict(payload))
    if asyncio.iscoroutine(outcome):
        outcome = await outcome
    return dict(outcome) if isinstance(outcome, Mapping) else {}


class HookStore:
    EVENTS = {"run.started", "tool.before", "tool.after", "run.completed", "run.failed"}

    def __init__(
        self,
        path: Path,
        *,
        plugin_hooks: Iterable[Mapping[str, Any]] | Callable[[], Iterable[Mapping[str, Any]]] = (),
    ) -> None:
        self.path = path
        self.plugin_hooks = plugin_hooks
        self._recent_logs: list[dict[str, Any]] = []
        self._trust_path = path.with_name("hooks.trust.json")
        self._trust_lock = threading.RLock()
        self._watch_tasks: dict[str, asyncio.Task[Any]] = {}
        self._watch_paths: dict[str, set[str]] = {}
        self._watch_cwds: dict[str, str] = {}

    def start_file_watcher(
        self, session_id: str, paths: Iterable[str], *, cwd: str | None,
        callback: Callable[[str, dict[str, Any]], Any],
    ) -> None:
        """Watch SessionStart/CwdChanged paths and dispatch stable file changes."""
        identifier = str(session_id or "")
        if not identifier:
            return
        resolved_cwd = str(Path(cwd or os.getcwd()).resolve())
        resolved_paths = {
            str(Path(item).expanduser().resolve())
            for item in paths if isinstance(item, str) and item.strip()
        }
        resolved_paths.add(str(self.path.resolve()))
        if cwd:
            project = Path(cwd).expanduser().resolve() / ".claude"
            resolved_paths.update(str(path) for path in (
                project / "settings.json", project / "settings.local.json",
            ))
        prior_cwd = self._watch_cwds.get(identifier)
        prior_paths = self._watch_paths.get(identifier)
        if prior_cwd == resolved_cwd and prior_paths == resolved_paths:
            return
        self.stop_file_watcher(identifier)
        self._watch_cwds[identifier] = resolved_cwd
        self._watch_paths[identifier] = resolved_paths
        task = asyncio.create_task(
            self._watch_file_changes(identifier, resolved_paths, resolved_cwd, callback),
            name=f"atlas-hook-file-watch:{identifier[:12]}",
        )
        self._watch_tasks[identifier] = task

    def stop_file_watcher(self, session_id: str) -> None:
        identifier = str(session_id or "")
        task = self._watch_tasks.pop(identifier, None)
        if task is not None:
            task.cancel()
        self._watch_paths.pop(identifier, None)
        self._watch_cwds.pop(identifier, None)

    @staticmethod
    def _file_snapshot(paths: set[str]) -> dict[str, tuple[bool, int, int, bool]]:
        snapshot: dict[str, tuple[bool, int, int, bool]] = {}
        for raw_path in paths:
            path = Path(raw_path)
            targets = [path]
            if path.is_dir():
                targets.extend(item for item in path.rglob("*") if item.is_file() or item.is_dir())
            for item in targets:
                try:
                    info = item.stat()
                except OSError:
                    snapshot[str(item)] = (False, 0, 0, False)
                else:
                    snapshot[str(item)] = (True, info.st_mtime_ns, info.st_size, item.is_dir())
        return snapshot

    async def _watch_file_changes(
        self, session_id: str, paths: set[str], cwd: str,
        callback: Callable[[str, dict[str, Any]], Any],
    ) -> None:
        before = await asyncio.to_thread(self._file_snapshot, paths)
        try:
            while True:
                await asyncio.sleep(0.35)
                after = await asyncio.to_thread(self._file_snapshot, paths)
                for file_path in sorted(set(before) | set(after)):
                    old, new = before.get(file_path), after.get(file_path)
                    if old == new:
                        continue
                    await asyncio.sleep(0.25)
                    stable = await asyncio.to_thread(self._file_snapshot, {file_path})
                    current = stable.get(file_path, (False, 0, 0, False))
                    if current != after.get(file_path):
                        continue
                    change_type = "added" if not (old or (False,))[0] and current[0] else (
                        "deleted" if not current[0] else "changed"
                    )
                    payload = {
                        "file_path": file_path, "path": file_path,
                        "change_type": change_type, "cwd": cwd,
                        "session_id": session_id,
                    }
                    result = callback("FileChanged", payload)
                    if asyncio.iscoroutine(result):
                        await result
                    if change_type == "added" and current[3]:
                        result = callback("DirectoryAdded", {**payload, "source": "watcher"})
                        if asyncio.iscoroutine(result):
                            await result
                    if Path(file_path).name in {"settings.json", "settings.local.json", "config.toml"}:
                        result = callback("ConfigChange", {**payload, "source": "file_watcher"})
                        if asyncio.iscoroutine(result):
                            await result
                before = after
        except asyncio.CancelledError:
            return

    @staticmethod
    def _fingerprint(hook: Mapping[str, Any]) -> str:
        """Bind review to the exact command, event, matcher and source."""
        identity = {
            key: hook.get(key) for key in (
                "id", "event", "source", "matcher", "timeout_s",
                "hooks", "plugin_root",
            )
        }
        if not isinstance(hook.get("hooks"), list):
            identity["command"] = hook.get("command")
        raw = json.dumps(identity, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _read_trust_records(self) -> dict[str, Any]:
        try:
            with self._trust_path.open("r", encoding="utf-8") as stream:
                data = json.load(stream)
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        if not isinstance(data, Mapping) or data.get("version") != 1:
            return {}
        hooks = data.get("hooks")
        return dict(hooks) if isinstance(hooks, Mapping) else {}

    def trust_status(self, hook: Mapping[str, Any]) -> dict[str, Any]:
        """Return a fail-closed review state without changing hook config."""
        hook_id = str(hook.get("id") or "")
        fingerprint = self._fingerprint(hook)
        with self._trust_lock:
            record = self._read_trust_records().get(hook_id)
        current = record if isinstance(record, Mapping) else {}
        same_config = current.get("fingerprint") == fingerprint
        trusted = same_config and current.get("trusted") is True
        if trusted:
            state = "approved"
        elif same_config and current.get("trusted") is False:
            state = "revoked"
        elif current:
            state = "changed"
        else:
            state = "unreviewed"
        return {
            "trusted": trusted,
            "trust_state": state,
            "trust_fingerprint": fingerprint,
            "reviewed_at": current.get("reviewed_at") if same_config else None,
        }

    def set_hook_trust(
        self, hook_id: str, trusted: bool, *, fingerprint: str, cwd: str | None = None,
    ) -> dict[str, Any]:
        """Approve/revoke one current hook revision; config changes need review again."""
        matches = [hook for hook in self.list_all(cwd) if hook.get("id") == hook_id]
        if not matches:
            raise KeyError(hook_id)
        if len(matches) > 1:
            raise ValueError("Hook ID 不唯一，无法安全审批")
        hook = matches[0]
        current_fingerprint = self._fingerprint(hook)
        if fingerprint != current_fingerprint:
            raise ValueError("Hook 配置已变化，请刷新并重新审查")

        from datetime import datetime, timezone

        with self._trust_lock:
            records = self._read_trust_records()
            records[hook_id] = {
                "fingerprint": current_fingerprint,
                "trusted": bool(trusted),
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
            }
            self._trust_path.parent.mkdir(parents=True, exist_ok=True)
            temp = self._trust_path.with_name(
                f"{self._trust_path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
            )
            temp.write_text(
                json.dumps({"version": 1, "hooks": records}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(temp, self._trust_path)
        return {**hook, **self.trust_status(hook)}

    def _data(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        with self.path.open("rb") as stream:
            return tomllib.load(stream)

    def list(self) -> list[dict[str, Any]]:
        return list(self._data().get("hooks", []))

    def list_claude(self, cwd: str | None = None) -> list[dict[str, Any]]:
        hooks = claude_hook_settings(cwd)
        hooks.extend(self._plugin_hook_list())
        overrides = {
            item.get("id"): bool(item.get("enabled", True))
            for item in self._data().get("hook_overrides", [])
        }
        for item in hooks:
            item["enabled"] = overrides.get(item["id"], True)
        return hooks

    def list_all(self, cwd: str | None = None) -> list[dict[str, Any]]:
        legacy = [
            {**hook, "source": "atlas", "matcher": None}
            for hook in self.list()
        ]
        claude = []
        for group in self.list_claude(cwd):
            claude.append({
                "id": group["id"], "event": group["event"],
                "matcher": group.get("matcher"), "source": group.get("source", "claude"),
                "enabled": group.get("enabled", True), "hooks": group.get("hooks", []),
                "plugin_root": group.get("plugin_root"),
                "command": "; ".join(str(spec.get("command") or "") for spec in group.get("hooks", [])),
            })
        result: list[dict[str, Any]] = []
        for hook in [*legacy, *claude]:
            default_source = "claude" if isinstance(hook.get("hooks"), list) else "atlas"
            normalized = {**hook, "source": hook.get("source") or default_source}
            result.append({**normalized, **self.trust_status(normalized)})
        return result

    def set_hook_enabled(self, hook_id: str, enabled: bool, cwd: str | None = None) -> dict[str, Any]:
        legacy = self.list()
        for index, hook in enumerate(legacy):
            if hook.get("id") == hook_id:
                legacy[index] = {**hook, "enabled": bool(enabled)}
                self.save(legacy)
                return legacy[index]
        item = next((item for item in self.list_all(cwd) if item.get("id") == hook_id), None)
        if item is None:
            raise KeyError(hook_id)
        data = self._data()
        overrides = {
            row.get("id"): bool(row.get("enabled", True))
            for row in data.get("hook_overrides", [])
        }
        overrides[hook_id] = bool(enabled)
        data["hook_overrides"] = [{"id": key, "enabled": value} for key, value in overrides.items()]
        self._save_data(data)
        return {**item, "enabled": bool(enabled)}

    def recent_logs(self) -> list[dict[str, Any]]:
        return list(self._recent_logs)

    def save(self, hooks: list[dict[str, Any]]) -> None:
        data = self._data()
        data["hooks"] = hooks
        self._save_data(data)

    def _save_data(self, data: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        for hook in data.get("hooks", []):
            lines.extend([
                "[[hooks]]",
                f"id = {json.dumps(hook['id'], ensure_ascii=False)}",
                f"event = {json.dumps(hook['event'], ensure_ascii=False)}",
                f"command = {json.dumps(hook['command'], ensure_ascii=False)}",
                f"timeout_s = {int(hook.get('timeout_s', 30))}",
                f"enabled = {str(bool(hook.get('enabled', True))).lower()}",
                "",
            ])
        for override in data.get("hook_overrides", []):
            lines.extend([
                "[[hook_overrides]]",
                f"id = {json.dumps(override['id'], ensure_ascii=False)}",
                f"enabled = {str(bool(override.get('enabled', True))).lower()}",
                "",
            ])
        tmp = self.path.with_suffix(".toml.tmp")
        tmp.write_text("\n".join(lines), encoding="utf-8")
        os.replace(tmp, self.path)

    async def execute(
        self,
        event: str,
        payload: dict[str, Any],
        *,
        cwd: str | None = None,
        emit: Any = None,
        claude_hooks: Iterable[Mapping[str, Any]] = (),
        bridge_event_alias: bool = True,
    ) -> dict[str, Any]:
        blocked = {"blocked": False, "reason": "", "updated_input": None,
                   "additional_context": "", "continue": None, "logs": [],
                   "updated_tool_output": None, "feedback": "", "permission_decision": None,
                   "allowed": False, "ask_user": False, "retry": False}

        atlas_hooks = [
            hook for hook in self.list()
            if hook.get("enabled", True) and hook.get("event") == event
        ]
        claude_event = event if event in CLAUDE_HOOK_EVENTS else (
            _ATLAS_TO_CLAUDE.get(event) if bridge_event_alias else None
        )
        claude_hooks_to_run: list[Mapping[str, Any]] = []
        claude_payload: dict[str, Any] = {}
        if claude_event:
            claude_hooks_to_run = [
                item for item in self.list_claude(cwd) if item.get("enabled", True)
            ]
            claude_hooks_to_run.extend(
                item for item in claude_hooks if item.get("enabled", True)
            )
            claude_payload = _event_payload(claude_event, payload, cwd)

        # Preflight every matching hook before any command runs so an unreviewed
        # hook cannot execute after another hook has already produced side effects.
        for hook in atlas_hooks:
            atlas_hook = {**hook, "source": "atlas", "matcher": None}
            status = self.trust_status(atlas_hook)
            if not status["trusted"]:
                return self._deny_untrusted(atlas_hook, event, "atlas")
        for group in claude_hooks_to_run:
            if group.get("event") != claude_event or not _matches(
                group.get("matcher"), str(claude_event), claude_payload,
            ):
                continue
            matching_command = any(
                isinstance(spec, Mapping)
                and spec.get("type", "command") == "command"
                and _matches_if(spec.get("if"), str(claude_event), claude_payload)
                for spec in group.get("hooks", [])
            )
            reviewed_group = {**group, "source": group.get("source") or "claude"}
            if matching_command and not self.trust_status(reviewed_group)["trusted"]:
                return self._deny_untrusted(
                    reviewed_group, str(claude_event), str(reviewed_group["source"]),
                )

        for hook in atlas_hooks:
            started = time.monotonic()
            code, output, stderr = await _run_command(
                {"command": hook["command"], "timeout": hook.get("timeout_s", 30), "event": event},
                {"event": event, **payload}, cwd=cwd, plugin_root=None,
            )
            log = {"hook_id": hook["id"], "event": event, "exit_code": code,
                   "duration_ms": round((time.monotonic() - started) * 1000),
                   "output": output, "stderr": stderr, "source": "atlas"}
            self._record(log)
            blocked["logs"].append(log)
            if emit:
                maybe_awaitable = emit("hook.ran", log)
                if asyncio.iscoroutine(maybe_awaitable):
                    await maybe_awaitable
            if event == "tool.before" and code == 2:
                blocked.update(blocked=True, reason=stderr.strip() or output.strip() or "Blocked by hook")
                break

        if blocked["blocked"]:
            return blocked
        if claude_event:
            result = await execute_claude_hooks(
                claude_hooks_to_run, claude_event, payload, cwd=cwd, emit=emit,
            )
            for log in result["logs"]:
                self._record(log)
            prior_logs = blocked["logs"]
            blocked.update(result)
            blocked["logs"] = prior_logs + result["logs"]
        return blocked

    def _plugin_hook_list(self) -> list[dict[str, Any]]:
        hooks = self.plugin_hooks() if callable(self.plugin_hooks) else self.plugin_hooks
        return [dict(item) for item in hooks if isinstance(item, Mapping)]

    def _record(self, log: dict[str, Any]) -> None:
        self._recent_logs.append(log)
        del self._recent_logs[:-100]

    async def test(self, hook_id: str, cwd: str | None = None) -> dict[str, Any]:
        hook = next((item for item in self.list() if item.get("id") == hook_id), None)
        if hook:
            atlas_hook = {**hook, "source": "atlas", "matcher": None}
            if not self.trust_status(atlas_hook)["trusted"]:
                return self._deny_untrusted_sync(atlas_hook, hook["event"], "atlas")
            started = time.monotonic()
            code, output, stderr = await _run_command(
                {"command": hook["command"], "timeout": hook.get("timeout_s", 30), "event": hook["event"]},
                {"event": hook["event"], "run_id": "example-run",
                 "conversation_id": "example-conversation", "tool_name": "example",
                 "parameters": {}, "result": None}, cwd=None, plugin_root=None,
            )
            log = {"hook_id": hook_id, "event": hook["event"], "exit_code": code,
                   "duration_ms": round((time.monotonic() - started) * 1000),
                   "output": output, "stderr": stderr}
            self._record(log)
            return log
        group = next((item for item in self.list_claude(cwd) if item.get("id") == hook_id), None)
        if not group:
            raise KeyError(hook_id)
        reviewed_group = {**group, "source": group.get("source") or "claude"}
        if not self.trust_status(reviewed_group)["trusted"]:
            return self._deny_untrusted_sync(
                reviewed_group, str(reviewed_group.get("event") or ""), str(reviewed_group["source"]),
            )
        payload = {
            "session_id": "example-session", "tool_name": "example",
            "tool_input": {"command": "example", "file_path": "example.txt"},
            "cwd": cwd or "", "prompt": "example prompt",
        }
        result = await execute_claude_hooks([group], str(group["event"]), payload, cwd=cwd)
        for log in result["logs"]:
            log["hook_id"] = hook_id
            self._record(log)
        return {"hook_id": hook_id, "event": group["event"], **result}

    def _deny_untrusted_sync(
        self, hook: Mapping[str, Any], event: str, source: str,
    ) -> dict[str, Any]:
        hook_id = str(hook.get("id") or "")
        reason = f"Hook「{hook_id}」尚未通过信任审查，已阻止执行。请在 Hooks 设置页明确批准后重试。"
        log = {
            "hook_id": hook_id, "event": event, "exit_code": None,
            "duration_ms": 0, "output": "", "stderr": reason,
            "source": source, "trust_state": self.trust_status(hook)["trust_state"],
            "blocked": True, "review_required": True, "reason": reason,
        }
        self._record(log)
        return log

    def _deny_untrusted(
        self, hook: Mapping[str, Any], event: str, source: str,
    ) -> dict[str, Any]:
        log = self._deny_untrusted_sync(hook, event, source)
        return {
            "blocked": True, "reason": log["reason"], "updated_input": None,
            "additional_context": "", "continue": None, "logs": [log],
            "updated_tool_output": None, "feedback": "", "permission_decision": None,
            "allowed": False, "ask_user": False, "retry": False,
            "review_required": True,
        }


async def maybe_awaitable(value: Any) -> None:
    if asyncio.iscoroutine(value):
        await value
