"""U10 integration scenarios for saved/dynamic workflows, automation worktrees and task overview.

Runs from the checkout with ATLAS_ROOT pointing at the configured local Atlas profile.
The workflow planner uses the configured deepseek-v4.1-flash provider; git automation
dispatch and presentation fixtures remain local and deterministic.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))


def command(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"command failed: {args[0]}")
    return result.stdout.strip()


async def workflow_scenario(root: Path) -> None:
    os.environ["ATLAS_WORKFLOW_DB"] = str(root / "workflow.db")
    from atlas.models import ModelManager
    from atlas.task_artifacts import TomlRecordStore
    from atlas.workflow import NodeResult, WorkflowJournal, plan_workflow, run_workflow
    from atlas.api import workflow_router

    journal = WorkflowJournal(root / "workflow.db")
    model_router = ModelManager().model_router

    async def call_planner(*, prompt: str, model: str | None) -> str:
        response = await model_router.complete_for(
            model or "deepseek-v4.1-flash", "workflow_planner",
            [{"role": "user", "content": prompt}], max_tokens=1600, temperature=0,
        )
        print("Workflow planner: configured deepseek-v4.1-flash request completed", flush=True)
        return response.text

    graph = await plan_workflow(
        "为一个小型 Python 工具规划：检查入口与依赖，随后产出验证报告。",
        workspace=str(root), call_model=call_planner, model="deepseek-v4.1-flash",
    )
    graph.workflow_id = "u10-dynamic-workflow"

    class Runner:
        async def run(self, *, goal: str, context: str, workspace: str, model: str | None) -> NodeResult:
            artifact = root / "workflow-artifacts" / f"{len(list((root / 'workflow-artifacts').glob('*'))):02d}.md"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(f"# {goal}\n\nCompleted from {workspace}.\n", encoding="utf-8")
            return NodeResult(response=f"完成：{goal}", model=model,
                              metadata={"artifacts": [{"name": artifact.name, "path": str(artifact)}]})

    result = await run_workflow(graph, Runner(), max_parallel=3, on_event=lambda _event: None, journal=journal)
    assert result.status == "completed", result.status
    assert result.graph.nodes and all(node.output for node in result.graph.nodes)
    saved_runs = journal.list_runs(limit=10)
    saved = next(run for run in saved_runs if run["workflow_id"] == "u10-dynamic-workflow")
    assert len(saved["events"]) >= len(result.graph.nodes) * 2
    assert all(node["status"] == "completed" for node in saved["graph"]["nodes"])

    templates = TomlRecordStore(root / "settings", "workflow-templates")
    workflow_router._templates = lambda: templates
    template = (await workflow_router.create_template({"name": "报告模板", "goal": "检查入口并输出报告"}))["template"]
    edited = (await workflow_router.update_template(
        template["id"], {"name": "报告模板（更新）", "goal": "检查入口、测试并输出报告"},
    ))["template"]
    assert edited["goal"].startswith("检查入口") and (await workflow_router.list_templates())["templates"]
    rerun_graph = await plan_workflow(edited["goal"], workspace=str(root), call_model=call_planner,
                                      model="deepseek-v4.1-flash")
    rerun_graph.workflow_id = "u10-saved-template-rerun"
    rerun = await run_workflow(rerun_graph, Runner(), max_parallel=3,
                               on_event=lambda _event: None, journal=journal)
    assert rerun.status == "completed"
    assert (await workflow_router.delete_template(template["id"]))["deleted"]
    assert not templates.get(template["id"])
    assert any(run["workflow_id"] == "u10-dynamic-workflow" for run in (await workflow_router.list_runs())["runs"])
    print("Workflow scenario: real planner, dependent child DAG, durable outputs/events, template edit and rerun definition passed", flush=True)


async def automation_worktree_scenario(root: Path) -> None:
    from atlas.automation.engine import AutomationEngine
    from atlas.automation.store import AutomationStore, AutomationValidationError, normalize_record, validate_record

    repository = root / "repo"
    repository.mkdir()
    command("git", "init", "-q", str(repository))
    command("git", "-C", str(repository), "config", "user.email", "u10@example.test")
    command("git", "-C", str(repository), "config", "user.name", "U10 Fixture")
    (repository / "README.md").write_text("base workspace\n", encoding="utf-8")
    command("git", "-C", str(repository), "add", "README.md")
    command("git", "-C", str(repository), "commit", "-m", "fixture")

    store = AutomationStore(root / "automations.toml")
    record = store.put({
        "id": "u10-worktree", "name": "U10 worktree check", "enabled": True,
        "trigger": {"kind": "interval", "every_seconds": 3600},
        "payload": {"kind": "agent_turn", "message": "写一条工作树结果", "execution_mode": "worktree",
                    "base_directory": str(repository), "cleanup_policy": "keep"},
    })
    observed: list[dict[str, Any]] = []

    async def dispatch(payload: dict[str, Any]) -> str:
        observed.append(payload)
        workspace = Path(payload["workspace"])
        assert workspace.is_dir() and workspace != repository
        (workspace / "agent-result.txt").write_text("created in isolated tree", encoding="utf-8")
        return "isolated run completed"

    engine = AutomationEngine(store, dispatch_turn=dispatch)
    outcome = await engine.execute_payload(record["id"], "manual")
    result = outcome["result"]
    path = Path(result["worktree_path"])
    assert outcome["status"] == "ok" and (path / "agent-result.txt").is_file()
    assert not (repository / "agent-result.txt").exists()
    assert result["worktree_branch"].startswith("atlas/automation-") and result["text"] == "isolated run completed"

    current = store.get(record["id"])
    assert current and current["payload"]["worktree_path"] == str(path)
    engine._cleanup_record_worktree(current)  # same cleanup path used by cancel/delete
    assert not path.exists()
    store.put({**current, "payload": {**current["payload"], "cleanup_policy": "remove_after_run"}})
    removed_run = await engine.execute_payload(record["id"], "manual")
    removed_path = Path(removed_run["result"]["worktree_path"])
    assert removed_run["status"] == "ok" and not removed_path.exists()
    invalid = normalize_record({**record, "payload": {**record["payload"], "execution_mode": "worktree", "base_directory": ""}})
    try:
        validate_record(invalid)
    except AutomationValidationError:
        pass
    else:
        raise AssertionError("worktree API payload validation accepted an empty base directory")
    print("Automation scenario: local Git worktree dispatch, isolated write, persisted run path/branch, keep and cleanup policies, API payload validation passed", flush=True)


async def main() -> None:
    profile = os.environ.get("ATLAS_ROOT")
    if not profile or not Path(profile).is_dir():
        raise RuntimeError("ATLAS_ROOT must point at the configured local Atlas profile")
    with tempfile.TemporaryDirectory(prefix="atlas-u10-") as directory:
        root = Path(directory)
        await workflow_scenario(root)
        await automation_worktree_scenario(root)
    vitest = subprocess.run(
        ["npx.cmd", "vitest", "run", "--root", ".", "src/renderer/shell/panels/TaskOverviewPanel.test.tsx"],
        cwd=ROOT / "frontend", capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if vitest.returncode:
        raise RuntimeError(vitest.stdout + "\n" + vitest.stderr)
    print("Task overview scenario: rendered plan, source, generated file and summary fixture passed", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
    print("U10 CHECK PASS")
