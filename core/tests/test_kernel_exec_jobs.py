import asyncio
from types import SimpleNamespace

import pytest

from atlas.engine.kernel.exec import (
    JOB_OUTPUT_RING_BYTES,
    MAX_BACKGROUND_JOBS_PER_OWNER,
    SETTLED_JOB_OUTPUT_BYTES,
    ExecManager,
)
from atlas.engine.kernel import workflow_tool
from atlas.engine.kernel.loop import AtlasKernel
from atlas.engine.kernel.tools import kernel_tool_schemas
from atlas.tools.local_execution import LOCAL_TOOLS
from atlas.workflow.types import WorkflowGraph


pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_exec_manager_registers_lists_reads_and_kills_owner_jobs(tmp_path):
    killed = []

    async def dispatch(_name, _arguments):
        return {"is_error": True, "error": "not expected"}

    async def kill():
        killed.append(True)
        return {"state": "cancelled"}

    manager = ExecManager(dispatch, output_dir=tmp_path, run_id="owner-a")
    manager.register_background_job("subagent-1", label="review worker", kill=kill)
    manager.append_job_output("subagent-1", b"worker output\n")

    assert manager.job_list()[0]["job_id"] == "subagent-1"
    output = await manager.job_output("subagent-1")
    assert output["output"] == "worker output\n"
    assert output["state"] == "running"
    assert (await manager.job_kill("subagent-1"))["state"] == "cancelled"
    assert killed == [True]


@pytest.mark.asyncio
async def test_exec_manager_fences_job_access_to_owner(tmp_path):
    async def dispatch(_name, _arguments):
        return {"is_error": True, "error": "not expected"}

    manager = ExecManager(dispatch, output_dir=tmp_path, run_id="owner-a")
    manager.register_background_job("subagent-1", label="private worker")

    assert manager.job_list(owner_id="owner-b")["error"] == "job_owner_mismatch"
    assert (await manager.job_output("subagent-1", owner_id="owner-b"))["error"] == "job_owner_mismatch"
    assert (await manager.job_output("missing"))["error"] == "unknown_job"


@pytest.mark.asyncio
async def test_exec_manager_caps_background_jobs_per_owner(tmp_path):
    async def dispatch(_name, _arguments):
        return {"is_error": True, "error": "not expected"}

    manager = ExecManager(dispatch, output_dir=tmp_path, run_id="owner-a")
    for index in range(MAX_BACKGROUND_JOBS_PER_OWNER):
        manager.register_background_job(f"job-{index}")

    with pytest.raises(ValueError, match="maximum of 10"):
        manager.register_background_job("job-over-limit")


@pytest.mark.asyncio
async def test_exec_manager_ring_and_settled_output_caps(tmp_path):
    async def dispatch(_name, _arguments):
        return {"is_error": True, "error": "not expected"}

    manager = ExecManager(dispatch, output_dir=tmp_path, run_id="owner-a")
    manager.register_background_job("job-1")
    manager.append_job_output("job-1", b"x" * (JOB_OUTPUT_RING_BYTES + 7))
    running = await manager.job_output("job-1")
    assert len(running["output"].encode("utf-8")) == JOB_OUTPUT_RING_BYTES
    assert running["omitted_bytes"] == 7

    manager.settle_background_job("job-1", state="completed")
    settled = await manager.job_output("job-1")
    assert len(settled["output"].encode("utf-8")) == SETTLED_JOB_OUTPUT_BYTES
    assert settled["state"] == "completed"


@pytest.mark.unit
def test_background_job_tools_are_model_visible():
    schemas = {tool["function"]["name"]: tool["function"] for tool in LOCAL_TOOLS}
    assert set(("job_list", "job_output", "job_kill")) <= schemas.keys()
    assert schemas["job_output"]["parameters"]["required"] == ["job_id"]
    assert schemas["job_kill"]["parameters"]["required"] == ["job_id"]

    kernel_schemas = {
        tool["function"]["name"]: tool["function"]
        for tool in kernel_tool_schemas(include_workflow=True)
    }
    assert set(("job_list", "job_output", "job_kill")) <= kernel_schemas.keys()
    assert kernel_schemas["job_output"]["parameters"]["required"] == ["job_id"]
    assert kernel_schemas["job_kill"]["parameters"]["required"] == ["job_id"]


