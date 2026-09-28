"""End-to-end proof of the long-lived personal agent loop.

Scenario (the closeout plan's "qualitative change" acceptance):

    create a Project
    -> start a long-running durable agent task in a background process
    -> the task uses a local plugin and records project/memory state
    -> kill the process mid-task
    -> "restart": a fresh process recovers the workflow via DBOS
    -> the task completes and writes back state
    -> a brand-new conversation recovers "where we were" from
       Project + MemoryOS adapter + session_search

Everything runs against the real components (ProjectStore, PluginRuntime,
MemoryOSAdapter, DurableBackend) with a real cross-process crash.
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
from atlas.memory.memoryos_adapter import MemoryOSAdapter
from atlas.projects import ProjectStore

CORE_DIR = Path(__file__).resolve().parents[1]

CHILD_SCRIPT = """
import asyncio, json, sys
sys.path.insert(0, r"{core_dir}")
from pathlib import Path

from atlas.capabilities.durable.dbos_backend import DurableBackend
from atlas.memory import MemoryStore
from atlas.memory.memoryos_adapter import MemoryOSAdapter
from atlas.plugins import PluginRuntime
from atlas.projects import ProjectStore


async def main() -> None:
    config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    marker = Path(config["started_marker"])

    memory = MemoryStore(db_path=Path(config["data_dir"]) / "atlas.db")
    await memory.init()
    adapter = MemoryOSAdapter(memory)
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
    await adapter.set_project_state(
        project.project_id, "closeout merged; starting hub wave",
    )

    # use a local plugin for real: install, load, invoke a command
    runtime = PluginRuntime(
        [Path(config["plugin_source"]), Path(config["data_dir"]) / "plugins"],
        Path(config["data_dir"]) / "plugins" / "state.json",
    )
    runtime.install_local(Path(config["plugin_source"]))
    report = await runtime.load_all()
    command_prompt = "plugin-missing"
    for plugin in runtime.discover():
        if plugin["loaded"]:
            from atlas.agent.capabilities import AgentCapabilityRegistry

            registry = AgentCapabilityRegistry()
            await runtime.load_all(
                hook_bus=None, mcp_client=None, capabilities=registry,
            )
            invoked = await registry.invoke(
                "plugin.demo.command.standup",
            )
            command_prompt = str(invoked.get("prompt", ""))
    await adapter.record_decision(
        "run hub wave on durable",
        rationale=command_prompt,
        project_id=project.project_id,
        source_conversation_id=conversation,
    )

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
    plugin_source = tmp_path / "downloaded-plugins" / "demo-plugin"
    (plugin_source / "commands").mkdir(parents=True)
    (plugin_source / "plugin.json").write_text(
        json.dumps({"name": "demo", "version": "1.0.0"}), encoding="utf-8",
    )
    (plugin_source / "commands" / "standup.md").write_text(
        "昨天的进展：closeout 合并；今天的计划：hub 上线。", encoding="utf-8",
    )
    started_marker = tmp_path / "child-started.marker"
    child_config = tmp_path / "child-config.json"
    child_config.write_text(json.dumps({
        "data_dir": str(data_dir),
        "workspace": str(workspace),
        "plugin_source": str(plugin_source),
        "started_marker": str(started_marker),
    }), encoding="utf-8")

    # Phase A: the "Atlas process" builds state, uses a plugin, and crashes.
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
    adapter = MemoryOSAdapter(memory)
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
        await adapter.set_project_state(
            str(project.project_id), "hub resumed after crash; wave continues",
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
        recall = await adapter.session_search("hub", conversation_ids=conversation_ids)
        assert recall, "project-scoped recall found nothing"
        assert any(
            "hub 后台任务" in hit["content"] for hit in recall
        ), f"recall missed the resumed session: {recall}"
        decisions = await adapter.project_decisions(str(project.project_id))
        assert any(
            "hub wave" in decision["summary"] and "closeout" in decision["rationale"]
            for decision in decisions
        ), f"plugin-informed decision missing: {decisions}"
        assert (
            await adapter.get_project_state(str(project.project_id))
            == "hub resumed after crash; wave continues"
        )
    finally:
        durable.stop()
        await projects.close()
        await memory.close()
