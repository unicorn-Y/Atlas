# Ported from zai-org/ZCode@29628c9acdb81b703bbd4080c207a0e7ce5e276e: apps/zcode-cli/packages/core/src/workflow/scheduler/types.ts (Apache-2.0)
"""Public data contracts for Atlas's standalone DAG workflow runner."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TypedDict


NodeStatus = Literal["pending", "active", "completed", "failed", "skipped", "cancelled"]
WorkflowStatus = Literal["running", "paused", "completed", "failed", "cancelled"]


@dataclass
class WorkflowNode:
    """One independently executable task and its dependency / ownership scope."""

    id: str
    goal: str
    title: str = ""
    depends_on: list[str] = field(default_factory=list)
    owner: str | None = None
    files: list[str] = field(default_factory=list)
    description: str | None = None
    prompt: str | None = None
    context: str = ""
    workspace: str | None = None
    model: str | None = None
    max_attempts: int | None = None
    attempts: int = 0
    status: NodeStatus = "pending"
    error: str | None = None
    output: str | None = None
    collection_id: str | None = None


@dataclass
class WorkflowEdge:
    """A directed dependency edge: ``from_node`` must settle before ``to_node``."""

    from_node: str
    to_node: str


@dataclass
class WorkflowCollection:
    """Planner-managed node group; expansion runs when its frontier has room."""

    collection_id: str
    goal: str
    node_ids: list[str] = field(default_factory=list)
    explorable: bool = True
    frontier_target: int = 3
    max_planner_runs: int = 10
    max_consecutive_errors: int = 3
    planner_runs: int = 0
    error_count: int = 0
    analyzed_node_ids: list[str] = field(default_factory=list)
    exhausted: bool = False
    status: Literal["active", "draining", "exhausted"] = "active"


@dataclass
class WorkflowGraph:
    """A durable task DAG. ``workflow_id`` identifies its journaled execution."""

    goal: str
    nodes: list[WorkflowNode]
    workspace: str
    edges: list[WorkflowEdge] = field(default_factory=list)
    workflow_id: str | None = None
    model: str | None = None
    max_attempts: int = 3
    failure_threshold: int = 3
    collections: list[WorkflowCollection] = field(default_factory=list)


@dataclass
class NodeResult:
    """The output returned by a subagent for one task node."""

    response: str
    model: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class SubagentRunner(Protocol):
    """Adapter for the host's subagent runtime; workflow code does not own models."""

    async def run(
        self,
        *,
        goal: str,
        context: str,
        workspace: str,
        model: str | None,
    ) -> NodeResult: ...


class WorkflowEvent(TypedDict, total=False):
    """Append-only event shape delivered to the journal and ``on_event`` callback."""

    workflow_id: str
    timestamp: str
    type: str
    node_id: str
    phase: str
    message: str
    payload: dict[str, Any]


@dataclass
class WorkflowResult:
    """Final or paused workflow state, including the replayable graph snapshot."""

    workflow_id: str
    status: WorkflowStatus
    graph: WorkflowGraph
    error: str | None = None

