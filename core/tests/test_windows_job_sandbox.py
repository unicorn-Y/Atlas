"""Per-call Windows sandbox: the boundary must be real and the report honest.

The ledger's E14 says Atlas only had a whole-run Docker container plus a prompt
instruction, so on a host without Docker a "read-only" call could still write.
A Windows Job Object gives the native primitive: the child and everything it
spawns live in the job, and closing the job terminates the tree.

Two things these tests insist on:
- the containment is actually applied (``enforced`` is True only after a real
  AssignProcessToJobObject succeeded), and
- ``danger-full-access`` reports ``enforced: False`` rather than pretending.
"""

from __future__ import annotations

import asyncio
import sys

import pytest

from atlas.windows_job_sandbox import (
    MODES,
    JobSandboxUnavailable,
    run_in_job,
    sandbox_capabilities,
)

pytestmark = pytest.mark.unit


def test_capabilities_never_claim_a_filesystem_boundary():
    caps = sandbox_capabilities()
    assert caps["backend"] == "win32job"
    assert "read-only" not in caps["modes"], (
        "a Job Object cannot enforce a filesystem ACL, so read-only must not be advertised"
    )
    assert "docker" in caps["detail"].lower() or "filesystem" in caps["detail"].lower()


def test_unknown_mode_is_refused():
    with pytest.raises(ValueError):
        asyncio.run(run_in_job(["cmd", "/c", "echo"], mode="sandbox-ish"))


@pytest.mark.skipif(sys.platform != "win32", reason="Job Objects are Windows-only")
def test_command_runs_inside_the_job_and_reports_enforcement():
    result = asyncio.run(run_in_job(["cmd", "/c", "echo hello-from-job"],
                                    mode="workspace-write", timeout=30))
    assert result.exit_code == 0
    assert "hello-from-job" in result.stdout
    assert result.enforced is True
    assert result.timed_out is False


@pytest.mark.skipif(sys.platform != "win32", reason="Job Objects are Windows-only")
def test_timeout_terminates_the_whole_tree():
    result = asyncio.run(run_in_job(["cmd", "/c", "ping -n 20 127.0.0.1"],
                                    mode="workspace-write", timeout=2))
    assert result.timed_out is True
    assert result.killed_tree is True
    assert result.enforced is True


@pytest.mark.skipif(sys.platform != "win32", reason="Job Objects are Windows-only")
def test_danger_full_access_reports_no_enforcement():
    result = asyncio.run(run_in_job(["cmd", "/c", "echo full"],
                                    mode="danger-full-access", timeout=30))
    assert result.exit_code == 0
    assert result.enforced is False, "full access must not claim containment"


def test_modes_are_the_closed_set_the_ledger_names():
    assert MODES == ("read-only", "workspace-write", "danger-full-access")


# --- integration with the sandbox manager -----------------------------------

@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != "win32", reason="Job Objects are Windows-only")
async def test_docker_manager_falls_back_to_the_job_backend(tmp_path):
    """With no container for the run, the manager must contain the command, not run bare."""
    from atlas.sandbox import DockerSandboxManager

    manager = DockerSandboxManager()
    manager._roots["run-1"] = str(tmp_path)
    result = await manager.call_tool(
        "run-1", "local_shell",
        {"command": "echo host-fallback", "cwd": str(tmp_path),
         "sandbox_permissions": "workspace-write"},
    )
    assert result["data"]["sandbox_backend"] == "win32job"
    assert result["sandbox_enforced"] is True
    assert "host-fallback" in result["content"][0]["text"]


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != "win32", reason="Job Objects are Windows-only")
async def test_read_only_is_refused_rather_than_faked(tmp_path):
    """A Job Object cannot enforce a filesystem ACL, so read-only must fail closed."""
    from atlas.sandbox import DockerSandboxManager

    manager = DockerSandboxManager()
    manager._roots["run-2"] = str(tmp_path)
    result = await manager.call_tool(
        "run-2", "local_shell",
        {"command": "echo should-not-run", "cwd": str(tmp_path),
         "sandbox_permissions": "read-only"},
    )
    assert result["is_error"] is True
    assert result["data"]["sandbox_enforced"] is False
    assert "should-not-run" not in result["content"][0]["text"]
