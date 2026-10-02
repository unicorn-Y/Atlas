from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any


@dataclass
class RunContext:
    task_id: str
    workspace: Path
    task_dir: Path
    prompt: str
    model: str | None = None
    timeout_seconds: float = 120
    config: dict[str, Any] = field(default_factory=dict)
    scenario: dict[str, Any] | None = None


@dataclass
class RunOutcome:
    exit_code: int | None
    stdout: str = ""
    stderr: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)
    duration_ms: float = 0.0
    error: str | None = None
    unsupported: list[str] = field(default_factory=list)


class ParticipantAdapter:
    name = "participant"

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self._process = None

    def availability(self) -> dict[str, Any]:
        raise NotImplementedError

    def build_command(self, context: RunContext) -> list[str]:
        raise NotImplementedError

    def run_once(self, context: RunContext) -> RunOutcome:
        raise NotImplementedError

    def parse_usage(self, outcome: RunOutcome) -> dict[str, int | float | None]:
        return {"tool_calls": None, "turns": None, "input_tokens": None,
                "output_tokens": None, "cached_tokens": None, "cost_usd": None}

    def supports(self, capability: str) -> bool:
        return False

    def cleanup(self) -> None:
        process = self._process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except Exception:
                process.kill()
        self._process = None


def sanitize_command(command: list[str], secrets: tuple[str, ...] = ()) -> list[str]:
    result: list[str] = []
    redact_next = False
    prompt_next = False
    for arg in command:
        if prompt_next:
            result.append("<prompt>")
            prompt_next = False
            continue
        if redact_next:
            result.append("<redacted>")
            redact_next = False
            continue
        if arg in {"--prompt", "--query", "--query-file"}:
            result.append(arg)
            prompt_next = arg != "--query-file"
            redact_next = arg == "--query-file"
            continue
        if arg in {"--api-key", "--token", "--password", "--header", "-H"}:
            result.append(arg)
            redact_next = True
            continue
        if any(arg.startswith(prefix) for prefix in ("--api-key=", "--token=", "--password=")):
            result.append(arg.split("=", 1)[0] + "=<redacted>")
            continue
        value = arg
        for secret in secrets:
            if secret:
                value = value.replace(secret, "<redacted>")
        if value.startswith(("sk-", "sk-ant-", "Bearer ")):
            value = "<redacted>"
        value = re.sub(r"(?i)(sk-ant-[A-Za-z0-9_-]{12,}|sk-[A-Za-z0-9_-]{20,}|Bearer\s+[A-Za-z0-9._~-]{12,})", "<redacted>", value)
        result.append(value)
    return result
