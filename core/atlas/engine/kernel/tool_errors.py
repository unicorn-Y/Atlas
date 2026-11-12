# SPDX-License-Identifier: Apache-2.0
"""Structured, model-readable tool error payloads for the Atlas kernel.

The tool scheduler used to compress every handler exception into
``f"{type(exc).__name__}: {exc}"``. That string is what the model reads, so it
has to stay human-readable, but the runtime also needs machine-checkable
fields (``code`` / ``retryable`` / ``exit_code`` / ``stderr_tail`` ...). Both
forms are rendered from one :class:`ToolError`, so the text the model sees and
the dict the runtime records can never disagree.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

STDERR_TAIL_LINES = 12
MAX_MESSAGE_CHARS = 1200
MAX_TAIL_CHARS = 1200

#: Codes that a plain retry can plausibly resolve.
RETRYABLE_CODES = frozenset({
    "timeout",
    "resource_busy",
    "network_error",
    "rate_limited",
    "transient",
})

_HINTS: dict[str, str] = {
    "timeout": (
        "The tool exceeded its per-call deadline and was cancelled. Narrow the "
        "request (single file, tighter search, shorter command) or raise the "
        "budget with ATLAS_TOOL_TIMEOUT_SECONDS / ATLAS_TOOL_TIMEOUT_<TOOL>."
    ),
    "permission_denied": (
        "The run is not allowed to touch this path or command. Request the "
        "needed scope instead of retrying the same call unchanged."
    ),
    "not_found": "The path or resource does not exist. Re-check the name before retrying.",
    "resource_busy": (
        "Another process holds this file, port, or lock. Wait for it to finish "
        "or choose a different target, then retry."
    ),
    "network_error": "The remote side was unreachable. Check connectivity and the URL, then retry.",
    "rate_limited": "The remote side throttled the call. Back off before retrying.",
    "nonzero_exit": (
        "The command exited non-zero. Read the stderr tail, fix the cause, and "
        "only then run it again."
    ),
    "invalid_input": "The arguments were rejected before execution. Fix them and retry.",
    "unsupported": "This tool does not support the requested operation; choose another approach.",
    "cancelled": (
        "The call was cancelled and may have partial effects. Inspect state before retrying."
    ),
    "execution_error": (
        "An unexpected handler failure occurred. Inspect the message and the "
        "related logs before retrying."
    ),
}

# Keyword checks run only when the exception type alone is not conclusive.
_KEYWORD_CODES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("access is denied", "permission denied", "winerror 5", "eperm"), "permission_denied"),
    (("sharing violation", "winerror 32", "being used by another process", "resource busy",
      "locked by another", "file is locked"), "resource_busy"),
    (("timed out", "timeout", "deadline exceeded", "etimedout"), "timeout"),
    (("connection refused", "connection reset", "temporary failure in name resolution",
      "name or service not known", "getaddrinfo failed", "econnreset", "network is unreachable"),
     "network_error"),
    (("rate limit", "too many requests", "429"), "rate_limited"),
    (("no such file", "cannot find the path", "file not found", "not found", "404"), "not_found"),
    (("unsupported", "not implemented", "not supported"), "unsupported"),
)


class ToolTimeoutError(Exception):
    """Raised by the scheduler when one tool call exceeds its deadline."""

    def __init__(
        self,
        timeout_seconds: float,
        *,
        name: str = "",
        partial_output: str | None = None,
    ) -> None:
        self.timeout_seconds = float(timeout_seconds)
        self.name = name
        self.partial_output = partial_output
        super().__init__(
            f"tool {name or 'call'} exceeded its {self.timeout_seconds:g}s deadline"
        )


@dataclass(frozen=True, slots=True)
class ToolError:
    """One tool failure, in both machine and model shapes."""

    code: str
    message: str
    error_type: str = "ToolError"
    retryable: bool = False
    exit_code: int | None = None
    stderr_tail: str | None = None
    hint: str | None = None
    partial_output: str | None = None
    timeout_seconds: float | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "error_type": self.error_type,
            "retryable": self.retryable,
            "exit_code": self.exit_code,
            "stderr_tail": self.stderr_tail,
            "hint": self.hint,
        }
        if self.partial_output:
            payload["partial_output"] = self.partial_output
        if self.timeout_seconds is not None:
            payload["timeout_seconds"] = self.timeout_seconds
        return payload

    def as_text(self) -> str:
        """The human/model-facing form; never a bare ``str(dict)``."""
        lines = [f"{self.error_type}: {_clip(self.message, MAX_MESSAGE_CHARS)}"]
        facts = [f"code={self.code}", f"retryable={'yes' if self.retryable else 'no'}"]
        if self.exit_code is not None:
            facts.append(f"exit_code={self.exit_code}")
        if self.timeout_seconds is not None:
            facts.append(f"timeout_seconds={self.timeout_seconds:g}")
        lines.append(" | ".join(facts))
        if self.hint:
            lines.append(f"hint: {self.hint}")
        if self.stderr_tail:
            lines.append(f"stderr tail (last {STDERR_TAIL_LINES} lines):")
            lines.extend(f"  {line}" for line in self.stderr_tail.splitlines())
        if self.partial_output:
            lines.append("partial output before the timeout (truncated):")
            lines.extend(f"  {line}" for line in self.partial_output.splitlines())
        return "\n".join(lines)


def tail_text(
    text: Any, *, lines: int = STDERR_TAIL_LINES, chars: int = MAX_TAIL_CHARS,
) -> str | None:
    """Return the trailing lines of ``text``, bounded, or ``None`` when empty."""
    if text is None:
        return None
    if isinstance(text, (bytes, bytearray)):
        text = bytes(text).decode("utf-8", "replace")
    value = str(text).strip()
    if not value:
        return None
    value = "\n".join(value.splitlines()[-max(1, lines):])
    return _clip(value, chars)


def hint_for(code: str) -> str | None:
    return _HINTS.get(code)


def error_from_exception(exc: BaseException, *, name: str = "") -> ToolError:
    """Classify a handler exception into the structured error contract."""
    if isinstance(exc, ToolTimeoutError):
        return ToolError(
            code="timeout",
            message=str(exc),
            error_type="TimeoutError",
            retryable=True,
            hint=hint_for("timeout"),
            partial_output=tail_text(exc.partial_output),
            timeout_seconds=exc.timeout_seconds,
        )
    # ``error_type`` is rendered as the text prefix, so the message must not
    # repeat it: as_text() reproduces the historical ``Type: message`` form.
    text = f"{type(exc).__name__}: {exc}"
    lowered = text.lower()
    exit_code = _exit_code(exc)
    code = _code_from_keywords(lowered) or _code_from_type(exc)
    if code is None:
        code = "nonzero_exit" if exit_code not in (None, 0) else "execution_error"
    stderr = tail_text(
        getattr(exc, "stderr_tail", None)
        or getattr(exc, "stderr", None)
        or getattr(exc, "output", None)
    )
    return ToolError(
        code=code,
        message=str(exc),
        error_type=type(exc).__name__,
        retryable=code in RETRYABLE_CODES,
        exit_code=exit_code,
        stderr_tail=stderr,
        hint=hint_for(code),
    )


def error_from_output(output: Any, *, name: str = "") -> ToolError | None:
    """Build a structured error for a dispatch result that already failed."""
    if not isinstance(output, dict):
        return None
    if not (output.get("is_error") or output.get("error") or output.get("success") is False):
        return None
    data = output.get("data") if isinstance(output.get("data"), dict) else {}
    explicit_code = output.get("error_code") or output.get("error_category")
    message = _message_of(output)
    if not message:
        message = f"Tool {name or 'call'} reported an error."
    lowered = message.lower()
    code = str(explicit_code) if explicit_code else None
    if not code:
        code = _code_from_keywords(lowered) or _code_from_outcome(output)
    if not code:
        code = "execution_error"
    exit_code = _first_int(
        output.get("exit_code"), data.get("exit_code"), data.get("returncode"),
        output.get("returncode"),
    )
    if exit_code is not None and code == "execution_error":
        code = "nonzero_exit"
    hinted = output.get("retryable")
    retryable = bool(hinted) if hinted is not None else code in RETRYABLE_CODES
    return ToolError(
        code=code,
        message=message,
        error_type=str(output.get("error_type") or "ToolError"),
        retryable=retryable,
        exit_code=exit_code,
        stderr_tail=tail_text(
            output.get("stderr_tail") or output.get("stderr") or data.get("stderr")
            or data.get("stderr_tail")
        ),
        hint=str(output.get("hint") or hint_for(code) or "") or None,
    )


def decorate_failed_output(output: dict[str, Any], *, name: str = "") -> ToolError | None:
    """Attach the structured fields to an already-failed dispatch result.

    The tool's own ``error`` text is left byte-for-byte intact (tools author it
    with their own context); only additive keys are set, and only once.
    """
    if not isinstance(output, dict) or "error_info" in output:
        return None
    error = error_from_output(output, name=name)
    if error is None:
        return None
    output.setdefault("error_info", error.as_dict())
    output.setdefault("error_code", error.code)
    output.setdefault("retryable", error.retryable)
    if error.exit_code is not None:
        output.setdefault("exit_code", error.exit_code)
    if error.stderr_tail:
        output.setdefault("stderr_tail", error.stderr_tail)
    if error.hint:
        output.setdefault("hint", error.hint)
    return error


def error_output(error: ToolError, *, outcome: str = "failed", **extra: Any) -> dict[str, Any]:
    """The dict-shaped tool output for a failed call, including both error forms."""
    payload: dict[str, Any] = {
        "is_error": True,
        "outcome": outcome,
        "error": error.as_text(),
        "error_info": error.as_dict(),
        "error_code": error.code,
        "retryable": error.retryable,
    }
    if error.exit_code is not None:
        payload["exit_code"] = error.exit_code
    if error.stderr_tail:
        payload["stderr_tail"] = error.stderr_tail
    if error.hint:
        payload["hint"] = error.hint
    if error.partial_output:
        payload["partial_output"] = error.partial_output
    payload.update(extra)
    return payload


def _code_from_type(exc: BaseException) -> str | None:
    if isinstance(exc, (TimeoutError,)):
        return "timeout"
    if isinstance(exc, PermissionError):
        return "permission_denied"
    if isinstance(exc, (FileNotFoundError, NotADirectoryError)):
        return "not_found"
    if isinstance(exc, (ConnectionError,)):
        return "network_error"
    if isinstance(exc, json.JSONDecodeError):
        return "invalid_input"
    if isinstance(exc, (ValueError, TypeError, KeyError, AssertionError)):
        return "invalid_input"
    if isinstance(exc, (NotImplementedError,)):
        return "unsupported"
    if isinstance(exc, OSError):
        return "execution_error"
    return None


def _code_from_keywords(lowered: str) -> str | None:
    for needles, code in _KEYWORD_CODES:
        if any(needle in lowered for needle in needles):
            return code
    return None


def _code_from_outcome(output: dict[str, Any]) -> str | None:
    outcome = str(output.get("outcome") or output.get("state") or "").lower()
    return {
        "denied": "permission_denied",
        "cancelled": "cancelled",
        "timeout": "timeout",
        "timed_out": "timeout",
        "not_found": "not_found",
    }.get(outcome)


def _message_of(output: dict[str, Any]) -> str:
    for key in ("error", "message", "detail", "reason"):
        value = output.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            for inner in ("message", "error", "detail"):
                nested = value.get(inner)
                if isinstance(nested, str) and nested.strip():
                    return nested.strip()
    data = output.get("data")
    if isinstance(data, dict):
        for key in ("error", "message", "stderr_tail", "stderr"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _exit_code(exc: BaseException) -> int | None:
    for attr in ("exit_code", "returncode", "return_code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _first_int(*values: Any) -> int | None:
    for value in values:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"
