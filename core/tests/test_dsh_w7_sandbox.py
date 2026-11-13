"""W7 evidence for per-call Docker sandbox modes and enforcement reporting."""

from types import SimpleNamespace

import pytest


@pytest.mark.unit
@pytest.mark.asyncio
async def test_escalation_approval_is_one_call_with_justification():
    from atlas.engine.kernel.loop import authorize_local_sandbox_request

    approvals = []

    async def approve(call_id, tool_name, arguments):
        approvals.append((call_id, tool_name, arguments))
        return "allow_once"

    result = await authorize_local_sandbox_request(
        {"sandbox_permissions": "read-only", "justification": "Inspect generated output"},
        approve,
        tool_name="local_shell",
        tool_call_id="tool-w7-1",
        sandbox_executor_available=True,
    )

    assert result["approved"] is True
    assert result["sandbox_enforced"] is True
    assert result["request"] == {
        "sandbox_permissions": "read-only",
        "justification": "Inspect generated output",
    }
    assert len(approvals) == 1
    assert approvals[0][2]["justification"] == "Inspect generated output"
    assert approvals[0][2]["_approval_no_always"] is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_per_call_read_only_uses_read_only_workspace_mount_and_reports_mode(
    tmp_path, monkeypatch,
):
    import atlas.sandbox as sandbox_module
    from atlas.sandbox import DockerSandboxManager

    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        if command[1] == "run" and "-d" in command:
            return SimpleNamespace(returncode=0, stdout="container-1\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="read ok", stderr="")

    monkeypatch.setattr(sandbox_module.shutil, "which", lambda _name: "docker-mock")
    monkeypatch.setattr(sandbox_module.subprocess, "run", fake_run)
    manager = DockerSandboxManager()
    await manager.start("run-1", str(tmp_path), {"type": "docker"})

    result = await manager.call_tool("run-1", "local_shell", {
        "command": "cat input.txt", "cwd": str(tmp_path),
        "sandbox_permissions": "read-only",
    })

    invocation = calls[1]
    assert invocation[1:5] == ["run", "--rm", "--network", "none"]
    mount = invocation[invocation.index("--mount") + 1]
    assert mount.startswith("type=bind,source=")
    assert mount.endswith(",target=/workspace,readonly")
    assert "container-1" not in invocation
    assert result["data"]["sandbox_permissions"] == "read-only"
    assert result["data"]["sandbox_enforced"] is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_per_call_workspace_write_uses_existing_writable_container_and_reports_mode(
    tmp_path, monkeypatch,
):
    import atlas.sandbox as sandbox_module
    from atlas.sandbox import DockerSandboxManager

    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        if command[1] == "run" and "-d" in command:
            return SimpleNamespace(returncode=0, stdout="container-1\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="write ok", stderr="")

    monkeypatch.setattr(sandbox_module.shutil, "which", lambda _name: "docker-mock")
    monkeypatch.setattr(sandbox_module.subprocess, "run", fake_run)
    manager = DockerSandboxManager()
    await manager.start("run-1", str(tmp_path), {"type": "docker"})

    result = await manager.call_tool("run-1", "local_shell", {
        "command": "touch output.txt", "cwd": str(tmp_path),
        "sandbox_permissions": "workspace-write",
    })

    invocation = calls[1]
    assert invocation[1:5] == ["exec", "-w", "/workspace", "container-1"]
    assert "--mount" not in invocation
    assert result["data"]["sandbox_permissions"] == "workspace-write"
    assert result["data"]["sandbox_enforced"] is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_danger_full_access_is_rejected_without_running_a_command(tmp_path, monkeypatch):
    import atlas.sandbox as sandbox_module
    from atlas.sandbox import DockerSandboxManager

    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="container-1\n", stderr="")

    monkeypatch.setattr(sandbox_module.shutil, "which", lambda _name: "docker-mock")
    monkeypatch.setattr(sandbox_module.subprocess, "run", fake_run)
    manager = DockerSandboxManager()
    await manager.start("run-1", str(tmp_path), {"type": "docker"})

    result = await manager.call_tool("run-1", "local_shell", {
        "command": "touch outside.txt", "cwd": str(tmp_path),
        "sandbox_permissions": "danger-full-access",
    })

    assert len(calls) == 1
    assert result["is_error"] is True
    assert result["data"]["sandbox_permissions"] == "danger-full-access"
    assert result["data"]["sandbox_enforced"] is False
