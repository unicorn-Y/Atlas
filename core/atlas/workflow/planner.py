# Ported from zai-org/ZCode@29628c9acdb81b703bbd4080c207a0e7ce5e276e: apps/zcode-cli/packages/core/src/workflow/scheduler/planner-expansion.ts (Apache-2.0)
# Ported from zai-org/ZCode@29628c9acdb81b703bbd4080c207a0e7ce5e276e: apps/zcode-cli/packages/core/src/workflow/scheduler/collection-planner.ts (Apache-2.0)
# Ported from zai-org/ZCode@29628c9acdb81b703bbd4080c207a0e7ce5e276e: apps/zcode-cli/packages/core/src/workflow/scheduler/collection-runtime.ts (Apache-2.0)
# Planner prompt shape follows apps/zcode-cli/packages/core/src/workflow/scheduler/prompts.ts at the same commit.
"""Callback-driven initial planning and validated dynamic DAG expansion."""

from __future__ import annotations

import inspect
import json
from typing import Any, Awaitable, Callable, Mapping, Protocol

from .graph import validate_graph
from .prompts import build_collection_prompt, build_planner_prompt
from .types import WorkflowCollection, WorkflowEdge, WorkflowGraph, WorkflowNode


class PlannerCallback(Protocol):
    """Injected model boundary. Implementations own model selection and transport."""

    def __call__(self, *, prompt: str, model: str | None) -> str | Mapping[str, Any] | Awaitable[str | Mapping[str, Any]]: ...


async def plan_workflow(
    goal: str,
    *,
    workspace: str,
    call_model: PlannerCallback,
    model: str | None = None,
    max_attempts: int = 3,
    failure_threshold: int = 3,
) -> WorkflowGraph:
    """Ask the supplied callback for a graph, parse it, and validate its dependencies."""
    response = call_model(prompt=build_planner_prompt(goal, workspace, model=model), model=model)
    if inspect.isawaitable(response):
        response = await response
    graph_payload = _as_mapping(response)
    graph = graph_from_planner_payload(
        goal,
        workspace=workspace,
        payload=graph_payload,
        model=model,
        max_attempts=max_attempts,
        failure_threshold=failure_threshold,
    )
    validate_graph(graph)
    return graph


async def expand_collection(
    graph: WorkflowGraph,
    collection: WorkflowCollection,
    *,
    call_model: PlannerCallback,
    unseen_completions: list[str] | None = None,
) -> list[str]:
    """Expand a planner-managed collection and return newly added node ids."""
    response = call_model(
        prompt=build_collection_prompt(graph, collection),
        model=graph.model,
    )
    if inspect.isawaitable(response):
        response = await response
    return apply_planner_expansion(
        graph,
        collection,
        _as_mapping(response),
        unseen_completions=unseen_completions or [],
    )


def graph_from_planner_payload(
    goal: str,
    *,
    workspace: str,
    payload: Mapping[str, Any],
    model: str | None = None,
    max_attempts: int = 3,
    failure_threshold: int = 3,
) -> WorkflowGraph:
    """Translate planner JSON node/edge records into the public graph contract."""
    nodes = [_planner_node(raw, default_goal=goal) for raw in payload.get("nodes", [])]
    edges = [_edge(raw) for raw in payload.get("edges", [])]
    collections = [
        WorkflowCollection(
            collection_id=str(raw["collection_id"]),
            goal=str(raw.get("goal", goal)),
            node_ids=list(raw.get("node_ids", [])),
            explorable=bool(raw.get("explorable", True)),
            frontier_target=int(raw.get("frontier_target", 3)),
            max_planner_runs=int(raw.get("max_planner_runs", 10)),
            max_consecutive_errors=int(raw.get("max_consecutive_errors", 3)),
        )
        for raw in payload.get("collections", [])
    ]
    graph = WorkflowGraph(
        goal=goal,
        nodes=nodes,
        workspace=workspace,
        edges=edges,
        model=model,
        max_attempts=max_attempts,
        failure_threshold=failure_threshold,
        collections=collections,
    )
    for node in graph.nodes:
        if not node.title:
            node.title = node.id
    return graph


