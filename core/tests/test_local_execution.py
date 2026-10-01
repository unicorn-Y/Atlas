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
async def test_agent_completes_multi_step_file_edit_and_execution(
    tmp_path: Path, legacy_agent_engine,
) -> None:
    target = tmp_path / "跨目录 项目" / "value.txt"

    class Memory:
        async def retrieve_approved_goal_knowledge(self, *_args, **_kwargs):
            return []

        async def extract_memories(self, *_args, **_kwargs):
            return []

        async def get_conversation_messages(self, *_args, **_kwargs):
            return []

        async def get_agent_context_with_trace(self, *_args, **_kwargs):
            return {"memories": [], "knowledge_trace": {"query_terms": [], "decisions": []}}

        async def apply_knowledge_consolidated_insights(self, *_args, **_kwargs):
            return []

        async def retrieve_agent_reflections(self, *_args, **_kwargs):
            return []

        async def retrieve_approved_goal_experiences(self, *_args, **_kwargs):
            return []

        async def save_message(self, **_kwargs):
            return "assistant-message"

        async def extract_conversation_candidates(self, *_args, **_kwargs):
            return []

    manager = MagicMock()
    manager.current_model = "test-model"
    manager.current_litellm_model = "openai/test-model"
    local = LocalExecutionRuntime()
    agent = AgentOrchestrator(manager, Memory(), local_execution=local)
    calls = [
        ("local_file", {"action": "write", "path": str(target), "content": "step-one"}),
        (
            "local_exec",
            {
                "executable": sys.executable,
                "args": [
                    "-c",
                    f"from pathlib import Path; print(Path({str(target)!r}).read_text())",
                ],
                "cwd": str(tmp_path),
            },
        ),
    ]

    async def fake_acompletion(*, messages, **_kwargs):
        index = sum(item["role"] == "tool" for item in messages)

        async def stream():
            if index < len(calls):
                name, arguments = calls[index]
                fragment = SimpleNamespace(
                    index=0,
                    id=f"step-{index}",
                    function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
                )
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(content=None, tool_calls=[fragment]),
                            finish_reason="tool_calls",
                        )
                    ]
                )
            else:
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(content="Verified step-one", tool_calls=None),
                            finish_reason="stop",
                        )
                    ]
                )

        return stream()

    with (
        patch("atlas.agent.requires_plan", return_value=False),
        patch("atlas.agent.acompletion", side_effect=fake_acompletion),
    ):
        events = [
            event
            async for event in agent.run("edit then run", "conversation", source_run_id="test-run")
        ]
    await local.shutdown()

    assert events[-1]["type"] == "done", events
    assert target.read_text(encoding="utf-8") == "step-one"
    assert [event["name"] for event in events if event["type"] == "tool_call"] == [
        "local_file",
        "local_exec",
    ]
    assert any(
        event["type"] == "tool_result" and "step-one" in json.dumps(event) for event in events
    )
    assert not any(event["type"] == "approval_required" for event in events)
    assert events[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_agent_repairs_external_git_project_and_commits(
    tmp_path: Path, legacy_agent_engine,
) -> None:
    project = tmp_path / "MemoryOS 任意路径 Project"
    project.mkdir()
    source = project / "answer.py"
    test_script = project / "test_answer.py"
    source.write_text("def answer():\n    return 41\n", encoding="utf-8")
    test_script.write_text(
        "from answer import answer\nassert answer() == 42\nprint('PASS')\n",
        encoding="utf-8",
    )
    subprocess_run = shutil.which("git") or "git"
    for command in (
        ["init", "--quiet"],
        ["config", "user.email", "atlas@example.test"],
        ["config", "user.name", "Atlas Test"],
        ["add", "."],
        ["commit", "--quiet", "-m", "baseline"],
    ):
        result = await asyncio.create_subprocess_exec(
            subprocess_run,
            *command,
            cwd=str(project),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await result.communicate()
        assert result.returncode == 0

    class Memory:
        async def retrieve_approved_goal_knowledge(self, *_args, **_kwargs):
            return []

        async def extract_memories(self, *_args, **_kwargs):
            return []

        async def get_conversation_messages(self, *_args, **_kwargs):
            return []

        async def get_agent_context_with_trace(self, *_args, **_kwargs):
            return {"memories": [], "knowledge_trace": {"query_terms": [], "decisions": []}}

        async def apply_knowledge_consolidated_insights(self, *_args, **_kwargs):
            return []

        async def retrieve_agent_reflections(self, *_args, **_kwargs):
            return []

        async def retrieve_approved_goal_experiences(self, *_args, **_kwargs):
            return []

        async def save_message(self, **_kwargs):
            return "assistant-message"

        async def extract_conversation_candidates(self, *_args, **_kwargs):
            return []

    manager = MagicMock()
    manager.current_model = "test-model"
    manager.current_litellm_model = "openai/test-model"
    runtime = LocalExecutionRuntime()
    agent = AgentOrchestrator(manager, Memory(), local_execution=runtime)
    steps = [
        ("local_file", {"action": "list", "path": str(project)}),
        ("local_file", {"action": "read", "path": str(source)}),
        ("local_file", {"action": "read", "path": str(test_script)}),
        (
            "local_exec",
            {"executable": sys.executable, "args": ["-u", str(test_script)], "cwd": str(project)},
        ),
        (
            "local_file",
            {"action": "write", "path": str(source), "content": "def answer():\n    return 42\n"},
        ),
        (
            "local_exec",
            {"executable": sys.executable, "args": ["-u", str(test_script)], "cwd": str(project)},
        ),
        ("local_git", {"action": "diff", "repo": str(project)}),
        ("local_git", {"action": "add", "repo": str(project), "paths": ["answer.py"]}),
        (
            "local_git",
            {"action": "commit", "repo": str(project), "message": "fix: return expected answer"},
        ),
        ("local_git", {"action": "status", "repo": str(project)}),
    ]

    async def fake_acompletion(*, messages, **_kwargs):
        index = sum(item["role"] == "tool" for item in messages)

        async def stream():
            if index < len(steps):
                name, arguments = steps[index]
                call = SimpleNamespace(
                    index=0,
                    id=f"workflow-{index}",
                    function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
                )
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(content=None, tool_calls=[call]),
                            finish_reason="tool_calls",
                        )
                    ]
                )
            else:
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(content="Repaired, tested, and committed."),
                            finish_reason="stop",
                        )
                    ]
                )

        return stream()

    with (
        patch("atlas.agent.requires_plan", return_value=False),
        patch("atlas.agent.acompletion", side_effect=fake_acompletion),
    ):
        events = [
            event
            async for event in agent.run(
                "Run the failing test, fix the project, and commit the change.",
                "external-project",
                source_run_id="external-project-run",
            )
        ]
    await runtime.shutdown()

    calls = [event for event in events if event["type"] == "tool_call"]
    results = [event for event in events if event["type"] == "tool_result"]
    assert len(calls) == len(steps)
    assert "return 42" in source.read_text(encoding="utf-8")
    assert results[3]["data"]["exit_code"] == 1
    assert "AssertionError" in json.dumps(results[3])
    assert results[5]["data"]["exit_code"] == 0
    assert "return 42" in json.dumps(results[6])
    assert results[8]["data"]["exit_code"] == 0
    final_status = json.dumps(results[9])
    assert "## " in final_status and "answer.py" not in final_status
    assert not any(event["type"] == "approval_required" for event in events)
    assert events[-1]["type"] == "done"


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
async def test_agent_run_cancel_stops_its_foreground_process(
    tmp_path: Path, legacy_agent_engine,
) -> None:
    class Memory:
        async def retrieve_approved_goal_knowledge(self, *_args, **_kwargs):
            return []

        async def extract_memories(self, *_args, **_kwargs):
            return []

        async def get_conversation_messages(self, *_args, **_kwargs):
            return []

        async def get_agent_context_with_trace(self, *_args, **_kwargs):
            return {"memories": [], "knowledge_trace": {"query_terms": [], "decisions": []}}

        async def apply_knowledge_consolidated_insights(self, *_args, **_kwargs):
            return []

        async def retrieve_agent_reflections(self, *_args, **_kwargs):
            return []

        async def retrieve_approved_goal_experiences(self, *_args, **_kwargs):
            return []

        async def save_message(self, **_kwargs):
            return "assistant-message"

        async def extract_conversation_candidates(self, *_args, **_kwargs):
            return []

    manager = MagicMock()
    manager.current_model = "test-model"
    manager.current_litellm_model = "openai/test-model"
    runtime = LocalExecutionRuntime()
    agent = AgentOrchestrator(manager, Memory(), local_execution=runtime)
    cancel_event = asyncio.Event()

    async def fake_acompletion(*, messages, **_kwargs):
        async def stream():
            if not any(item["role"] == "tool" for item in messages):
                call = SimpleNamespace(
                    index=0,
                    id="long-process",
                    function=SimpleNamespace(
                        name="local_process",
                        arguments=json.dumps(
                            {
                                "action": "start",
                                "executable": sys.executable,
                                "args": [
                                    "-u",
                                    "-c",
                                    "import time; print('ready', flush=True); time.sleep(60)",
                                ],
                                "cwd": str(tmp_path),
                                "detached": False,
                            }
                        ),
                    ),
                )
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(content=None, tool_calls=[call]),
                            finish_reason="tool_calls",
                        )
                    ]
                )
            else:
                await asyncio.sleep(60)

        return stream()

    with (
        patch("atlas.agent.requires_plan", return_value=False),
        patch("atlas.agent.acompletion", side_effect=fake_acompletion),
    ):
        events = agent.run(
            "start a long task",
            "cancel-conversation",
            cancel_event=cancel_event,
            source_run_id="cancel-run",
        )
        while True:
            event = await asyncio.wait_for(anext(events), timeout=10)
            if event["type"] == "tool_output":
                cancel_event.set()
                break
        remainder = [event async for event in events]
    states = [process.state for process in runtime._processes.values()]
    await runtime.shutdown()

    assert any(event["type"] == "cancelled" for event in remainder)
    assert "running" not in states
