"""Saved DAG workflow templates and durable run inspection."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from atlas.config import get_config
from atlas.task_artifacts import TomlRecordStore
from atlas.workflow.graph import graph_to_dict
from atlas.workflow.journal import WorkflowJournal

router = APIRouter(prefix="/api/workflows")


def _templates() -> TomlRecordStore:
    return TomlRecordStore(get_config().db_path.parent, "workflow-templates")


@router.get("/templates")
async def list_templates() -> dict[str, Any]:
    return {"templates": _templates().list()}


@router.post("/templates", status_code=201)
async def create_template(body: dict[str, Any]) -> dict[str, Any]:
    name, goal = str(body.get("name") or "").strip(), str(body.get("goal") or "").strip()
    if not name or not goal:
        raise HTTPException(status_code=422, detail="name and goal are required")
    try:
        return {"template": _templates().put({"name": name, "goal": goal})}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/templates/{template_id}")
async def update_template(template_id: str, body: dict[str, Any]) -> dict[str, Any]:
    store = _templates()
    old = store.get(template_id)
    if old is None:
        raise HTTPException(status_code=404, detail="Workflow template not found")
    name, goal = str(body.get("name", old["name"])).strip(), str(body.get("goal", old["goal"])).strip()
    if not name or not goal:
        raise HTTPException(status_code=422, detail="name and goal are required")
    return {"template": store.put({**old, "name": name, "goal": goal, "id": template_id})}


@router.delete("/templates/{template_id}")
async def delete_template(template_id: str) -> dict[str, bool]:
    if not _templates().delete(template_id):
        raise HTTPException(status_code=404, detail="Workflow template not found")
    return {"deleted": True}


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