def apply_planner_expansion(
    graph: WorkflowGraph,
    collection: WorkflowCollection,
    result: Mapping[str, Any],
    *,
    unseen_completions: list[str] | None = None,
) -> list[str]:
    """Append unique nodes/edges, reject cycles, and update collection frontier state."""
    existing_node_ids = {node.id for node in graph.nodes}
    added_nodes: list[WorkflowNode] = []
    for raw in result.get("nodes", []):
        node = _planner_node(raw, default_goal=collection.goal, collection_id=collection.collection_id)
        if node.id in existing_node_ids:
            raise ValueError(f"Planner returned duplicate workflow node: {node.id}")
        existing_node_ids.add(node.id)
        added_nodes.append(node)

    candidate = WorkflowGraph(
        goal=graph.goal,
        nodes=[*graph.nodes, *added_nodes],
        workspace=graph.workspace,
        edges=list(graph.edges),
        workflow_id=graph.workflow_id,
        model=graph.model,
        max_attempts=graph.max_attempts,
        failure_threshold=graph.failure_threshold,
        collections=graph.collections,
    )
    new_edges: list[WorkflowEdge] = []
    existing = {(edge.from_node, edge.to_node) for edge in graph.edges}
    for raw in result.get("edges", []):
        edge = _edge(raw)
        if (edge.from_node, edge.to_node) not in existing:
            new_edges.append(edge)
            existing.add((edge.from_node, edge.to_node))
    for node in added_nodes:
        for dependency in node.depends_on:
            if (dependency, node.id) not in existing:
                new_edges.append(WorkflowEdge(dependency, node.id))
                existing.add((dependency, node.id))
    candidate.edges.extend(new_edges)
    validate_graph(candidate)

    graph.nodes.extend(added_nodes)
    graph.edges.extend(new_edges)
    collection.node_ids = list(dict.fromkeys([
        *collection.node_ids,
        *result.get("collection_node_ids", [node.id for node in added_nodes]),
    ]))
    collection.analyzed_node_ids = list(dict.fromkeys([
        *collection.analyzed_node_ids,
        *(unseen_completions or []),
        *[node.id for node in graph.nodes if node.collection_id == collection.collection_id and node.status == "completed"],
    ]))
    changed = bool(added_nodes or new_edges)
    if result.get("exhausted") is True:
        collection.exhausted = True
        collection.status = "exhausted"
    elif not changed and not any(
        node.status in {"pending", "active"} and node.id in set(collection.node_ids)
        for node in graph.nodes
    ):
        if collection.status == "draining":
            collection.exhausted = True
            collection.status = "exhausted"
        else:
            collection.status = "draining"
    else:
        collection.status = "active"
    return [node.id for node in added_nodes]


def _planner_node(raw: Mapping[str, Any], *, default_goal: str, collection_id: str | None = None) -> WorkflowNode:
    node_id = str(raw.get("id", "")).strip()
    if not node_id:
        raise ValueError("Planner node id must not be empty")
    title = str(raw.get("title", node_id))
    node_goal = str(raw.get("goal", raw.get("description", title or default_goal)))
    files = raw.get("files", raw.get("owned_files", []))
    return WorkflowNode(
        id=node_id,
        goal=node_goal,
        title=title,
        depends_on=[str(value) for value in raw.get("depends_on", raw.get("dependsOn", []))],
        owner=raw.get("owner"),
        files=[str(value) for value in files],
        description=raw.get("description"),
        prompt=raw.get("prompt"),
        context=str(raw.get("context", "")),
        workspace=raw.get("workspace"),
        model=raw.get("model"),
        max_attempts=raw.get("max_attempts"),
        collection_id=raw.get("collection_id", raw.get("collectionId", collection_id)),
    )


def _edge(raw: Mapping[str, Any]) -> WorkflowEdge:
    return WorkflowEdge(
        from_node=str(raw.get("from", raw.get("from_node", ""))),
        to_node=str(raw.get("to", raw.get("to_node", ""))),
    )


def _as_mapping(response: str | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(response, Mapping):
        return response
    value = response.strip()
    if value.startswith("```"):
        value = value.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Planner response is not valid JSON: {exc}") from exc
    if not isinstance(parsed, Mapping):
        raise ValueError("Planner response must be a JSON object")
    return parsed

