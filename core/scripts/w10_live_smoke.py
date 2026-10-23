"""W10 command shell identity and Git push boundary smoke scenarios."""
from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch


async def _shell_identity_and_argv() -> None:
    from atlas.kernel.exec import ExecManager
    from atlas.tools.local_execution import LocalExecutionRuntime, _shell_identity

    runtime = LocalExecutionRuntime()
    tools = runtime.get_tools_for_llm()
    shell_schema = next(
        item["function"] for item in tools if item["function"].get("name") == "local_shell"
    )
    name, executable = _shell_identity()
    marker = f"Shell: {name} ({executable})"
    if marker not in shell_schema["description"]:
        raise RuntimeError("local_shell description omitted the actual shell and executable path")
    command = {
        "bash": "printf W10-SHELL-IDENTITY",
        "zsh": "printf W10-SHELL-IDENTITY",
        "powershell": "Write-Output W10-SHELL-IDENTITY",
        "cmd": "echo W10-SHELL-IDENTITY",
    }[name]
    with tempfile.TemporaryDirectory(prefix="atlas-w10-shell-") as directory:
        result = await runtime.call_tool(
            "local_shell", {"shell": name, "command": command, "cwd": directory},
            run_id="w10-smoke-shell",
        )
        data = result.get("data")
        if not isinstance(data, dict) or data.get("shell") != marker:
            raise RuntimeError(f"local_shell result did not report its actual shell: {data!r}")
        if "W10-SHELL-IDENTITY" not in data.get("stdout", ""):
            raise RuntimeError(f"shell identity command did not complete: {data!r}")
        direct = await runtime.call_tool(
            "local_exec", {
                "executable": os.environ.get("PYTHON", "python"),
                "args": ["-c", "print('W10-ARGV')"], "cwd": directory,
            }, run_id="w10-smoke-argv",
        )
        direct_data = direct.get("data")
        if not isinstance(direct_data, dict) or direct_data.get("shell") != "Shell: none (direct argv)":
            raise RuntimeError("local_exec result did not identify direct argv execution")
        if "W10-ARGV" not in direct_data.get("stdout", ""):
            raise RuntimeError(f"argv execution failed: {direct_data!r}")
        async def dispatch(name: str, arguments: dict[str, object]) -> dict[str, object]:
            return await runtime.call_tool(name, arguments, run_id="w10-smoke-exec-manager")

        manager = ExecManager(
            dispatch, output_dir=Path(directory) / "managed", local_runtime=runtime,
        )
        managed = await manager.execute("local_shell", {
            "shell": name, "command": command, "cwd": directory, "yield_time_ms": 1_000,
        })
        managed_data = managed.get("data")
        if not isinstance(managed_data, dict) or managed_data.get("shell") != marker:
            raise RuntimeError(f"ExecManager dropped the actual shell identity: {managed_data!r}")
        content_text = "\n".join(
            str(item.get("text", "")) for item in managed.get("content", [])
            if isinstance(item, dict)
        )
        if marker not in content_text:
            raise RuntimeError("model-facing ExecManager result omitted the shell identity")
        await manager.shutdown()
    await runtime.shutdown()
    print("Shell contract: model description and each command result name the actual shell/path; argv is labeled shell-free", flush=True)


async def _detached_head_push_guard() -> None:
    from atlas.tools.local_execution import (
        LocalExecutionRuntime,
        _git_child_environment,
        git_command_timeout,
    )

    runtime = LocalExecutionRuntime()
    if (git_command_timeout("status") != 15
            or git_command_timeout("diff") != 20
            or git_command_timeout("push") != 600
            or git_command_timeout("push", 2) != 2):
        raise RuntimeError("Git action timeout budgets did not match the configured defaults")
    with patch.dict(os.environ, {
        "GIT_DIR": "C:/missing/wrong.git",
        "GIT_WORK_TREE": "C:/missing/wrong-worktree",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.worktree",
        "GIT_CONFIG_VALUE_0": "C:/missing/redirected",
    }, clear=False):
        safe_env = _git_child_environment()
    if any(name.upper().startswith("GIT_CONFIG_KEY_") for name in safe_env):
        raise RuntimeError("inherited GIT_CONFIG_KEY_* settings were not stripped")
    if any(name in safe_env for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_CONFIG_COUNT")):
        raise RuntimeError("inherited repository-redirection variables were not stripped")
    if safe_env.get("GIT_TERMINAL_PROMPT") != "0" or safe_env.get("GIT_PAGER") != "cat":
        raise RuntimeError("Git child environment was not made non-interactive")
    with tempfile.TemporaryDirectory(prefix="atlas-w10-git-") as directory:
        repo = Path(directory) / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
        env = os.environ.copy()
        env.update({
            "GIT_AUTHOR_NAME": "Atlas W10 Smoke",
            "GIT_AUTHOR_EMAIL": "w10-smoke@example.invalid",
            "GIT_COMMITTER_NAME": "Atlas W10 Smoke",
            "GIT_COMMITTER_EMAIL": "w10-smoke@example.invalid",
        })
        subprocess.run(["git", "-C", str(repo), "-c", "init.defaultBranch=main", "commit", "--allow-empty", "-m", "fixture"], env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with patch.dict(os.environ, {"GIT_DIR": "C:/missing/wrong.git"}, clear=False):
            status = await runtime.call_tool(
                "local_git", {"action": "status", "repo": str(repo)}, run_id="w10-smoke-git-env",
            )
        if status.get("is_error") or "##" not in str((status.get("data") or {}).get("stdout", "")):
            raise RuntimeError(f"local_git followed a parent GIT_DIR instead of the requested repository: {status!r}")
        subprocess.run(["git", "-C", str(repo), "checkout", "--detach", "--quiet", "HEAD"], check=True)
        result = await runtime.call_tool(
            "local_git", {"action": "push", "repo": str(repo)}, run_id="w10-smoke-detached-push",
        )
        if not result.get("is_error") or "detached HEAD" not in str(result.get("content", "")):
            raise RuntimeError(f"detached HEAD push was not rejected before push: {result!r}")
    await runtime.shutdown()
    print("Git runner: action deadlines, repo environment isolation, non-interactive output, and detached-HEAD guard passed", flush=True)


async def main() -> None:
    root_value = os.environ.get("ATLAS_ROOT")
    if not root_value or not Path(root_value).is_dir():
        raise RuntimeError("ATLAS_ROOT must point at the configured local Atlas test environment")
    await _shell_identity_and_argv()
    await _detached_head_push_guard()
    print("W10 LIVE SMOKE PASS")


if __name__ == "__main__":
    asyncio.run(main())
