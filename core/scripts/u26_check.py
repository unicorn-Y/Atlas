"""Behavior checks for the U26 construction batch; uses local fakes and no Electron UI."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "core"
FRONTEND = ROOT / "frontend"


def run_scene(title: str, command: list[str], *, cwd: Path = ROOT, timeout: int = 1800) -> bool:
    print(f"U26 scene: {title}", flush=True)
    result = subprocess.run(
        command, cwd=cwd, env=os.environ.copy(), capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=timeout,
    )
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", file=sys.stderr)
    if result.returncode:
        print(f"U26 scene failed: {title}", flush=True)
        return False
    print(f"U26 scene passed: {title}", flush=True)
    return True


def vitest(files: str) -> list[str]:
    # cmd.exe is needed for the Windows npx.cmd shim; the command and paths are fixed here.
    return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", f"npx vitest run {files}"]


def main() -> int:
    scenes = [
        ("audio device selection, output routing and channel transcription",
         [sys.executable, "-m", "pytest", "-q", str(CORE / "tests" / "test_channel_audio.py")], ROOT),
        ("independent voice HUD ASR status, transcript and error lifecycle",
         vitest("src/renderer/services/voiceHudProtocol.test.ts src/renderer/services/vimEditor.test.ts"), FRONTEND),
        ("diagnostic traces, audit history, storage migration and reset preview",
         [sys.executable, "-m", "pytest", "-q", str(CORE / "tests" / "test_maintenance.py")], ROOT),
        ("theme v1 migration, directory validation, locale resources and renderer interactions",
         vitest("src/renderer/shell/themes.test.ts src/renderer/services/i18n.test.ts src/renderer/services/audioDevices.test.ts src/renderer/services/speechPlayback.test.ts"), FRONTEND),
        ("complete static and interpolated renderer locale coverage",
         ["node", "scripts/check-i18n-coverage.cjs"], FRONTEND),
    ]
    for title, command, cwd in scenes:
        if not run_scene(title, command, cwd=cwd):
            print("U26 CHECK FAIL", flush=True)
            return 1
    print("Electron was not started; tests use temporary data and local fake services.", flush=True)
    print("U26 CHECK PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
