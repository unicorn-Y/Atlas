"""W9 live smoke coverage for command limits, shell routing, and child environments."""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


def _timeout_and_shell_policy() -> None:
    from atlas.kernel.exec import command_timeout
    from atlas.tools import local_execution

    if command_timeout("echo ready") != 120:
        raise RuntimeError("Bash default timeout is not 120 seconds")
    if command_timeout("echo ready", 2_000) != 600:
        raise RuntimeError("Bash timeout was not clamped to the 10-minute maximum")
    with patch.dict(os.environ, {"BASH_DEFAULT_TIMEOUT_MS": "4000", "BASH_MAX_TIMEOUT_MS": "2000"}):
        if command_timeout("echo ready") != 4:
            raise RuntimeError("maximum Bash timeout fell below the configured default")
    if not local_execution._probe_shell(sys.executable):
        raise RuntimeError("executable validation rejected the active Python runtime")
    if local_execution._probe_shell(str(Path(sys.executable).parent / "missing-atlas-shell")):
        raise RuntimeError("shell discovery accepted a missing executable")
    with (
        patch.dict(os.environ, {"SHELL": "/preferred/zsh", "ATLAS_DEFAULT_SHELL": ""}),
        patch("atlas.config.get_config", return_value={"local_execution.default_shell": ""}),
        patch.object(local_execution, "_probe_shell", return_value=True),
    ):
        if local_execution._effective_shell("auto", None, windows=False) != ("zsh", "/preferred/zsh"):
            raise RuntimeError("an executable user SHELL path did not take precedence")
    print("Command policy: default/capped deadlines and executable probes passed", flush=True)


def _child_environment_policy() -> None:
    from atlas.engine.tools import child_process_env

    policy = {
        "inherit": "all",
        "exclude": ["ATLAS_W9_DROP_*", "ATLAS_W9_TOKEN"],
        "include_only": ["PATH", "ATLAS_W9_*", "PUBLIC_*"],
    }
    with (
        patch.dict(os.environ, {
            "ATLAS_W9_KEEP": "inherited",
            "ATLAS_W9_DROP_ME": "removed",
            "ATLAS_W9_TOKEN": "secret",
            "PUBLIC_VALUE": "visible",
            "ATLAS_API_KEY": "do-not-inherit",
        }, clear=False),
        patch.object(child_process_env, "_policy", return_value=policy),
        patch.object(child_process_env, "_scrub_enabled", return_value=True),
    ):
        result = child_process_env.child_process_env({
            "ATLAS_W9_KEEP": "set-value",
            "PUBLIC_EXTRA": "visible",
            "OUTSIDE_ALLOWLIST": "filtered",
        })
    if result.get("ATLAS_W9_KEEP") != "set-value":
        raise RuntimeError("explicit environment override did not follow inherited values")
    if "ATLAS_W9_DROP_ME" in result or "ATLAS_W9_TOKEN" in result:
        raise RuntimeError("exclude or sensitive-key filtering did not run")
    if "ATLAS_API_KEY" in result or "OUTSIDE_ALLOWLIST" in result:
        raise RuntimeError("credential scrub or include-only filtering failed")
    if result.get("PUBLIC_EXTRA") != "visible":
        raise RuntimeError("include-only filtering removed a matching explicit value")
    print("Child environment: sensitive filtering, exclude/set/include ordering passed", flush=True)


async def _bounded_process_output() -> None:
    from atlas.kernel.exec import ExecManager
    from atlas.tools import local_execution
    from atlas.tools.local_execution import LocalExecutionRuntime

    runtime = LocalExecutionRuntime()

    async def dispatch(name: str, arguments: dict[str, object]) -> dict[str, object]:
        return await runtime.call_tool(name, arguments, run_id="w9-smoke")

    with tempfile.TemporaryDirectory(prefix="atlas-w9-output-") as directory:
        script = "import sys; sys.stdout.write('A'*6000); sys.stderr.write('B'*6000)"
        manager = ExecManager(
            dispatch,
            output_dir=Path(directory) / "managed",
            local_runtime=runtime,
            max_output_bytes=4_096,
        )
        result = await manager.execute("local_exec", {
            "executable": sys.executable,
            "args": ["-c", script],
            "cwd": directory,
            "max_output_bytes": 2_048,
            "yield_time_ms": 1_000,
        })
        data = result.get("data", {})
        if not isinstance(data, dict) or data.get("state") != "completed":
            raise RuntimeError(f"head/tail output process did not complete: {result!r}")
        if data.get("output_omitted_bytes", 0) <= 0:
            raise RuntimeError("requested output/context budget did not retain a bounded head/tail")
        await manager.shutdown()

        manager = ExecManager(
            dispatch,
            output_dir=Path(directory) / "disk-capped",
            local_runtime=runtime,
            max_output_bytes=4_096,
        )
        with patch.object(local_execution, "MAX_PROCESS_LOG_BYTES", 512):
            result = await manager.execute("local_exec", {
                "executable": sys.executable,
                "args": ["-c", script],
                "cwd": directory,
                "max_output_bytes": 2_048,
                "yield_time_ms": 1_000,
            })
        data = result.get("data", {})
        if not isinstance(data, dict) or data.get("state") != "completed":
            raise RuntimeError(f"disk-capped output process did not complete: {result!r}")
        if data.get("output_bytes_dropped", 0) <= 0 or not data.get("output_truncated"):
            raise RuntimeError("disk output cap did not report omitted bytes")
        handle = next(iter(manager.handles.values()))
        if handle.output_path.stat().st_size > manager.MAX_OUTPUT_FILE_BYTES:
            raise RuntimeError("managed full-output file exceeded its configured cap")
        await manager.shutdown()
        await runtime.shutdown()
    print("Command output: metadata reserve, head/tail cap, and disk cap passed", flush=True)


async def main() -> None:
    _timeout_and_shell_policy()
    _child_environment_policy()
    await _bounded_process_output()
    print("W9 LIVE SMOKE PASS")


if __name__ == "__main__":
    asyncio.run(main())
