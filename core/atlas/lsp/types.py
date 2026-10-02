# Atlas-original module (contract: ATLAS-C6A LSP core, owner: subagent A).
"""Atlas unified diagnostic type and the LSP-native-dict converter.

The service layer (client/manager/reporter) works with LSP-native diagnostic
dicts for delta bookkeeping; conversion to :class:`Diagnostic` happens once at
the facade boundary.  Positions are 1-based here (LSP wire format is 0-based).
"""
from __future__ import annotations

from dataclasses import dataclass

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFORMATION = "information"
SEVERITY_HINT = "hint"

_SEVERITY_BY_INT = {
    1: SEVERITY_ERROR,
    2: SEVERITY_WARNING,
    3: SEVERITY_INFORMATION,
    4: SEVERITY_HINT,
}


@dataclass(frozen=True)
class Diagnostic:
    file: str        # absolute path
    line: int        # 1-based
    column: int      # 1-based
    severity: str    # error|warning|information|hint
    code: str        # may be ""
    message: str
    source: str      # may be ""


def _severity_name(value: object) -> str:
    """LSP severity int 1..4 → name; missing/invalid → ``"error"``."""
    # bool is an int subclass but not a legal LSP severity.
    if not isinstance(value, bool) and isinstance(value, int):
        return _SEVERITY_BY_INT.get(value, SEVERITY_ERROR)
    return SEVERITY_ERROR


def from_lsp(raw: dict, file: str) -> Diagnostic:
    """LSP-native diagnostic dict → Atlas :class:`Diagnostic`.

    ``range.start.line``/``character`` are 0-based on the wire → 1-based here;
    severity int 1..4 → name, missing/invalid → ``"error"``; ``code``/``source``
    ``None`` → ``""``.  Non-string fields are coerced via ``str()``.
    """
    if not isinstance(raw, dict):
        raw = {}
    rng = raw.get("range") or {}
    start = rng.get("start") or {}
    try:
        line = max(1, int(start.get("line", 0)) + 1)
    except (TypeError, ValueError):
        line = 1
    try:
        column = max(1, int(start.get("character", 0)) + 1)
    except (TypeError, ValueError):
        column = 1

    code = raw.get("code")
    source = raw.get("source")
    message = raw.get("message")
    return Diagnostic(
        file=file,
        line=line,
        column=column,
        severity=_severity_name(raw.get("severity")),
        code="" if code is None else str(code),
        message="" if message is None else str(message),
        source="" if source is None else str(source),
    )


__all__ = [
    "SEVERITY_ERROR", "SEVERITY_WARNING", "SEVERITY_INFORMATION", "SEVERITY_HINT",
    "Diagnostic", "from_lsp",
]
