"""U37 acceptance scenarios. No Electron process or screenshots are used."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def scenario(
    name: str, command: list[str], *, cwd: Path = ROOT,
    env: dict[str, str] | None = None, basetemp: Path | None = None,
) -> None:
    print(f"U37 scenario: {name}", flush=True)
    child_env = dict(os.environ if env is None else env)
    result = subprocess.run(
        command, cwd=cwd, env=child_env, check=False,
        capture_output=basetemp is not None,
        encoding="utf-8", errors="replace",
    )
    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    if output:
        print(output, end="" if output.endswith("\n") else "\n", flush=True)
    if result.returncode:
        detail = f"U37 scenario failed ({result.returncode}): {name}"
        if output:
            detail += f"\npytest diagnostics:\n{output[-12000:]}"
        raise AssertionError(detail)
    print(f"U37 scenario PASS: {name}", flush=True)


def pytest_scenario(name: str, *nodeids: str) -> None:
    import sys

    normalized = [nodeid.removeprefix("core/") for nodeid in nodeids]
    # Plugin/MCP coverage must not inspect or mutate the user's Atlas home or
    # inherit state from earlier acceptance suites in the shared _atlasroot.
    with tempfile.TemporaryDirectory(prefix="atlas-u37-") as temp:
        isolated = Path(temp)
        isolated_root = isolated / "atlas-root"
        isolated_root.mkdir()
        isolated_data = isolated / "atlas-data"
        isolated_data.mkdir()
        home = isolated / "home"
        home.mkdir()
        scratch = isolated / "pytest-tmp"
        env = dict(os.environ)
        env.update({
            "ATLAS_ROOT": str(isolated_root),
            "ATLAS_DATA_DIR": str(isolated_data),
            "HOME": str(home),
            "USERPROFILE": str(home),
            "APPDATA": str(home / "AppData" / "Roaming"),
            "LOCALAPPDATA": str(home / "AppData" / "Local"),
            "TMP": str(isolated),
            "TEMP": str(isolated),
        })
        scenario(
            name,
            [sys.executable, "-m", "pytest", "--basetemp", str(scratch), *normalized, "-q"],
            cwd=ROOT / "core", env=env, basetemp=scratch,
        )


def main() -> int:
    pytest_scenario(
        "0 execute_code UTF-8 bridge, workspace-relative file tools, and agent dispatch",
        "core/tests/test_agent_enrichment.py::test_codeact_subprocess_uses_atlas_bridge_for_three_operations",
        "core/tests/test_agent_enrichment.py::test_execute_code_dispatches_through_current_agent_tool_pipeline",
    )
    pytest_scenario(
        "1 named scenario bundle persistence, conflict preview, and memory collection injection",
        "core/tests/test_scenario_bundles.py",
    )
    scenario(
        "2 chat-tab/window shortcut default resolution",
        ["cmd.exe", "/d", "/c", "call ..\\node_modules\\.bin\\vitest.cmd run --root . src/renderer/services/shortcuts.test.ts"],
        cwd=FRONTEND,
    )
    pytest_scenario(
        "3 automation deletion impact lists durable run and conversation references",
        "core/tests/test_automation_delete_impact.py",
    )
    pytest_scenario(
        "4 plugin manifest schema, paths, commands, hooks, MCP conflicts, and registration",
        "core/tests/test_plugin_validation.py", "core/tests/test_plugins.py",
    )
    pytest_scenario(
        "5 batch MCP reconnect filters disabled/healthy services and reports each outcome",
        "core/tests/test_mcp_batch_reconnect.py",
    )
    pytest_scenario(
        "6 curator state, pause, pin, duplicate handling, and candidate lifecycle",
        "core/tests/test_evolution_skill_curator.py", "core/tests/test_evolution.py",
    )
    scenario(
        "7 Composer skill search/keyboard-call preview and workspace file-drop routing",
        ["cmd.exe", "/d", "/c", "call ..\\node_modules\\.bin\\vitest.cmd run --root . src/renderer/components/Composer.test.ts src/renderer/services/fileDrop.test.ts"],
        cwd=FRONTEND,
    )
    print("Electron was not started; no screenshots were captured.", flush=True)
    print("U37 CHECK PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
