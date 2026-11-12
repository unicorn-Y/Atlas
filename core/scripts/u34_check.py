"""Focused U34 scenarios for items 0–6; never starts Electron or captures screenshots."""
from __future__ import annotations

import os
import importlib.util
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "core"
FRONTEND = ROOT / "frontend"


def run(title: str, command: list[str], cwd: Path = ROOT) -> None:
    print(f"U34 scenario: {title}", flush=True)
    result = subprocess.run(
        command,
        cwd=cwd,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800,
    )
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", file=sys.stderr)
    if result.returncode:
        raise RuntimeError(f"{title} failed with exit {result.returncode}")
    print(f"U34 scenario PASS: {title}", flush=True)


def pytest(*files: str, croniter: bool = False) -> list[str]:
    # Run pytest with this checker's interpreter. A separately resolved pytest
    # may create a fresh project environment in a worktree where the entry point
    # point is not installed, even though the parent interpreter has pytest.
    if croniter and importlib.util.find_spec("croniter") is None:
        raise RuntimeError("croniter is required; invoke this checker with an interpreter that includes croniter")
    return [sys.executable, "-m", "pytest", "-q", *(str(CORE / "tests" / item) for item in files)]


def vitest(files: str) -> list[str]:
    # Windows npx is a cmd shim; keep the fixed test path as one trusted command string.
    return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", f"npx vitest run {files}"]


def check_fullscreen_contract() -> None:
    ipc = (FRONTEND / "src/shared/ipc.ts").read_text(encoding="utf-8")
    main = (FRONTEND / "src/main/electron.ts").read_text(encoding="utf-8")
    app = (FRONTEND / "src/renderer/App.tsx").read_text(encoding="utf-8")
    thread = (FRONTEND / "src/renderer/components/MessageThread.tsx").read_text(encoding="utf-8")
    required = {
        "shared IPC type": "setWindowFullScreen",
        "trusted main-process handler": "setFullScreen",
        "renderer command": "/tui",
        "page navigation": "PageDown",
        "Escape exit": "Escape",
        "selection copy": "Ctrl+Shift+C",
    }
    sources = {"shared IPC type": ipc, "trusted main-process handler": main,
               "renderer command": app, "page navigation": thread,
               "Escape exit": thread, "selection copy": thread}
    missing = [label for label, token in required.items() if token not in sources[label]]
    if missing:
        raise AssertionError(f"fullscreen wiring missing: {missing}")


def main() -> int:
    # Item 0: default Atlas ownership, ordinary-chat keyword matching and audit.
    run("0 default Atlas standing-order match and audit",
        pytest("test_standing_orders.py"))

    # Item 1: persistent Daybreak preference and stable long-task prompt semantics.
    run("1 Daybreak preference round-trip and resume prompt",
        pytest("test_daybreak.py"))

    # Item 2: exercise the IPC/renderer command contract without opening Electron.
    print("U34 scenario: 2 fullscreen IPC and keyboard contract", flush=True)
    check_fullscreen_contract()
    print("U34 scenario PASS: 2 fullscreen IPC and keyboard contract", flush=True)

    # Item 3: model and reasoning fields cross API, durable store, scheduler and dispatch.
    run("3 automation model/reasoning API, store and dispatch",
        pytest("test_automation_store.py", "test_automation_router.py", "test_automation_engine.py",
               croniter=True))

    # Item 4: persisted UI-only child activity, runtime wire events and unread dedupe.
    run("4 persisted child activity and context projection",
        pytest("test_atlas_session_sync.py", "test_api_runtime.py"))
    run("4 renderer event normalization",
        vitest("src/renderer/services/runtimeEvents.test.ts"), FRONTEND)
    run("4 renderer unread dedupe",
        vitest("src/renderer/store/useAtlasStore.test.ts -t \"counts unread updates once\""), FRONTEND)

    # Item 5: CLI image parsing, validation, JSONL events and multimodal dispatch fake.
    run("5 CLI image input and multimodal dispatch",
        [sys.executable, "-m", "pytest", "-q",
         str(CORE / "tests/test_cli_headless.py"), "-k", "exec_"])

    # Item 6: dangerous suggestion filtering and home carousel/fill rendering.
    run("6 backend dynamic suggestion safety",
        pytest("test_suggestions_safety.py"))
    run("6 renderer safety and home example carousel",
        vitest("src/renderer/services/suggestionSafety.test.ts src/renderer/shell/HomeView.test.tsx"),
        FRONTEND)

    print("Electron was not started; renderer UI behavior is covered by source tests and desktop acceptance steps.",
          flush=True)
    print("U34 CHECK PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
