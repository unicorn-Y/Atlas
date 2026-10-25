"""U19 integration checks for worktree diff, rollouts, browser state and Android preview APIs."""
from __future__ import annotations

import asyncio
import base64
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE))

async def main() -> None:
    from atlas.api import browser_router, mobile_preview_router, workspace_router
    from atlas.logs import append_run_event

    with tempfile.TemporaryDirectory(prefix="atlas-u19-") as temp:
        root = Path(temp)
        repo = root / "repo"
        repo.mkdir()
        def git(*args: str) -> None:
            subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        git("init", "-q")
        git("config", "user.email", "u19@example.invalid")
        git("config", "user.name", "U19 Check")
        tracked = repo / "tracked.txt"
        tracked.write_text("before\n", encoding="utf-8")
        git("add", "tracked.txt")
        git("commit", "-qm", "baseline")
        tracked.write_text("after\n", encoding="utf-8")
        (repo / "new file.txt").write_text("untracked content\n", encoding="utf-8")
        diff = await workspace_router.get_workspace_git_diff(str(repo))
        assert "before" in diff["tracked_diff"] and "after" in diff["tracked_diff"]
        assert diff["source"] == "git-worktree"
        assert any(item["path"] == "new file.txt" and "untracked content" in item["diff"]
                   for item in diff["untracked"])

        from atlas import logs
        log_root = root / "logs"
        with patch.object(logs, "LOG_DIR", log_root):
            append_run_event("u19-rollout", "run_started", model="test-model")
            rollout = await workspace_router.get_run_rollout("u19-rollout")
            missing = await workspace_router.get_run_rollout("u19-missing")
        assert rollout["exists"] and rollout["event_count"] == 1
        assert rollout["events"][0]["event"] == "run_started" and Path(rollout["path"]).is_file()
        assert not missing["exists"] and missing["error"]

        extension_dir = root / "browser-extension"
        extension_dir.mkdir()
        (extension_dir / "manifest.json").write_text(json.dumps({"manifest_version": 3, "version": "19.0.0"}), encoding="utf-8")
        from atlas.engine_core.tools import browser_extension_bridge
        from atlas.tools.x2 import browser as browser_settings
        with patch.object(browser_settings, "get_browser_settings", return_value={"mode": "extension"}), \
                patch.object(browser_extension_bridge, "connection_info", return_value={
                    "url": "ws://127.0.0.1:8765/extension", "pairing_code": "test-only",
                    "extension_path": str(extension_dir), "connected": False}):
            extension_state = await browser_router.get_settings()
        assert extension_state["extension"]["installed"] and extension_state["extension"]["version"] == "19.0.0"
        assert extension_state["extension"]["connected"] is False

        from atlas.tools import mobile_simulator
        fake_devices = {"devices": [{"serial": "emulator-5554", "state": "device", "model": "Pixel_8"}]}
        async def fake_call(name: str, arguments: dict, workspace: str) -> dict:
            return fake_devices if name == "android_list_devices" else {"available": True, "avds": ["Pixel_8_API_35"]}
        with patch.object(mobile_simulator, "call_mobile_tool", new=AsyncMock(side_effect=fake_call)):
            inventory = await mobile_preview_router.android_preview_devices()
        assert inventory["devices"][0]["serial"] == "emulator-5554"
        assert inventory["avds"] == ["Pixel_8_API_35"]
        with patch.object(mobile_simulator, "call_mobile_tool", new=AsyncMock(side_effect=RuntimeError("Android adb is unavailable"))):
            unavailable = await mobile_preview_router.android_preview_devices()
        assert unavailable["available"] is False and "adb is unavailable" in unavailable["reason"]

        class FakeRequest:
            def __init__(self, value: dict): self.value = value
            async def json(self) -> dict: return self.value
        async def mobile_call(name: str, arguments: dict, workspace: str) -> dict:
            return {"serial": "emulator-5554", "avd": "Pixel_8_API_35"} if name == "android_start_emulator" else {"installed": True, "serial": arguments["serial"], "apkPath": arguments["apkPath"]}
        with patch.object(mobile_simulator, "call_mobile_tool", new=AsyncMock(side_effect=mobile_call)) as mobile_call_mock:
            started = await mobile_preview_router.android_preview_start(FakeRequest({"avd": "Pixel_8_API_35"}))
            installed = await mobile_preview_router.android_preview_install(FakeRequest({"workspace": str(repo), "serial": "emulator-5554", "apkPath": "app/debug.apk"}))
        assert started["serial"] == "emulator-5554" and installed["installed"]
        assert mobile_call_mock.await_args_list[0].args[0] == "android_start_emulator"
        assert mobile_call_mock.await_args_list[1].args[0] == "android_install_app"

        png = b"\x89PNG\r\n\x1a\n" + b"u19-frame"
        with patch.object(mobile_simulator, "_adb", return_value=SimpleNamespace(stdout=png)):
            frame = await mobile_preview_router.android_preview_screenshot("emulator-5554")
        assert base64.b64decode(frame["data_url"].split(",", 1)[1]) == png
        print("U19 API SCENARIOS PASS: tracked + untracked git diff; JSONL rollout + missing file; browser package/update and pairing state; Android device/AVD selection, start, install and PNG refresh response")


if __name__ == "__main__":
    asyncio.run(main())
    print("U19 CHECK PASS")
