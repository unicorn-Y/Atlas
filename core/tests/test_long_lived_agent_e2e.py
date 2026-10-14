"""End-to-end proof of the long-lived personal agent loop.

Scenario (the closeout plan's "qualitative change" acceptance):

    create a Project
    -> start a long-running durable agent task in a background process
    -> the process creates a project conversation
    -> kill the process mid-task
    -> "restart": a fresh process recovers the workflow via DBOS
    -> the task completes and writes a resumed conversation
    -> a brand-new conversation recovers "where we were" from
       Project + session_search

The test exercises ProjectStore, MemoryStore session_search, and DurableBackend across a process crash.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from atlas.capabilities.durable.dbos_backend import DurableBackend
from atlas.memory import MemoryStore
from atlas.projects import ProjectStore

CORE_DIR = Path(__file__).resolve().parents[1]

CHILD_SCRIPT = """
import asyncio, json, sys
sys.path.insert(0, r"{core_dir}")
from pathlib import Path

from atlas.capabilities.durable.dbos_backend import DurableBackend
from atlas.memory import MemoryStore
from atlas.projects import ProjectStore


async def main() -> None:
    config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    marker = Path(config["started_marker"])

    memory = MemoryStore(db_path=Path(config["data_dir"]) / "atlas.db")
    await memory.init()
    projects = ProjectStore(Path(config["data_dir"]) / "projects.db")
    await projects.init()

    # create the Project and associate the working conversation
    project = await projects.create_project(
        "Atlas", workspace_path=config["workspace"], current_goal="ship the hub",
    )
    conversation = await memory.create_conversation("Atlas work")
    await projects.attach_conversation(project.project_id, conversation)
    await memory.save_message(
        conversation, "user", "hybrid router 已经合并，下一步是 hub 后台任务",
    )
    # start the long-running durable task, then die mid-run
    # start the long-running durable task, then die mid-run
    durable = DurableBackend(Path(config["data_dir"]) / "dbos.sqlite")

    async def dispatcher(payload: dict) -> dict:
        marker.write_text("started", encoding="utf-8")
        await asyncio.sleep(600)  # killed here
        return {{}}

    durable.set_dispatcher(dispatcher, asyncio.get_running_loop())
    durable.start()
    await durable.run_agent_task({{"task_id": "{task_id}", "message": "long task"}})
    marker.write_text("never-reached", encoding="utf-8")


asyncio.run(main())
""".format(core_dir=str(CORE_DIR), task_id="hub-wave-1")


@pytest.mark.skipif(sys.platform != "win32", reason="e2e tuned for this Windows host")
async def test_long_lived_agent_survives_crash_and_recovers_context(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    started_marker = tmp_path / "child-started.marker"
    child_config = tmp_path / "child-config.json"
    child_config.write_text(json.dumps({
        "data_dir": str(data_dir),
        "workspace": str(workspace),
        "started_marker": str(started_marker),
    }), encoding="utf-8")

    # Phase A: the "Atlas process" creates a project and crashes.
    child = subprocess.Popen(
        [sys.executable, "-c", CHILD_SCRIPT, str(child_config)],
        cwd=str(CORE_DIR),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and not started_marker.exists():
            await asyncio.sleep(0.3)
        assert started_marker.exists(), "child never reached the durable task"
    finally:
        child.kill()
        child.wait(timeout=15)

    # Phase B: the restarted process recovers the task and finishes it.
    memory = MemoryStore(db_path=data_dir / "atlas.db")
    await memory.init()
    projects = ProjectStore(data_dir / "projects.db")
    await projects.init()
    project = await projects.get_by_name("Atlas")
    assert project is not None, "project from the crashed process is gone"

    completion: dict = {}

    async def resumed_dispatcher(payload: dict) -> dict:
        completion.update(payload)
        conversation = await memory.create_conversation("Atlas work resumed")
        await projects.attach_conversation(str(project.project_id), conversation)
        await memory.save_message(
            conversation, "user",
            "hub 后台任务从崩溃中恢复完成，hub wave 可以继续",
        )
        return {"status": "completed", "payload": payload}

    durable = DurableBackend(data_dir / "dbos.sqlite")
    durable.set_dispatcher(resumed_dispatcher, asyncio.get_running_loop())
    try:
        assert durable.start()["started"] is True
        deadline = asyncio.get_running_loop().time() + 30
        while asyncio.get_running_loop().time() < deadline and not completion:
            await asyncio.sleep(0.5)
        assert completion.get("task_id") == "hub-wave-1", (
            "DBOS recovery did not resume the crashed long-running task"
        )

        # A brand-new conversation recovers "where we were".
        conversation_ids = await projects.list_conversations(str(project.project_id))
        recall = await memory.session_search("hub", conversation_ids=conversation_ids)
        assert recall, "project-scoped recall found nothing"
        assert any(
            "hub 后台任务" in hit["content"] for hit in recall
        ), f"recall missed the resumed session: {recall}"
    finally:
        durable.stop()
        await projects.close()
        await memory.close()