@pytest.mark.asyncio
async def test_background_job_tool_names_dispatch_to_registry(tmp_path):
    async def dispatch(_name, _arguments):
        return {"is_error": True, "error": "not expected"}

    manager = ExecManager(dispatch, output_dir=tmp_path, run_id="owner-a")
    manager.register_background_job("subagent-1")
    manager.append_job_output("subagent-1", "result")

    listed = await manager.execute("job_list", {})
    output = await manager.execute("job_output", {"job_id": "subagent-1"})
    assert listed["data"]["jobs"][0]["job_id"] == "subagent-1"
    assert output["output"] == "result"


@pytest.mark.asyncio
async def test_kernel_dispatches_job_tools_directly_to_run_registry(tmp_path):
    async def dispatch(_name, _arguments):
        return {"is_error": True, "error": "not expected"}

    manager = ExecManager(dispatch, output_dir=tmp_path, run_id="owner-a")
    manager.register_background_job("job-1", kill=lambda: {"state": "cancelled"})
    manager.append_job_output("job-1", "kernel output")
    kernel = object.__new__(AtlasKernel)

    output = await kernel._dispatch(
        agent=None, runtime=None, call_id="call-output", name="job_output",
        arguments={"job_id": "job-1"}, event_queue=asyncio.Queue(),
        exec_manager=manager,
    )
    listed = await kernel._dispatch(
        agent=None, runtime=None, call_id="call-list", name="job_list",
        arguments={}, event_queue=asyncio.Queue(), exec_manager=manager,
    )
    killed = await kernel._dispatch(
        agent=None, runtime=None, call_id="call-kill", name="job_kill",
        arguments={"job_id": "job-1"}, event_queue=asyncio.Queue(),
        exec_manager=manager,
    )
    denied = await kernel._dispatch(
        agent=None, runtime=SimpleNamespace(tool_allow=None, tool_deny=("job_kill",)),
        call_id="call-denied", name="job_kill", arguments={"job_id": "job-1"},
        event_queue=asyncio.Queue(), exec_manager=manager,
    )
    assert output["output"] == "kernel output"
    assert listed["data"]["jobs"][0]["job_id"] == "job-1"
    assert killed["state"] == "cancelled"
    assert denied["is_error"] is True


@pytest.mark.asyncio
async def test_local_process_compatibility_routes_subagent_output_and_stop(tmp_path):
    cancelled = []

    async def dispatch(_name, _arguments):
        return {"is_error": True, "error": "should use the registry"}

    manager = ExecManager(dispatch, output_dir=tmp_path, run_id="owner-a")
    manager.register_background_job(
        "subagent-1", kill=lambda: (cancelled.append(True) or {"state": "cancelled"}),
    )
    manager.append_job_output("subagent-1", "child output")

    output = await manager.execute("local_process", {
        "action": "read", "execution_id": "subagent-1",
    })
    stopped = await manager.execute("local_process", {
        "action": "cancel", "execution_id": "subagent-1",
    })
    assert output["data"]["text"] == "child output"
    assert stopped["state"] == "cancelled"
    assert cancelled == [True]


@pytest.mark.asyncio
async def test_registered_subagent_refresh_is_bounded_and_settles(tmp_path):
    async def dispatch(_name, _arguments):
        return {"is_error": True, "error": "not expected"}

    manager = ExecManager(dispatch, output_dir=tmp_path, run_id="owner-a")
    snapshot = {"status": "running", "progress": "started"}
    manager.register_background_job("subagent-1", refresh=lambda: snapshot)

    first = await manager.job_output("subagent-1")
    assert first["output"] == "started"
    snapshot.update(status="completed", result="finished")
    listed = manager.job_list()
    job = next(item for item in listed if item["job_id"] == "subagent-1")
    final = await manager.job_output("subagent-1")
    assert job["state"] == "completed"
    assert final["output"].endswith("finished")


