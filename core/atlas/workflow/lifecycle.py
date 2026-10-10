# Ported from zai-org/ZCode@29628c9acdb81b703bbd4080c207a0e7ce5e276e: apps/zcode-cli/packages/core/src/workflow/lifecycle.ts (Apache-2.0)
"""Pure node-state transitions used by scheduling and crash recovery."""

from __future__ import annotations

from .types import WorkflowGraph, WorkflowNode


def reconcile_for_resume(graph: WorkflowGraph) -> list[str]:
    """Repair nodes left active by interruption, preserving completed work and attempts."""
    repaired: list[str] = []
    for node in graph.nodes:
        if node.status == "active":
            node.status = "pending"
            node.error = "Recovered after an interrupted workflow run."
            repaired.append(node.id)
    return repaired


def activate_node(node: WorkflowNode) -> None:
    """Clear the previous error and mark a newly dispatched attempt active."""
    node.status = "active"
    node.error = None


def fail_node(graph: WorkflowGraph, node: WorkflowNode, error: str) -> bool:
    """Record a failed attempt; return true when another attempt remains."""
    node.attempts += 1
    node.error = error
    max_attempts = node.max_attempts if node.max_attempts is not None else graph.max_attempts
    retry = node.attempts < max_attempts
    node.status = "pending" if retry else "failed"
    return retry

