from __future__ import annotations

import json
import os
import shutil
import subprocess
import re
import ipaddress
import time
from typing import Any
from urllib.parse import urlsplit

from .base import ParticipantAdapter, RunContext, RunOutcome

USAGE_KEYS = ("tool_calls", "turns", "input_tokens", "output_tokens", "cached_tokens", "cost_usd")


def executable(adapter: ParticipantAdapter, default: str) -> str:
    cmd = adapter.config.get("command", default)
    if isinstance(cmd, list):
        cmd = cmd[0] if cmd else default
    return str(cmd)


def available(adapter: ParticipantAdapter, default: str) -> dict[str, Any]:
    cmd = executable(adapter, default)
    path = shutil.which(cmd)
    return {"available": bool(path), "reason": None if path else f"CLI not found: {cmd}", "path": path}


def _proxy_url(adapter: ParticipantAdapter) -> str | None:
    value = adapter.config.get("fault_proxy_url")
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = urlsplit(value)
        address = ipaddress.ip_address(parsed.hostname or "")
        if (parsed.scheme != "http" or not address.is_loopback or parsed.port is None
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or parsed.path.rstrip("/") != "/v1"):
            return None
    except (ValueError, TypeError):
        return None
    return value.rstrip("/")


def _fault_binding(adapter: ParticipantAdapter) -> dict[str, str] | None:
    binding = adapter.config.get("fault_proxy_binding")
    if not isinstance(binding, dict):
        return None
    kind = binding.get("kind")
    if kind == "env" and adapter.name == "hermes" and binding.get("name") == "OPENAI_BASE_URL":
        return {"kind": "env", "name": "OPENAI_BASE_URL"}
    return None


