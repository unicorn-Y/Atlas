"""Shared bounded retry and redacted diagnostics for live-model check scripts."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import inspect
import json
import re
from typing import Any, Callable


@dataclass(frozen=True)
class AttemptResult:
    passed: bool
    answer: str = ""
    detail: str = ""
    value: Any = None


_SECRET_FIELD = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|password|secret|token)"
    r"(\s*[:=]\s*)([^\s,;]+)"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[^\s,;]+")
_KEY_SHAPES = re.compile(
    r"\b(?:dsk-|sk-|xox[baprs]-|gh[pousr]_|github_pat_|AIza|AKIA|ASIA)[A-Za-z0-9_-]{12,}\b"
)


def redact_diagnostic(value: str) -> str:
    value = _SECRET_FIELD.sub(r"\1\2[REDACTED]", value)
    value = _BEARER.sub("Bearer [REDACTED]", value)
    value = _KEY_SHAPES.sub("[REDACTED_KEY]", value)
    return value[-1600:]


def classify_failure(detail: str = "", answer: str = "") -> str:
    """Classify provider failures without depending on provider-specific exception classes."""
    text = f"{detail}\n{answer}".lower()
    status = re.search(r"(?:http(?: status)?\s*[:=]?\s*|status\s*[:=]\s*)([45]\d\d)\b", text)
    if status:
        return f"HTTP {status.group(1)}"
    for code in ("429", "503", "502", "504", "401", "403", "400"):
        if re.search(rf"\b{code}\b", text):
            return f"HTTP {code}"
    if any(marker in text for marker in ("timeout", "timed out", "超时", "readtimeout", "connecttimeout")):
        return "timeout"
    if any(marker in text for marker in ("relay rejected", "upstream rejected", "中转拒绝", "gateway rejected")):
        return "relay rejection"
    if not answer.strip() or "(empty/unavailable)" in text or "empty model answer" in text:
        return "empty reply"
    if any(marker in text for marker in ("refused", "rejected", "拒绝", "content filter")):
        return "provider/model rejection"
    return "model assertion/runtime failure"


def latest_run_log_path(since: float | None = None) -> str:
    """Find a run log path for diagnostics; return no contents, prompts, or credentials."""
    try:
        from atlas.logs import LOG_DIR

        paths = [path for path in (LOG_DIR / "runs").rglob("*.jsonl")
                 if path.is_file() and (since is None or path.stat().st_mtime >= since - 2)]
    except Exception:
        return "unavailable"
    paths.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return str(paths[0]) if paths else "none"


def latest_run_error_event(since: float | None = None) -> str:
    """Return a redacted summary of the newest failure event, never raw log JSON."""
    try:
        from atlas.logs import LOG_DIR

        paths = [path for path in (LOG_DIR / "runs").rglob("*.jsonl")
                 if path.is_file() and (since is None or path.stat().st_mtime >= since - 2)]
    except Exception:
        return "unavailable"
    paths.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    for path in paths[:20]:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in reversed(lines[-300:]):
            try:
                row = json.loads(line)
            except (ValueError, TypeError):
                continue
            if not isinstance(row, dict):
                continue
            event = str(row.get("event") or "")
            if not any(marker in event.lower() for marker in ("error", "fail", "timeout")):
                continue
            summary = {key: row[key] for key in (
                "timestamp", "event", "run_id", "tool", "tool_name", "error_type", "status",
                "status_code", "category", "error"
            ) if key in row}
            return redact_diagnostic(json.dumps(summary, ensure_ascii=False, default=str))
    return "none"


def _attempt_prompt(prompt: str, attempt_number: int) -> str:
    if attempt_number == 1:
        return prompt
    return (
        f"{prompt}\n\nValidation retry: the previous answer did not satisfy this check. "
        "Follow the requested operation and output marker exactly, verify that the requested "
        "result was produced, and do not add unrelated text."
    )


def _report_failure(name: str, attempt_number: int, result: AttemptResult) -> None:
    answer_tail = redact_diagnostic(result.answer)
    reason = redact_diagnostic(result.detail or "assertion did not match")
    category = classify_failure(result.detail, result.answer)
    log_path = latest_run_log_path()
    print(
        f"Real-model check {name} attempt {attempt_number}/2 failed: "
        f"failure_category={category}; run_log_path={log_path}; {reason}; "
        f"actual answer tail (redacted): {answer_tail or '(empty/unavailable)'}",
        flush=True,
    )


async def retry_real_model_check_async(
    name: str,
    prompt: str,
    attempt: Callable[[str, int], Any],
) -> AttemptResult:
    """Run a real-model assertion once, then repeat once with an explicit retry prompt.

    ``attempt`` returns AttemptResult and may be synchronous or asynchronous.
    Failed attempts print a redacted tail of the actual model answer.
    """
    last = AttemptResult(False, detail="no attempt completed")
    for attempt_number in (1, 2):
        try:
            outcome = attempt(_attempt_prompt(prompt, attempt_number), attempt_number)
            if inspect.isawaitable(outcome):
                outcome = await outcome
            if not isinstance(outcome, AttemptResult):
                raise TypeError("attempt callback must return AttemptResult")
            last = outcome
        except Exception as exc:  # provider transport failures are part of the live check
            last = AttemptResult(False, detail=f"{type(exc).__name__}: {exc}")
        if last.passed:
            print(f"PASS real-model check: {name} (attempt {attempt_number})", flush=True)
            return last
        _report_failure(name, attempt_number, last)
    raise AssertionError(
        f"real-model check failed after one retry: {name}; "
        f"last answer tail (redacted): {redact_diagnostic(last.answer) or '(empty/unavailable)'}"
    )


def retry_real_model_check(
    name: str,
    prompt: str,
    attempt: Callable[[str, int], Any],
) -> AttemptResult:
    """Synchronous entry point that does not wrap sync callbacks in an event loop."""
    last = AttemptResult(False, detail="no attempt completed")
    for attempt_number in (1, 2):
        try:
            outcome = attempt(_attempt_prompt(prompt, attempt_number), attempt_number)
            if inspect.isawaitable(outcome):
                outcome = asyncio.run(outcome)
            if not isinstance(outcome, AttemptResult):
                raise TypeError("attempt callback must return AttemptResult")
            last = outcome
        except Exception as exc:  # provider transport failures are part of the live check
            last = AttemptResult(False, detail=f"{type(exc).__name__}: {exc}")
        if last.passed:
            print(f"PASS real-model check: {name} (attempt {attempt_number})", flush=True)
            return last
        _report_failure(name, attempt_number, last)
    raise AssertionError(
        f"real-model check failed after one retry: {name}; "
        f"last answer tail (redacted): {redact_diagnostic(last.answer) or '(empty/unavailable)'}"
    )
