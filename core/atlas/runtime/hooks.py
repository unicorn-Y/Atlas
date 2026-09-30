"""User-configured command hooks for Atlas runtime events."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
import tomllib
from pathlib import Path
from typing import Any


class HookStore:
    EVENTS = {"run.started", "tool.before", "tool.after", "run.completed", "run.failed"}

    def __init__(self, path: Path) -> None:
        self.path = path

    def list(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self.path.open("rb") as stream:
            data = tomllib.load(stream)
        return list(data.get("hooks", []))

    def save(self, hooks: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        for hook in hooks:
            lines.extend(
                [
                    "[[hooks]]",
                    f"id = {json.dumps(hook['id'], ensure_ascii=False)}",
                    f"event = {json.dumps(hook['event'], ensure_ascii=False)}",
                    f"command = {json.dumps(hook['command'], ensure_ascii=False)}",
                    f"timeout_s = {int(hook.get('timeout_s', 30))}",
                    f"enabled = {str(bool(hook.get('enabled', True))).lower()}",
                    "",
                ]
            )
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
    ) -> dict[str, Any]:
        blocked = {"blocked": False, "reason": ""}
        for hook in self.list():
            if not hook.get("enabled", True) or hook.get("event") != event:
                continue
            started = time.monotonic()
            code, output = 1, ""
            proc = None
            try:
                if os.name == "nt":
                    command = ["cmd.exe", "/d", "/s", "/c", str(hook["command"])]
                else:
                    command = ["sh", "-lc", str(hook["command"])]
                proc = await asyncio.create_subprocess_exec(
                    *command,
                    cwd=cwd or None,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                stdout, _stderr = await asyncio.wait_for(
                    proc.communicate(
                        json.dumps({"event": event, **payload}, ensure_ascii=False).encode()
                    ),
                    timeout=max(1, int(hook.get("timeout_s", 30))),
                )
                code, output = proc.returncode or 0, stdout[:4096].decode("utf-8", errors="replace")
            except Exception as exc:
                if proc is not None and proc.returncode is None:
                    proc.kill()
                    await proc.wait()
                output = str(exc)[:4096]
            result = {
                "hook_id": hook["id"],
                "event": event,
                "exit_code": code,
                "duration_ms": round((time.monotonic() - started) * 1000),
                "output": output,
            }
            if emit:
                await emit("hook.ran", result)
            if event == "tool.before" and code == 2:
                blocked = {"blocked": True, "reason": output.strip() or "Blocked by hook"}
                break
        return blocked

    async def test(self, hook_id: str) -> dict[str, Any]:
        hook = next((item for item in self.list() if item.get("id") == hook_id), None)
        if not hook:
            raise KeyError(hook_id)
        started = time.monotonic()
        command = (
            ["cmd.exe", "/d", "/s", "/c", str(hook["command"])]
            if os.name == "nt"
            else ["sh", "-lc", str(hook["command"])]
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                cwd=None,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(
                proc.communicate(
                    json.dumps(
                        {
                            "event": hook["event"],
                            "run_id": "example-run",
                            "conversation_id": "example-conversation",
                            "tool_name": "example",
                            "parameters": {},
                            "result": None,
                        },
                        ensure_ascii=False,
                    ).encode()
                ),
                timeout=max(1, int(hook.get("timeout_s", 30))),
            )
            code, output = proc.returncode or 0, stdout[:4096].decode("utf-8", errors="replace")
        except Exception as exc:
            code, output = 1, str(exc)[:4096]
        return {
            "hook_id": hook_id,
            "event": hook["event"],
            "exit_code": code,
            "duration_ms": round((time.monotonic() - started) * 1000),
            "output": output,
        }
