"""U45 acceptance scenarios; diagnostics never emit credentials or full run payloads."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "core"


def _safe_line(value: str) -> str:
    value = re.sub(r"(?i)(api[_-]?key|access[_-]?token|authorization|secret|password)(\s*[=:]\s*)[^\s,;]+", r"\1\2[REDACTED]", value)
    value = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "[REDACTED_KEY]", value)
    return value[:1200]


def _last_error_events() -> list[str]:
    atlas_root = Path(os.environ.get("ATLAS_ROOT", ""))
    if not atlas_root.is_dir():
        return []
    candidates = sorted((p for p in atlas_root.rglob("*.jsonl") if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)[:20]
    found: list[str] = []
    for path in candidates:
        try:
            lines = path.read_text("utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            if re.search(r'"(?:type|event|status)"\s*:\s*"?(?:error|failed|failure)', line, re.I):
                found.append(_safe_line(line))
                if len(found) >= 5:
                    return found
    return found


def _run(command: list[str], *, cwd: Path, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(CORE) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    result = subprocess.run(command, cwd=cwd, env=env, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=timeout, check=False)
    if result.returncode:
        print(f"FAIL command={command!r} exit_code={result.returncode}")
        print("stderr tail:\n" + "\n".join(_safe_line(line) for line in result.stderr.splitlines()[-40:]))
        events = _last_error_events()
        if events:
            print("last run error events:\n" + "\n".join(events))
        raise AssertionError(f"command failed: {command[0]}")
    return result


def check_marketplace_cli() -> None:
    """Exercise the real Click command tree without depending on a remote market."""
    result = _run([sys.executable, "-m", "atlas.cli", "marketplace", "--help"], cwd=CORE)
    for command in ("search", "show", "install", "uninstall"):
        assert command in result.stdout, result.stdout


async def check_office_live_sessions() -> None:
    """Run the same Office router lifecycle with a local in-memory service graph."""
    from atlas.api.app_services import AppServices
    from atlas.api.office_router import (
        _token_hash, office_live_conversation_status, queue_office_writeback,
        start_office_live_control, stop_office_live_control,
        sync_office_live_control, take_office_writeback,
    )

    token = "u45-local-only-test-token"
    digest = _token_hash(token)
    services = AppServices(office_sessions={digest: "u45-office-conversation"})
    started = await start_office_live_control(services, {
        "host": "Word", "document_name": "fixture.docx", "address": "selection",
        "content": "before edit",
    }, token)
    assert started["state"] == "live"
    synced = await sync_office_live_control(services, {"content": "after edit", "address": "selection"}, token)
    assert synced["changed"] and synced["previous_revision"] == started["revision"]
    await queue_office_writeback(services, {"conversation_id": "u45-office-conversation", "text": "Atlas change"})
    writeback = await take_office_writeback(services, token)
    assert writeback["writeback"]["base_revision"] == synced["revision"]
    state = await office_live_conversation_status("u45-office-conversation", services)
    assert state["sessions"][0]["revision"] == synced["revision"]
    stopped = await stop_office_live_control(services, token)
    assert stopped["state"] == "stopped"


def check_renderer_table_actions() -> None:
    """Render and exercise the Markdown table's real expanded/copy controls."""
    _run(["node", str(ROOT / "node_modules/vitest/vitest.mjs"), "run", "src/renderer/components/ConversationMessage.test.tsx"], cwd=ROOT / "frontend")


def main() -> None:
    check_marketplace_cli()
    asyncio.run(check_office_live_sessions())
    check_renderer_table_actions()
    print("U45 CHECK PASS")


if __name__ == "__main__":
    main()
