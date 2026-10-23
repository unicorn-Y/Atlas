"""Small offline proof for W0-3 hook events and FileChanged watcher dispatch."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from atlas.runtime.hooks import CLAUDE_HOOK_EVENTS, HookStore


async def main() -> None:
    expected = {
        "SessionStart", "InstructionsLoaded", "UserPromptSubmit", "MessageDisplay",
        "PreToolUse", "PermissionRequest", "PostToolUse", "PostToolUseFailure",
        "PostToolBatch", "PermissionDenied", "Notification", "SubagentStart",
        "SubagentStop", "TaskCreated", "TaskCompleted", "Stop", "StopFailure",
        "ConfigChange", "CwdChanged", "DirectoryAdded", "FileChanged",
        "WorktreeCreate", "WorktreeRemove", "PreCompact", "PostCompact",
        "PreModelSwitch", "PostModelSwitch", "SessionEnd",
    }
    assert CLAUDE_HOOK_EVENTS == expected, CLAUDE_HOOK_EVENTS ^ expected

    with tempfile.TemporaryDirectory(prefix="atlas-w0-hooks-") as raw:
        root = Path(raw)
        config = root / "settings.json"
        config.write_text("{}", encoding="utf-8")
        store = HookStore(root / "hooks.toml")
        observed: list[str] = []

        async def callback(event: str, payload: dict) -> dict:
            observed.append(event)
            return {}

        store.start_file_watcher("probe", [str(root)], cwd=str(root), callback=callback)
        await asyncio.sleep(0.5)
        config.write_text('{"hooks": {}}', encoding="utf-8")
        (root / "new-folder").mkdir()
        await asyncio.sleep(1.2)
        store.stop_file_watcher("probe")
        assert "FileChanged" in observed, observed
        assert "ConfigChange" in observed, observed
        assert "DirectoryAdded" in observed, observed
    print(f"W0-3 OK: {len(expected)} lifecycle event declarations verified; watcher emitted FileChanged, ConfigChange and DirectoryAdded.")


if __name__ == "__main__":
    asyncio.run(main())