def run_command(adapter: ParticipantAdapter, context: RunContext, command: list[str], *, input_text: str | None = None,
                env: dict[str, str] | None = None) -> RunOutcome:
    start = time.monotonic()
    process = None
    try:
        process = subprocess.Popen(
            command, cwd=context.workspace, stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
        )
        try:
            out_bytes, err_bytes = process.communicate(
                input_text.encode("utf-8") if input_text is not None else None,
                timeout=context.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            else:
                process.kill()
            out_bytes, err_bytes = process.communicate()
            stdout, stderr = redact(out_bytes.decode("utf-8", "replace"), err_bytes.decode("utf-8", "replace"))
            return RunOutcome(None, stdout, stderr, jsonl_events(stdout),
                              (time.monotonic() - start) * 1000, "timeout")
        stdout, stderr = redact(out_bytes.decode("utf-8", "replace"), err_bytes.decode("utf-8", "replace"))
        events = jsonl_events(stdout)
        return RunOutcome(process.returncode, stdout, stderr, events,
                          (time.monotonic() - start) * 1000)
    except OSError as exc:
        _, message = redact("", str(exc))
        return RunOutcome(None, "", message, [], (time.monotonic() - start) * 1000, "launch_error")


def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def redact(stdout: str, stderr: str) -> tuple[str, str]:
    secrets = {v for k, v in os.environ.items() if any(x in k.upper() for x in ("KEY", "TOKEN", "SECRET", "PASSWORD")) and len(v) >= 8}
    for secret in secrets:
        stdout = stdout.replace(secret, "<redacted>")
        stderr = stderr.replace(secret, "<redacted>")
    stdout = re.sub(r"(?i)(sk-ant-[A-Za-z0-9_-]{12,}|sk-[A-Za-z0-9_-]{20,}|Bearer\s+[A-Za-z0-9._~-]{12,})", "<redacted>", stdout)
    stderr = re.sub(r"(?i)(sk-ant-[A-Za-z0-9_-]{12,}|sk-[A-Za-z0-9_-]{20,}|Bearer\s+[A-Za-z0-9._~-]{12,})", "<redacted>", stderr)
    return stdout, stderr


def redact_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    text, _ = redact(json.dumps(events, ensure_ascii=False), "")
    try:
        value = json.loads(text)
        return value if isinstance(value, list) else events
    except ValueError:
        return events


def kill_process_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        process.kill()


def jsonl_events(text: str) -> list[dict[str, Any]]:
    events = []
    for line in text.splitlines():
        try:
            value = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def empty_usage() -> dict[str, int | float | None]:
    return {key: None for key in USAGE_KEYS}


def sum_numeric(values: list[Any]) -> int | float | None:
    nums = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return sum(nums) if nums else None


def usage_from_events(outcome: RunOutcome, *, usage_paths: tuple[tuple[str, ...], ...], tool_types: tuple[str, ...] = (), turn_types: tuple[str, ...] = ()) -> dict[str, int | float | None]:
    out = empty_usage()
    events = outcome.events or jsonl_events(outcome.stdout)
    usage_records: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for event in events:
        for path in usage_paths:
            current: Any = event
            for key in path:
                current = current.get(key) if isinstance(current, dict) else None
            if isinstance(current, dict):
                usage_records.append((event, current))
                break
    def first_total(keys: tuple[str, ...]) -> int | float | None:
        # Final-result records aggregate preceding message/token events in several
        # CLIs. Use those records alone when present; otherwise sum per-call records.
        terminal = [(event, record) for event, record in usage_records
                    if event.get("type") in {"turn.completed", "run.completed", "result", "session.completed"}
                    or event.get("event") in {"run.completed", "result", "session.completed"}]
        selected = terminal or usage_records
        selected_values = []
        for _, record in selected:
            value = next((record[k] for k in keys if isinstance(record.get(k), (int, float))), None)
            if value is not None:
                selected_values.append(value)
        return sum_numeric(selected_values)
    out["input_tokens"] = first_total(("input_tokens", "inputTokens", "prompt_tokens"))
    out["output_tokens"] = first_total(("output_tokens", "outputTokens", "completion_tokens"))
    cached = []
    terminal = [(event, record) for event, record in usage_records
                if event.get("type") in {"turn.completed", "run.completed", "result", "session.completed"}
                or event.get("event") in {"run.completed", "result", "session.completed"}]
    for _, record in (terminal or usage_records):
        value = next((record[k] for k in ("cached_tokens", "cached_input_tokens", "cache_read_input_tokens", "cache_read", "cachedInputTokens") if isinstance(record.get(k), (int, float))), None)
        if value is None and isinstance(record.get("input_tokens_details"), dict):
            value = record["input_tokens_details"].get("cached_tokens")
        if value is None and isinstance(record.get("tokens"), dict):
            value = record["tokens"].get("cache", {}).get("read")
        if isinstance(value, (int, float)):
            cached.append(value)
    out["cached_tokens"] = cached[-1] if len(cached) == 1 else sum_numeric(cached)
    cost_records = []
    for _, record in (terminal or usage_records):
        value = next((record[k] for k in ("cost_usd", "total_cost_usd")
                      if isinstance(record.get(k), (int, float)) and not isinstance(record.get(k), bool)), None)
        if value is None and isinstance(record.get("cost"), dict):
            value = record["cost"].get("total")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            cost_records.append(value)
    if not cost_records:
        cost_records = [event[key] for event in events for key in ("total_cost_usd", "cost_usd")
                        if isinstance(event.get(key), (int, float)) and not isinstance(event.get(key), bool)]
    out["cost_usd"] = sum_numeric(cost_records)
    tc = sum(1 for e in events if e.get("type") in tool_types)
    tr = sum(1 for e in events if e.get("type") in turn_types)
    out["tool_calls"] = tc if tool_types and (tc or any(e.get("type") in tool_types for e in events)) else None
    out["turns"] = tr if turn_types and (tr or any(e.get("type") in turn_types for e in events)) else None
    return out


class CliAdapter(ParticipantAdapter):
    executable_name = ""

    def availability(self) -> dict[str, Any]:
        return available(self, self.executable_name)

    def _prefix(self) -> list[str]:
        configured = self.config.get("command")
        if isinstance(configured, list):
            command = [str(x) for x in configured]
        else:
            cmd = executable(self, self.executable_name)
            command = [cmd]
        return command

    def _run(self, context: RunContext, command: list[str], *, input_text: str | None = None) -> RunOutcome:
        binding = _fault_binding(self)
        if not binding or context.task_id != "20":
            return run_command(self, context, command, input_text=input_text)
        url = _proxy_url(self)
        if not url:
            return RunOutcome(None, error="fault_proxy_url_missing_or_not_loopback")
        env = os.environ.copy()
        env[binding["name"]] = url
        return run_command(self, context, command, input_text=input_text, env=env)

    def supports(self, capability: str) -> bool:
        if capability == "fault_proxy":
            binding = _fault_binding(self)
            url = self.config.get("fault_proxy_url")
            return bool(binding and (not url or _proxy_url(self)))
        return False