@pytest.mark.asyncio
async def test_detached_shell_uses_same_job_output_ring(tmp_path):
    state = {"status": "running"}
    stdout = b"detached shell output"

    async def dispatch(_name, arguments):
        action = arguments["action"]
        if action == "start":
            return {"data": {"execution_id": "shell-1", "shell": "direct argv"}}
        if action == "status":
            return {"data": {
                "execution_id": "shell-1", "state": state["status"],
                "exit_code": 0 if state["status"] == "completed" else None,
            }}
        if action == "read":
            stream = arguments["stream"]
            content = stdout if stream == "stdout" and arguments["offset"] == 0 else b""
            return {"data": {
                "text": content.decode(), "next_offset": arguments["offset"] + len(content),
                "complete": True,
            }}
        if action == "cancel":
            state["status"] = "cancelled"
            return {"data": {"execution_id": "shell-1", "state": "cancelled"}}
        return {"is_error": True, "error": f"unexpected action {action}"}

    manager = ExecManager(dispatch, output_dir=tmp_path, run_id="owner-a")
    started = await manager.start({
        "action": "start", "executable": "python", "args": ["-V"],
        "cwd": str(tmp_path), "detached": True,
    })
    assert started["data"]["execution_id"] == "shell-1"
    first = await manager.job_output("shell-1")
    assert first["output"] == stdout.decode()
    state["status"] = "completed"
    settled = await manager.job_output("shell-1")
    assert settled["state"] == "completed"
    assert settled["output"] == stdout.decode()


@pytest.mark.asyncio
async def test_workflow_runs_in_shared_job_registry_and_can_be_cancelled(tmp_path, monkeypatch):
    entered = asyncio.Event()

    class Config:
        @staticmethod
        def get(_key, default=None):
            return default

    async def plan_workflow(*_args, **_kwargs):
        return WorkflowGraph("test workflow", [], str(tmp_path))

    async def run_workflow(_graph, _runner, *, on_event, **_kwargs):
        await on_event({"type": "workflow_started", "message": "started"})
        entered.set()
        await asyncio.Future()

    async def dispatch(_name, _arguments):
        return {"is_error": True, "error": "not expected"}

    monkeypatch.setattr("atlas.config.get_config", lambda: Config())
    monkeypatch.setattr(workflow_tool, "plan_workflow", plan_workflow)
    monkeypatch.setattr(workflow_tool, "run_workflow", run_workflow)
    monkeypatch.setattr(workflow_tool, "_workflow_event", lambda *_args: asyncio.sleep(0))

    manager = ExecManager(dispatch, output_dir=tmp_path, run_id="owner-a")
    runtime = SimpleNamespace(
        tool_allow=None, tool_deny=(), read_only=False, mode="act",
        workspace=str(tmp_path), model="test-model", cancel_event=None,
        pause_event=None, exec_manager=manager, conversation_id="",
    )
    agent = SimpleNamespace(
        _model_mgr=SimpleNamespace(current_model="test-model"),
        _run_atlas_subtask=lambda *_args, **_kwargs: None,
    )
    task = asyncio.create_task(workflow_tool.execute_workflow_tool(
        agent, runtime, {"goal": "test workflow"},
    ))
    await asyncio.wait_for(entered.wait(), timeout=2)

    job = next(item for item in manager.job_list() if item["kind"] == "workflow")
    assert job["state"] == "running"
    output = await manager.job_output(job["job_id"])
    assert '"type": "workflow_started"' in output["output"]

    killed = await manager.job_kill(job["job_id"])
    assert killed["state"] == "cancelled"
    with pytest.raises(asyncio.CancelledError):
        await task
    final = await manager.job_output(job["job_id"])
    assert final["state"] == "cancelled"
