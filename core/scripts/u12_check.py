"""Focused real-surface checks for the three U12 construction items."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))

import pytest


def main() -> int:
    result = pytest.main(["-q", str(ROOT / "core" / "tests" / "test_u12_features.py")])
    if result != pytest.ExitCode.OK:
        return int(result)
    print("U12 CHECK PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
