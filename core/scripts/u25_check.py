"""Behavior checks for the four U25 construction items using local fakes only."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "core"

SCENES = (
    ("0 channel dependency install and MCP launch diagnostics", "test_channel_dependencies.py", "test_mcp_startup_diagnostics.py"),
    ("1 inbound audio transcription, preservation, deduplication and failures", "test_channel_audio.py"),
    ("2 loopback dashboard access, status pages and CLI lifecycle", "test_dashboard.py"),
    ("3 arbitrary channel target send, idempotency and retry status", "test_channel_manual_send.py"),
    ("4 self-hosted SSH environment, task attempts, scheduling, snapshots and patch apply", "test_remote_tasks.py"),
)


def main() -> int:
    for title, *files in SCENES:
        print(f"U25 scene: {title}", flush=True)
        command = [sys.executable, "-m", "pytest", "-q", *(str(CORE / "tests" / name) for name in files)]
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.stdout:
            print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
        if result.stderr:
            print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", file=sys.stderr)
        if result.returncode:
            print(f"U25 scene failed: {title}", flush=True)
            print("U25 CHECK FAIL", flush=True)
            return result.returncode
        print(f"U25 scene passed: {title}", flush=True)
    print("External services use fake/local adapters; no real SSH host or Electron process was started.", flush=True)
    print("U25 CHECK PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
