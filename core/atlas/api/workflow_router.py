"""Saved DAG workflow templates and durable run inspection."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException

from atlas.config import get_config
from atlas.task_artifacts import TomlRecordStore
from atlas.workflow.graph import graph_to_dict
from atlas.workflow.journal import WorkflowJournal

router = APIRouter(prefix="/api/workflows")

_BUILTIN_BLUEPRINTS: list[dict[str, Any]] = [
    {"id": "builtin-implementation", "name": "功能实现与交付", "goal": "实现目标并交付可验证结果", "builtin": True,
     "steps": [
         {"id": "inspect", "title": "检查现状与约束", "goal": "检查相关实现、任务要求和现有验证方式", "depends_on": [], "acceptance": ["明确受影响文件和已有行为"]},
         {"id": "implement", "title": "实现变更", "goal": "按要求实现功能并更新相关文档", "depends_on": ["inspect"], "acceptance": ["功能可通过产品入口使用"]},
         {"id": "verify", "title": "验证与交付", "goal": "运行针对性验证并汇总变更与结果", "depends_on": ["implement"], "acceptance": ["验证通过且结果可复查"]},
     ]},
    {"id": "builtin-investigation", "name": "问题调查与修复", "goal": "复现问题、修复根因并验证", "builtin": True,
     "steps": [
         {"id": "reproduce", "title": "复现并收集证据", "goal": "使用可重复的场景复现问题并记录错误", "depends_on": [], "acceptance": ["得到稳定复现步骤和根因线索"]},
         {"id": "fix", "title": "修复根因", "goal": "针对根因实现最小完整修复", "depends_on": ["reproduce"], "acceptance": ["原问题场景不再失败"]},
         {"id": "regression", "title": "回归验证", "goal": "运行针对性回归并检查相关路径", "depends_on": ["fix"], "acceptance": ["回归验证通过"]},
     ]},
]


def _templates() -> TomlRecordStore:
    return TomlRecordStore(get_config().db_path.parent, "workflow-templates")


@router.get("/templates")
async def list_templates() -> dict[str, Any]:
    saved = [_upgrade_blueprint(item) for item in _templates().list()]
    return {"templates": [*_BUILTIN_BLUEPRINTS, *saved]}


@router.post("/templates", status_code=201)
async def create_template(body: dict[str, Any]) -> dict[str, Any]:
    try:
        return {"template": _templates().put(_validate_blueprint(body))}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/templates/{template_id}")
async def update_template(template_id: str, body: dict[str, Any]) -> dict[str, Any]:
    store = _templates()
    old = store.get(template_id)
    if old is None:
        raise HTTPException(status_code=404, detail="Workflow template not found")
    try:
        return {"template": store.put(_validate_blueprint({**_upgrade_blueprint(old), **body, "id": template_id}))}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/templates/{template_id}")
async def delete_template(template_id: str) -> dict[str, bool]:
    if template_id.startswith("builtin-"):
        raise HTTPException(status_code=422, detail="Built-in blueprints cannot be deleted")
    if not _templates().delete(template_id):
        raise HTTPException(status_code=404, detail="Workflow template not found")
    return {"deleted": True}


def _upgrade_blueprint(value: dict[str, Any]) -> dict[str, Any]:
    """Give legacy name/goal templates a valid editable single-step blueprint."""
    if isinstance(value.get("steps"), list) and value["steps"]:
        return {**value, "builtin": bool(value.get("builtin", False))}
    return {**value, "steps": [{"id": "task", "title": value.get("name", "执行目标"),
                                 "goal": value.get("goal", ""), "depends_on": [], "acceptance": ["完成目标并汇报结果"]}],
            "builtin": bool(value.get("builtin", False))}


def _validate_blueprint(value: dict[str, Any]) -> dict[str, Any]:
    name, goal = str(value.get("name") or "").strip(), str(value.get("goal") or "").strip()
    steps = value.get("steps")
    if not name or not goal or not isinstance(steps, list) or not 1 <= len(steps) <= 30:
        raise ValueError("blueprint requires a name, goal, and 1 to 30 steps")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in steps:
        if not isinstance(raw, dict):
            raise ValueError("each blueprint step must be an object")
        step_id = str(raw.get("id") or "").strip()
        title, task = str(raw.get("title") or "").strip(), str(raw.get("goal") or "").strip()
        depends = raw.get("depends_on", [])
        acceptance = raw.get("acceptance", [])
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", step_id) or step_id in seen or not title or not task:
            raise ValueError("steps need unique IDs and non-empty titles and goals")
        if not isinstance(depends, list) or any(not isinstance(dep, str) or dep not in seen for dep in depends):
            raise ValueError(f"step {step_id} dependencies must refer to earlier steps")
        if not isinstance(acceptance, list) or not acceptance or any(not isinstance(item, str) or not item.strip() for item in acceptance):
            raise ValueError(f"step {step_id} needs at least one acceptance item")
        normalized.append({"id": step_id, "title": title, "goal": task,
                           "depends_on": list(dict.fromkeys(depends)),
                           "acceptance": [item.strip() for item in acceptance]})
        seen.add(step_id)
    return {"id": str(value.get("id") or "") or None, "name": name, "goal": goal, "steps": normalized}


@router.get("/runs")
async def list_runs(limit: int = 100) -> dict[str, Any]:
    return {"runs": WorkflowJournal().list_runs(limit=limit)}


@router.get("/runs/{workflow_id}")
async def get_run(workflow_id: str) -> dict[str, Any]:
    journal = WorkflowJournal()
    try:
        graph = journal.load_graph(workflow_id)
        status = journal.status(workflow_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workflow run not found") from exc
    return {"workflow_id": workflow_id, "status": status, "graph": graph_to_dict(graph),
            "events": journal.events(workflow_id)}
