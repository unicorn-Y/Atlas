"""Availability and event normalization for the selectable external Agents."""

from __future__ import annotations

import shutil
import subprocess
import time
from typing import Any

AGENT_COMMANDS = {
    "codex": ("codex", "Codex", "codex", ["--version"], "安装 Codex CLI 后即可使用。"),
    "claude": ("claude", "Claude Code", "claude", ["--version"], "安装 Claude Code CLI 后即可使用。"),
    "hermes": ("hermes", "Hermes", "hermes", ["--version"], "安装 Hermes Agent CLI 后即可使用。"),
    "pi": ("pi", "Pi", "pi", ["--version"], "安装 Pi Coding Agent 后即可使用。"),
    "zcode": ("zcode", "ZCode", "zcode", ["--version"], "安装 ZCode CLI 后即可使用。"),
}

_STATUS_TTL = 60.0


def external_agent_status(
    cache: dict[str, Any], *, now: float | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Probe installed CLIs without network access and cache results for 60 seconds."""
    current = time.monotonic() if now is None else now
    if cache.get("expires_at", 0) > current and isinstance(cache.get("value"), dict):
        return cache["value"]
    agents: list[dict[str, Any]] = []
    for agent_id, (command, label, _binary, args, install_detail) in AGENT_COMMANDS.items():
        executable = shutil.which(command)
        version = None
        detail = install_detail
        available = False
        if executable:
            invocation = [executable, *args]
            if executable.casefold().endswith((".cmd", ".bat")):
                invocation = ["cmd", "/c", executable, *args]
            try:
                result = subprocess.run(
                    invocation, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5, check=False,
                )
                if result.returncode == 0:
                    version = (result.stdout or result.stderr).strip()[:300] or "已安装"
                    detail = ""
                    available = True
                else:
                    detail = f"已找到程序，但版本检查失败。{install_detail}"
            except (OSError, subprocess.SubprocessError):
                detail = f"已找到程序，但无法启动。{install_detail}"
        agents.append({
            "id": agent_id, "name": label, "available": available,
            "version": version, "detail": detail,
        })
    value = {"agents": agents}
    cache.clear()
    cache.update({"expires_at": current + _STATUS_TTL, "value": value})
    return value


def normalize_external_event(
    event_type: str, data: dict[str, Any], pending_tools: dict[str, dict[str, Any]],
) -> list[tuple[str, dict[str, Any]]]:
    """Map ACP updates and CLI text events into the Atlas Runtime Event Protocol."""
    update = data.get("update", data)
    kind = str(update.get("sessionUpdate", update.get("type", event_type)))
    if kind in {"agent_message_chunk", "text", "message_delta"}:
        content = update.get("content", {})
        text = content.get("text", "") if isinstance(content, dict) else str(content or "")
        if not text:
            text = str(data.get("text", ""))
        return [("reply.delta", {"content": text})] if text else []
    if kind in {"tool_call", "tool_call_update"}:
        call_id = str(update.get("toolCallId", update.get("id", "")))
        existing = pending_tools.get(call_id, {})
        title = str(update.get("title", update.get("name", existing.get("name", "unknown"))))
        name = title if title.startswith("external:") else f"external:{title}"
        arguments = update.get("rawInput", update.get("input", existing.get("arguments", {})))
        if not isinstance(arguments, dict):
            arguments = {"input": arguments}
        if kind == "tool_call":
            pending_tools[call_id] = {"name": title, "arguments": arguments}
            return [("tool.started", {
                "tool_call_id": call_id, "name": name, "arguments": arguments,
            })]
        status = str(update.get("status", "")).casefold()
        if status in {"completed", "failed", "error"}:
            pending_tools.pop(call_id, None)
            return [("tool.completed", {
                "tool_call_id": call_id, "name": name,
                "arguments": arguments, "result": update.get("content", update.get("result")),
                "is_error": status != "completed",
            })]
        return []
    if kind in {"error", "response_error"}:
        detail = data.get("detail", update.get("message", update.get("error", "外部 Agent 执行失败。")))
        return [("run.failed", {"category": "external_agent", "detail": str(detail)})]
    return []
