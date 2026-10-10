# Ported from zai-org/ZCode@29628c9acdb81b703bbd4080c207a0e7ce5e276e: apps/zcode-cli/packages/core/src/workflow/scheduler/prompts.ts (Apache-2.0)
"""Prompt construction kept separate from model access and runtime adapters."""

from __future__ import annotations

import json

from .types import WorkflowCollection, WorkflowGraph, WorkflowNode


def build_node_context(graph: WorkflowGraph, node: WorkflowNode) -> str:
    """Give a node its declared context, owned paths, and settled dependency outputs."""
    by_id = {item.id: item for item in graph.nodes}
    dependency_ids = list(dict.fromkeys([
        *node.depends_on,
        *(edge.from_node for edge in graph.edges if edge.to_node == node.id),
    ]))
    dependencies = [
        {"id": parent_id, "goal": by_id[parent_id].goal, "output": by_id[parent_id].output or ""}
        for parent_id in dependency_ids
        if parent_id in by_id
    ]
    details = [
        f"Workflow goal:\n{graph.goal}",
        f"Task node: {node.title or node.id} ({node.id})",
        f"Node goal:\n{node.goal}",
    ]
    if node.description:
        details.append(f"Description:\n{node.description}")
    if node.prompt:
        details.append(f"Node instructions:\n{node.prompt}")
    if node.context:
        details.append(f"Additional context:\n{node.context}")
    if node.owner:
        details.append(f"Owner:\n{node.owner}")
    if node.files:
        details.append("Owned files:\n" + "\n".join(f"- {path}" for path in node.files))
    if dependencies:
        details.append("Completed dependency outputs:\n" + json.dumps(dependencies, ensure_ascii=False, indent=2))
    details.append("Execute only this node's scope. Return a concise report with changes, validation, and residual risk.")
    return "\n\n".join(details)


def build_planner_prompt(goal: str, workspace: str, *, model: str | None = None) -> str:
    """Ask the injected model callback for a DAG payload in the planner's JSON shape."""
    shape = {
        "nodes": [{
            "id": "unique-id",
            "title": "short title",
            "goal": "node objective",
            "description": "optional details",
            "depends_on": ["node-id"],
            "owner": "optional responsible agent",
            "files": ["optional/path.py"],
            "prompt": "optional node instructions",
            "model": model,
        }],
        "edges": [{"from": "dependency-node-id", "to": "node-id"}],
    }
    return "\n".join([
        "You are an Atlas workflow planner. Decompose the user goal into a small acyclic dependency graph.",
        f"Workspace: {workspace}",
        f"User goal:\n{goal}",
        "Assign clear ownership and disjoint file scopes where possible. Include dependency edges for ordering.",
        "Return only JSON matching this shape:",
        json.dumps(shape, ensure_ascii=False),
    ])


def build_collection_prompt(graph: WorkflowGraph, collection: WorkflowCollection) -> str:
    """Describe the settled frontier to the callback before collection expansion."""
    members = [node for node in graph.nodes if node.id in set(collection.node_ids) or node.collection_id == collection.collection_id]
    nodes = [
        {"id": node.id, "title": node.title, "goal": node.goal, "status": node.status, "output": node.output or ""}
        for node in members
    ]
    return "\n".join([
        "You are an Atlas workflow exploration planner.",
        f"Workflow goal:\n{graph.goal}",
        f"Collection: {collection.collection_id}",
        f"Collection goal:\n{collection.goal}",
        "Existing collection nodes:\n" + json.dumps(nodes, ensure_ascii=False, indent=2),
        'Return only JSON: {"nodes":[{"id":"string","title":"string","goal":"string","depends_on":["node-id"],"owner":"string","files":["path"]}],"edges":[{"from":"node-id","to":"node-id"}],"collection_node_ids":["node-id"],"exhausted":false,"reasoning":"string"}',
        "Use new unique node ids, avoid cycles, and set exhausted=true only when no useful expansion remains.",
    ])

