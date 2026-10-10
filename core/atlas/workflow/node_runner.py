# Ported from zai-org/ZCode@aac4755666d09fdcd70272fcf063c077a639015f: apps/zcode-cli/packages/core/src/workflow/scheduler/node-runner.ts (Apache-2.0)
"""Execute one ready DAG node through the injected subagent runtime."""

from __future__ import annotations

from .prompts import build_node_context
from .types import NodeResult, SubagentRunner, WorkflowGraph, WorkflowNode


async def run_workflow_node(graph: WorkflowGraph, node: WorkflowNode, runner: SubagentRunner) -> NodeResult:
    """Run a node with dependency outputs and explicit workspace / model routing."""
    return await runner.run(
        goal=node.goal,
        context=build_node_context(graph, node),
        workspace=node.workspace or graph.workspace,
        model=node.model or graph.model,
    )
