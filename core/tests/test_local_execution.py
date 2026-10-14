"""Native local execution acceptance tests."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from atlas.agent import AgentOrchestrator
from atlas.config import AtlasConfig
from atlas.tools.local_execution import LocalExecutionRuntime


def test_local_execution_defaults_to_full_access_without_workspace_root() -> None:
    config = AtlasConfig({})

    assert config.local_execution_permission_mode == "full_access"


@pytest.mark.asyncio
async def test_arbitrary_unicode_path_read_write_and_delete(tmp_path: Path) -> None:
    outside_workspace = tmp_path / "任意 工作目录"
    outside_workspace.mkdir()
    target = outside_workspace / "结果 文件.txt"
    runtime = LocalExecutionRuntime()

    written = await runtime.call_tool(
        "local_file",
        {
            "action": "write",
            "path": str(target),
            "content": "Atlas 本机执行",
        },
    )
    await runtime.call_tool(
        "local_file",
        {
            "action": "append",
            "path": str(target),
            "content": " 完成",
        },
    )
    read = await runtime.call_tool("local_file", {"action": "read", "path": str(target)})
    deleted = await runtime.call_tool("local_file", {"action": "delete", "path": str(target)})

    assert written["is_error"] is False
    assert read["data"]["content"] == "Atlas 本机执行 完成"
    assert deleted["is_error"] is False
    assert not target.exists()


@pytest.mark.asyncio
async def test_filesystem_copy_move_search_glob_and_stat(tmp_path: Path) -> None:
    runtime = LocalExecutionRuntime()
    root = tmp_path / "directory with spaces"
    source = root / "nested" / "note.txt"
    copy = root / "copy.txt"
    moved = root / "moved.txt"
    await runtime.call_tool(
        "local_file", {"action": "write", "path": str(source), "content": "needle here"}
    )
    copied = await runtime.call_tool(
        "local_file", {"action": "copy", "path": str(source), "destination": str(copy)}
    )
    matches = await runtime.call_tool(
        "local_file", {"action": "glob", "path": str(root), "pattern": "**/*.txt"}
    )
    found = await runtime.call_tool(
        "local_file", {"action": "search", "path": str(root), "query": "needle"}
    )
    moved_result = await runtime.call_tool(
        "local_file", {"action": "move", "path": str(copy), "destination": str(moved)}
    )
    stat = await runtime.call_tool("local_file", {"action": "stat", "path": str(moved)})
    missing = await runtime.call_tool(
        "local_file", {"action": "stat", "path": str(root / "missing")}
    )
    listed = await runtime.call_tool("local_file", {"action": "list", "path": str(root)})
    deleted = await runtime.call_tool(
        "local_file", {"action": "delete", "path": str(root), "recursive": True}
    )
    await runtime.shutdown()

    assert copied["is_error"] is False and moved_result["is_error"] is False
    assert len(matches["data"]["matches"]) == 2
    assert found["data"]["matches"][0]["text"] == "needle here"
    assert stat["data"]["exists"] is True and missing["data"]["exists"] is False
    assert {item["name"] for item in listed["data"]["entries"]} == {"moved.txt", "nested"}
    assert deleted["data"]["deleted"] is True and not root.exists()


@pytest.mark.asyncio
async def test_opt_in_deny_mode_blocks_local_mutations(tmp_path: Path) -> None:
    runtime = LocalExecutionRuntime()
    runtime.permission_mode = "deny"
    target = tmp_path / "not-written.txt"

    result = await runtime.call_tool(
        "local_file",
        {
            "action": "write",
            "path": str(target),
            "content": "denied",
        },
    )
    await runtime.shutdown()

    assert result["is_error"] is True
    assert not target.exists()


@pytest.mark.asyncio
async def test_shells_executable_cwd_environment_and_nonzero_exit(tmp_path: Path) -> None:
    runtime = LocalExecutionRuntime()
    py = await runtime.call_tool(
        "local_exec",
        {
            "executable": sys.executable,
            "args": ["-c", "import os; print(os.getcwd()); print(os.environ['ATLAS_TEST_VALUE'])"],
            "cwd": str(tmp_path),
            "env": {"ATLAS_TEST_VALUE": "passed"},
        },
    )
    ps = await runtime.call_tool(
        "local_shell",
        {
            "shell": "powershell",
            "command": "Write-Output 'powershell-ok'; Write-Output '中文路径可用'",
            "cwd": str(tmp_path),
        },
    )
    cmd = await runtime.call_tool(
        "local_shell",
        {
            "shell": "cmd",
            "command": "echo cmd-ok & echo 中文命令可用",
            "cwd": str(tmp_path),
        },
    )
    failed = await runtime.call_tool(
        "local_exec",
        {
            "executable": sys.executable,
            "args": ["-c", "import sys; print('bad', file=sys.stderr); sys.exit(7)"],
        },
    )

    assert str(tmp_path) in py["data"]["stdout"]
    assert "passed" in py["data"]["stdout"]
    assert ps["data"]["exit_code"] == 0 and "powershell-ok" in ps["data"]["stdout"]
    assert "中文路径可用" in ps["data"]["stdout"]
    assert cmd["data"]["exit_code"] == 0 and "cmd-ok" in cmd["data"]["stdout"]
    assert "中文命令可用" in cmd["data"]["stdout"]
    assert failed["is_error"] is False
    assert failed["data"]["exit_code"] == 7
    assert "bad" in failed["data"]["stderr"]
    await runtime.shutdown()


@pytest.mark.skipif(os.name != "nt", reason="Windows batch argv handling is Windows-specific")
@pytest.mark.asyncio
async def test_windows_batch_executable_preserves_argument_quoting(tmp_path: Path) -> None:
    runtime = LocalExecutionRuntime()
    batch = tmp_path / "command with spaces.cmd"
    batch.write_text("@echo off\r\necho [%~1]\r\n", encoding="utf-8")

    result = await runtime.call_tool(
        "local_exec",
        {
            "executable": str(batch),
            "args": ["value with spaces"],
            "cwd": str(tmp_path),
        },
    )
    await runtime.shutdown()

    assert result["data"]["exit_code"] == 0, result["data"]["stderr"]
    assert "[value with spaces]" in result["data"]["stdout"]


@pytest.mark.asyncio
async def test_process_stream_status_cancel_and_shutdown(tmp_path: Path) -> None:
    observed_streams: set[str] = set()
    output_seen = asyncio.Event()

    def observe(_execution_id: str, stream: str, _text: str) -> None:
        observed_streams.add(stream)
        if observed_streams == {"stdout", "stderr"}:
            output_seen.set()

    runtime = LocalExecutionRuntime(output_callback=observe)
    started = await runtime.call_tool(
        "local_process",
        {
            "action": "start",
            "executable": sys.executable,
            "args": [
                "-u",
                "-c",
                (
                    "import sys,time; print('ready', flush=True); "
                    "print('problem', file=sys.stderr, flush=True); time.sleep(60)"
                ),
            ],
            "cwd": str(tmp_path),
        },
    )
    execution_id = started["data"]["execution_id"]

    await asyncio.wait_for(output_seen.wait(), timeout=5)
    logs = await runtime.call_tool(
        "local_process",
        {
            "action": "read",
            "execution_id": execution_id,
            "stream": "stdout",
        },
    )
    error_logs = await runtime.call_tool(
        "local_process",
        {
            "action": "read",
            "execution_id": execution_id,
            "stream": "stderr",
        },
    )
    status = await runtime.call_tool(
        "local_process",
        {
            "action": "status",
            "execution_id": execution_id,
        },
    )
    cancelled = await runtime.call_tool(
        "local_process",
        {
            "action": "cancel",
            "execution_id": execution_id,
        },
    )
    await runtime.shutdown()

    assert "ready" in logs["data"]["text"]
    assert "problem" in error_logs["data"]["text"]
    assert status["data"]["state"] == "running"
    assert cancelled["data"]["state"] == "cancelled"


@pytest.mark.asyncio
async def test_process_stdin_write_submit_and_close(tmp_path: Path) -> None:
    runtime = LocalExecutionRuntime()
    started = await runtime.call_tool(
        "local_process",
        {
            "action": "start",
            "executable": sys.executable,
            "args": ["-u", "-c", "import sys; print('ready', flush=True); print('got:' + sys.stdin.readline().strip(), flush=True); print('eof:' + str(sys.stdin.read() == ''), flush=True)"],
            "cwd": str(tmp_path),
            "detached": True,
            "keep_stdin": True,
        },
    )
    execution_id = started["data"]["execution_id"]
    await runtime.call_tool(
        "local_process", {"action": "write_stdin", "execution_id": execution_id, "data": "answer"},
    )
    submitted = await runtime.call_tool(
        "local_process", {"action": "submit_stdin", "execution_id": execution_id},
    )
    closed = await runtime.call_tool(
        "local_process", {"action": "close_stdin", "execution_id": execution_id},
    )
    waited = await runtime.call_tool(
        "local_process", {"action": "wait", "execution_id": execution_id, "timeout": 5},
    )
    await runtime.shutdown()

    assert submitted["data"]["bytes_written"] == 2
    assert waited["data"]["exit_code"] == 0
    assert "got:answer" in waited["data"]["stdout"]
    assert closed["data"]["closed"] is True
    assert "eof:True" in waited["data"]["stdout"]


@pytest.mark.asyncio
async def test_process_pty_accepts_interactive_input(tmp_path: Path) -> None:
    if sys.platform != "win32":
        pytest.skip("pywinpty PTY integration is Windows-only")
    pytest.importorskip("winpty")
    runtime = LocalExecutionRuntime()
    started = await runtime.call_tool(
        "local_process",
        {
            "action": "start",
            "executable": sys.executable,
            "args": ["-u", "-c", "import sys; print('ready', flush=True); print('got:' + input(), flush=True)"],
            "cwd": str(tmp_path),
            "detached": True,
            "keep_stdin": True,
            "pty": True,
        },
    )
    execution_id = started["data"]["execution_id"]
    await runtime.call_tool(
        "local_process", {"action": "submit_stdin", "execution_id": execution_id, "data": "pty-answer"},
    )
    waited = await runtime.call_tool(
        "local_process", {"action": "wait", "execution_id": execution_id, "timeout": 10},
    )
    await runtime.shutdown()
    assert waited["data"]["exit_code"] == 0
    assert "got:pty-answer" in waited["data"]["stdout"]






@pytest.mark.asyncio
async def test_cancelling_atlas_process_terminates_child_tree(tmp_path: Path) -> None:
    runtime = LocalExecutionRuntime()
    marker = tmp_path / "child-survived.txt"
    child_code = f"import time; time.sleep(3); open({str(marker)!r}, 'w').write('alive')"
    parent_code = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
        "print('parent-ready', flush=True); time.sleep(60)"
    )
    started = await runtime.call_tool(
        "local_process",
        {
            "action": "start",
            "executable": sys.executable,
            "args": ["-u", "-c", parent_code],
            "cwd": str(tmp_path),
            "detached": False,
        },
        run_id="tree-run",
    )
    execution_id = started["data"]["execution_id"]
    for _ in range(50):
        output = await runtime.call_tool(
            "local_process",
            {
                "action": "read",
                "execution_id": execution_id,
                "stream": "stdout",
                "offset": 0,
            },
        )
        if "parent-ready" in output["data"]["text"]:
            break
        await asyncio.sleep(0.05)

    await runtime.cancel_run("tree-run")
    await asyncio.sleep(3.2)
    await runtime.shutdown()

    assert not marker.exists()


@pytest.mark.asyncio
async def test_git_operations_work_in_an_arbitrary_repository(tmp_path: Path) -> None:
    repo = tmp_path / "Git 项目 with spaces"
    remote = tmp_path / "local-remote.git"
    clone = tmp_path / "clone from local remote"
    repo.mkdir()
    runtime = LocalExecutionRuntime()
    await runtime.call_tool(
        "local_exec",
        {"executable": "git", "args": ["init", "--bare", str(remote)], "cwd": str(tmp_path)},
    )
    init = await runtime.call_tool(
        "local_exec",
        {"executable": shutil.which("git") or "git", "args": ["init", "--quiet"], "cwd": str(repo)},
    )
    await runtime.call_tool(
        "local_exec",
        {
            "executable": "git",
            "args": ["config", "user.email", "atlas@example.test"],
            "cwd": str(repo),
        },
    )
    await runtime.call_tool(
        "local_exec",
        {"executable": "git", "args": ["config", "user.name", "Atlas Test"], "cwd": str(repo)},
    )
    target = repo / "source file.txt"
    target.write_text("local git workflow", encoding="utf-8")
    status = await runtime.call_tool("local_git", {"action": "status", "repo": str(repo)})
    added = await runtime.call_tool(
        "local_git", {"action": "add", "repo": str(repo), "paths": ["."]}
    )
    diff = await runtime.call_tool(
        "local_git", {"action": "diff", "repo": str(repo), "args": ["--cached"]}
    )
    committed = await runtime.call_tool(
        "local_git", {"action": "commit", "repo": str(repo), "message": "test: local execution"}
    )
    history = await runtime.call_tool("local_git", {"action": "log", "repo": str(repo)})
    branch = await runtime.call_tool("local_git", {"action": "branch", "repo": str(repo)})
    await runtime.call_tool(
        "local_exec", {"executable": "git", "args": ["branch", "-M", "main"], "cwd": str(repo)}
    )
    await runtime.call_tool(
        "local_exec",
        {"executable": "git", "args": ["remote", "add", "origin", str(remote)], "cwd": str(repo)},
    )
    pushed = await runtime.call_tool(
        "local_git", {"action": "push", "repo": str(repo), "args": ["-u", "origin", "main"]}
    )
    await runtime.call_tool(
        "local_exec",
        {
            "executable": "git",
            "args": ["--git-dir", str(remote), "symbolic-ref", "HEAD", "refs/heads/main"],
            "cwd": str(tmp_path),
        },
    )
    cloned = await runtime.call_tool(
        "local_exec",
        {"executable": "git", "args": ["clone", str(remote), str(clone)], "cwd": str(tmp_path)},
    )
    await runtime.call_tool(
        "local_exec",
        {
            "executable": "git",
            "args": ["config", "user.email", "atlas@example.test"],
            "cwd": str(clone),
        },
    )
    await runtime.call_tool(
        "local_exec",
        {"executable": "git", "args": ["config", "user.name", "Atlas Test"], "cwd": str(clone)},
    )
    (clone / "remote change.txt").write_text("from clone", encoding="utf-8")
    clone_added = await runtime.call_tool(
        "local_exec", {"executable": "git", "args": ["add", "."], "cwd": str(clone)}
    )
    clone_commit = await runtime.call_tool(
        "local_exec",
        {"executable": "git", "args": ["commit", "-m", "remote change"], "cwd": str(clone)},
    )
    clone_push = await runtime.call_tool("local_git", {"action": "push", "repo": str(clone)})
    fetched = await runtime.call_tool("local_git", {"action": "fetch", "repo": str(repo)})
    pulled = await runtime.call_tool("local_git", {"action": "pull", "repo": str(repo)})
    final_status = await runtime.call_tool("local_git", {"action": "status", "repo": str(repo)})
    await runtime.shutdown()

    assert init["data"]["exit_code"] == 0
    assert "source file.txt" in status["data"]["stdout"]
    assert added["data"]["exit_code"] == 0
    assert "local git workflow" in diff["data"]["stdout"]
    assert committed["data"]["exit_code"] == 0
    assert "test: local execution" in history["data"]["stdout"]
    assert branch["data"]["stdout"].strip() in {"main", "master"}
    assert pushed["data"]["exit_code"] == 0 and cloned["data"]["exit_code"] == 0
    assert clone_added["data"]["exit_code"] == 0 and clone_commit["data"]["exit_code"] == 0
    assert clone_push["data"]["exit_code"] == 0, clone_push
    assert fetched["data"]["exit_code"] == 0 and pulled["data"]["exit_code"] == 0
    assert "## main" in final_status["data"]["stdout"]
    assert (repo / "remote change.txt").read_text(encoding="utf-8") == "from clone"
    assert diff["is_error"] is False


@pytest.mark.asyncio
async def test_detached_process_survives_run_cleanup_but_stops_on_shutdown(tmp_path: Path) -> None:
    runtime = LocalExecutionRuntime()
    marker = tmp_path / "child-finished.txt"
    code = f"import time; time.sleep(2); open({str(marker)!r}, 'w').write('finished')"
    started = await runtime.call_tool(
        "local_process",
        {
            "action": "start",
            "executable": sys.executable,
            "args": ["-c", code],
            "cwd": str(tmp_path),
            "detached": True,
        },
        run_id="detached-run",
    )
    execution_id = started["data"]["execution_id"]

    await runtime.cancel_run("detached-run")
    status = await runtime.call_tool(
        "local_process", {"action": "status", "execution_id": execution_id}
    )
    await runtime.shutdown()
    await asyncio.sleep(2.1)

    assert status["data"]["state"] == "running"
    assert not marker.exists()


@pytest.mark.asyncio
async def test_process_handoff_detaches_from_child_run(tmp_path: Path) -> None:
    runtime = LocalExecutionRuntime()
    started = await runtime.call_tool(
        "local_process",
        {
            "action": "start",
            "executable": sys.executable,
            "args": ["-c", "import time; time.sleep(30)"],
            "cwd": str(tmp_path),
        },
        run_id="child-run",
    )
    execution_id = started["data"]["execution_id"]
    handed = await runtime.call_tool(
        "local_process",
        {"action": "handoff", "execution_id": execution_id, "data": "Parent should poll this process."},
        run_id="child-run",
    )
    await runtime.cancel_run("child-run")
    listed = await runtime.call_tool("local_process", {"action": "list"})
    await runtime.shutdown()

    assert handed["data"]["detached"] is True
    assert handed["data"]["handoff_note"] == "Parent should poll this process."
    assert any(item["execution_id"] == execution_id for item in listed["data"]["processes"])


@pytest.mark.asyncio
async def test_file_reads_show_numbered_lines_and_batch_paths(tmp_path):
    """FEEL-1: reads are numbered text, not a Python dict repr; paths reads many files."""
    first = tmp_path / "a.py"
    first.write_text('x = "q"\r\ny = 2\n', encoding="utf-8")
    second = tmp_path / "b.txt"
    second.write_text("only line", encoding="utf-8")
    runtime = LocalExecutionRuntime()
    try:
        single = await runtime.call_tool("local_file", {"action": "read", "path": str(first)})
        text = single["content"][0]["text"]
        assert '1\tx = "q"\n2\ty = 2' in text and "\r" not in text
        assert "'content':" not in text  # no Python dict repr
        batch = await runtime.call_tool("local_file", {
            "action": "read", "paths": [str(first), str(second), str(tmp_path / "missing")],
        })
        assert not batch["is_error"]
        assert [("error" in item) for item in batch["data"]["files"]] == [False, False, True]
        assert "1\tonly line" in batch["content"][0]["text"]
    finally:
        await runtime.shutdown()


@pytest.mark.parametrize(("command", "refused"), [
    ('python -c "import os\nprint(os.getcwd())"', True),
    ("python -X utf8 -c 'a = 1\nprint(a)'", True),
    ('python -c "print(1)"', False),
    ("python -m pytest -c setup.cfg\necho ok", False),
    ("python - <<'EOF'\nprint(1)\nEOF", False),
])
def test_inline_multiline_code_is_refused_before_running(command, refused):
    try:
        LocalExecutionRuntime._validate_execution_args("local_shell", {"shell": "bash", "command": command})
    except ValueError as exc:
        assert refused and "Inline multi-line code is refused" in str(exc)
    else:
        assert not refused
