# Adapted from NousResearch/hermes-agent@663362680b6ffa4fbffeb58f6682564239a1953b:
# tools/approval_floors.py (MIT, (c) Nous Research); hard blocks are Atlas-local.
"""Operations that cannot be approved by an auxiliary model."""

from __future__ import annotations

import re

_FLOORS = (
    re.compile(r"\bformat-volume\b", re.I),
    re.compile(r"\breg(?:\.exe)?\s+delete\s+HKLM\\SYSTEM", re.I),
    re.compile(r"\brm\s+-[^\n]*rf\s+/(?:\s|$)", re.I),
    re.compile(r"\bdd\b[^\n]*\bof=/dev/(?:sd|nvme|hd)", re.I),
)


def floor_reason(command: str) -> str | None:
    return "这条操作触及不可恢复的系统或磁盘底线。" if any(
        pattern.search(command or "") for pattern in _FLOORS
    ) else None
