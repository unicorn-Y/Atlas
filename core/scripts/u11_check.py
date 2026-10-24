"""Focused real-surface checks for U11 peer sessions, webhooks, and daemon lifecycle."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))

import pytest


def main() -> int:
    tests = [
        ROOT / "core" / "tests" / "test_u11_peer_sessions.py",
        ROOT / "core" / "tests" / "test_u11_webhooks.py",
        ROOT / "core" / "tests" / "test_u11_daemon.py",
    ]
    result = pytest.main(["-q", *(str(path) for path in tests)])
    if result != pytest.ExitCode.OK:
        return int(result)
    print("U11 CHECK PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
