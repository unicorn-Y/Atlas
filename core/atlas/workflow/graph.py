# Ported from zai-org/ZCode@aac4755666d09fdcd70272fcf063c077a639015f: apps/zcode-cli/packages/core/src/workflow/scheduler/graph.ts (Apache-2.0)
"""Dependency validation, ready-frontier calculation, and graph serialization."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .types import WorkflowCollection, WorkflowEdge, WorkflowGraph, WorkflowNode


TERMINAL_DEPENDENCY_STATUSES = {"completed", "failed", "skipped", "cancelled"}


def dependencies(graph: WorkflowGraph) -> dict[str, list[str]]:
    """Combine node-local dependencies and explicit graph edges, preserving order."""
    result = {node.id: list(node.depends_on) for node in graph.nodes}
    for edge in graph.edges:
        result.setdefault(edge.to_node, []).append(edge.from_node)
    return {node_id: list(dict.fromkeys(parents)) for node_id, parents in result.items()}


def validate_graph(graph: WorkflowGraph) -> None:
    """Reject unknown nodes, invalid retry limits, and dependency cycles."""
    if not graph.goal.strip():
        raise ValueError("Workflow goal must not be empty")
    if not graph.workspace.strip():
        raise ValueError("Workflow workspace must not be empty")
    if graph.max_attempts < 1 or graph.failure_threshold < 1:
        raise ValueError("Workflow retry and failure thresholds must be positive")
    ids = [node.id for node in graph.nodes]
    if len(ids) != len(set(ids)):
        raise ValueError("Workflow node ids must be unique")
    known = set(ids)
    incoming = dependencies(graph)
    for node in graph.nodes:
        attempts = node.max_attempts if node.max_attempts is not None else graph.max_attempts
        if attempts < 1:
            raise ValueError(f"Node {node.id!r} max_attempts must be positive")
        if node.attempts < 0:
            raise ValueError(f"Node {node.id!r} attempts must be nonnegative")
        for parent in incoming.get(node.id, []):
            if parent not in known:
                raise ValueError(f"Node {node.id!r} depends on unknown node {parent!r}")
            if parent == node.id:
                raise ValueError(f"Node {node.id!r} cannot depend on itself")
    for edge in graph.edges:
        if edge.from_node not in known or edge.to_node not in known:
            raise ValueError(f"Workflow edge references unknown node: {edge.from_node!r} -> {edge.to_node!r}")
    for collection in graph.collections:
        if collection.frontier_target < 1 or collection.max_planner_runs < 1 or collection.max_consecutive_errors < 1:
            raise ValueError(f"Collection {collection.collection_id!r} limits must be positive")
    cycle = _find_cycle(incoming)
    if cycle:
        raise ValueError("Workflow dependency cycle: " + " -> ".join(cycle))


def ready_nodes(graph: WorkflowGraph) -> list[WorkflowNode]:
    """Return pending nodes whose dependencies have reached terminal states."""
    by_id = {node.id: node for node in graph.nodes}
    incoming = dependencies(graph)
    return [
        node
        for node in graph.nodes
        if node.status == "pending"
        and all(by_id[parent].status in TERMINAL_DEPENDENCY_STATUSES for parent in incoming[node.id])
    ]


def blocked_nodes(graph: WorkflowGraph) -> list[dict[str, Any]]:
    """Describe pending nodes that still wait on nonterminal dependencies."""
    by_id = {node.id: node for node in graph.nodes}
    incoming = dependencies(graph)
    return [
        {"node_id": node.id, "blocked_by": [p for p in incoming[node.id] if by_id[p].status not in TERMINAL_DEPENDENCY_STATUSES]}
        for node in graph.nodes
        if node.status == "pending"
        and any(by_id[p].status not in TERMINAL_DEPENDENCY_STATUSES for p in incoming[node.id])
    ]


def ordered_ready_nodes(graph: WorkflowGraph) -> list[WorkflowNode]:
    """Keep regular work first and round-robin ready tasks across explorable groups."""
    ready = ready_nodes(graph)
    grouped: dict[str, list[WorkflowNode]] = {}
    for collection in graph.collections:
        if not collection.explorable or collection.exhausted:
            continue
        member_ids = set(collection_node_ids(graph, collection))
        grouped[collection.collection_id] = [node for node in ready if node.id in member_ids]
    exploration_ids = {node.id for nodes in grouped.values() for node in nodes}
    regular = [node for node in ready if node.id not in exploration_ids]
    queues = [(collection_id, nodes[:]) for collection_id, nodes in grouped.items() if nodes]
    exploration: list[WorkflowNode] = []
    cursor = 0
    while queues:
        index = cursor % len(queues)
        _, nodes = queues[index]
        if nodes:
            exploration.append(nodes.pop(0))
        if not nodes:
            queues.pop(index)
        else:
            cursor += 1
    unique_exploration = list({node.id: node for node in exploration}.values())
    return regular + unique_exploration


def collection_node_ids(graph: WorkflowGraph, collection: WorkflowCollection) -> list[str]:
    return list(dict.fromkeys([
        *collection.node_ids,
        *(node.id for node in graph.nodes if node.collection_id == collection.collection_id),
    ]))


def collection_frontier(graph: WorkflowGraph, collection: WorkflowCollection) -> int:
    members = set(collection_node_ids(graph, collection))
    return sum(node.status in {"pending", "active"} for node in graph.nodes if node.id in members)


def graph_to_dict(graph: WorkflowGraph) -> dict[str, Any]:
    """Return a JSON-compatible durable snapshot of the entire graph state."""
    return asdict(graph)


def graph_from_dict(value: dict[str, Any]) -> WorkflowGraph:
    """Rebuild the dataclass graph from a journal snapshot."""
    nodes = [WorkflowNode(**_node_fields(item)) for item in value.get("nodes", [])]
    edges = [
        WorkflowEdge(
            from_node=item.get("from_node", item.get("from", "")),
            to_node=item.get("to_node", item.get("to", "")),
        )
        for item in value.get("edges", [])
    ]
    collections = [WorkflowCollection(**_collection_fields(item)) for item in value.get("collections", [])]
    return WorkflowGraph(
        goal=value["goal"],
        nodes=nodes,
        workspace=value["workspace"],
        edges=edges,
        workflow_id=value.get("workflow_id"),
        model=value.get("model"),
        max_attempts=value.get("max_attempts", 3),
        failure_threshold=value.get("failure_threshold", 3),
        collections=collections,
    )


def _node_fields(value: dict[str, Any]) -> dict[str, Any]:
    names = WorkflowNode.__dataclass_fields__.keys()
    return {name: value[name] for name in names if name in value}


def _collection_fields(value: dict[str, Any]) -> dict[str, Any]:
    names = WorkflowCollection.__dataclass_fields__.keys()
    return {name: value[name] for name in names if name in value}


def _find_cycle(incoming: dict[str, list[str]]) -> list[str] | None:
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def visit(node_id: str) -> list[str] | None:
        if node_id in visiting:
            start = stack.index(node_id)
            return [*stack[start:], node_id]
        if node_id in visited:
            return None
        visiting.add(node_id)
        stack.append(node_id)
        for parent in incoming[node_id]:
            result = visit(parent)
            if result:
                return result
        stack.pop()
        visiting.remove(node_id)
        visited.add(node_id)
        return None

    for node_id in incoming:
        result = visit(node_id)
        if result:
            return result
    return None
