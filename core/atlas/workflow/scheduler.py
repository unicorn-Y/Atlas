# Ported from zai-org/ZCode@aac4755666d09fdcd70272fcf063c077a639015f: apps/zcode-cli/packages/core/src/workflow/scheduler.ts (Apache-2.0)
# Collection scheduling thresholds follow apps/zcode-cli/packages/core/src/workflow/scheduler/collection-planner.ts at the same commit.
"""Bounded DAG scheduling with durable events, retries, pause, and resume."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from .events import emit_event
from .graph import blocked_nodes, ordered_ready_nodes, validate_graph
from .journal import WorkflowJournal
from .lifecycle import activate_node, fail_node, reconcile_for_resume
from .node_runner import run_workflow_node
from .planner import PlannerCallback, expand_collection
from .types import NodeResult, SubagentRunner, WorkflowGraph, WorkflowNode, WorkflowResult


async def run_workflow(
    graph: WorkflowGraph,
    runner: SubagentRunner,
    *,
    max_parallel: int,
    on_event: Callable[[dict[str, Any]], Any],
    planner: PlannerCallback | None = None,
    journal: WorkflowJournal | None = None,
    _resume: bool = False,
) -> WorkflowResult:
    """Run a DAG and always stop owned node tasks when the scheduler exits early."""
    active: dict[str, asyncio.Task[tuple[float, NodeResult | None, Exception | None]]] = {}
    try:
        return await _run_workflow_impl(
            graph,
            runner,
            max_parallel=max_parallel,
            on_event=on_event,
            planner=planner,
            journal=journal,
            _resume=_resume,
            _active=active,
        )
    except BaseException:
        tasks = list(active.values())
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        raise


async def _run_workflow_impl(
    graph: WorkflowGraph,
    runner: SubagentRunner,
    *,
    max_parallel: int,
    on_event: Callable[[dict[str, Any]], Any],
    planner: PlannerCallback | None,
    journal: WorkflowJournal | None,
    _resume: bool,
    _active: dict[str, asyncio.Task[tuple[float, NodeResult | None, Exception | None]]] | None = None,
) -> WorkflowResult:
    """Run or resume a DAG, persisting every transition in the dedicated SQLite journal.

    ``max_parallel`` is supplied by the caller for each run. Nodes run through the injected
    ``SubagentRunner`` and planner model calls use only the optional callback.
    """
    if not isinstance(max_parallel, int) or isinstance(max_parallel, bool) or max_parallel < 1:
        raise ValueError("max_parallel must be at least 1")
    if not graph.workflow_id:
        graph.workflow_id = str(uuid4())
    validate_graph(graph)
    journal = journal or WorkflowJournal()
    current, prior_status, pause_requested, created = journal.ensure_graph(graph, resume=_resume)
    if prior_status in {"completed", "failed", "cancelled"}:
        return WorkflowResult(current.workflow_id or "", prior_status, current)
    if pause_requested:
        journal.clear_pause_request(current.workflow_id or "")

    if created:
        await emit_event(journal, current, on_event, "workflow_started", message="Workflow started.", status="running")
    else:
        repaired = reconcile_for_resume(current)
        await emit_event(
            journal,
            current,
            on_event,
            "workflow_resumed",
            message="Workflow resumed from its journal." if not repaired else "Workflow resumed; interrupted active nodes were reset to pending.",
            payload={"repaired_node_ids": repaired},
            status="running",
        )

    active = _active if _active is not None else {}
    consecutive_failures = 0
    threshold_reached = False

    while True:
        if journal.cancel_requested(current.workflow_id or ""):
            for task in active.values():
                if not task.done():
                    task.cancel()
            if active:
                await asyncio.gather(*active.values(), return_exceptions=True)
            active.clear()
            for node in current.nodes:
                if node.status == "active":
                    node.status = "cancelled"
            await emit_event(journal, current, on_event, "workflow_cancelled", message="Workflow stopped by user.", status="cancelled")
            return WorkflowResult(current.workflow_id or "", "cancelled", current)
        pause_now = journal.pause_requested(current.workflow_id or "")
        if pause_now or threshold_reached:
            if active:
                await _collect_completed(active, current, journal, on_event)
                continue
            reason = "requested" if pause_now else "failure_threshold"
            return await _pause_result(current, journal, on_event, reason)

        planners_ran = 0
        if planner is not None:
            planners_ran = await _advance_collections(current, planner, journal, on_event)

        if journal.pause_requested(current.workflow_id or ""):
            if active:
                await _collect_completed(active, current, journal, on_event)
                continue
            return await _pause_result(current, journal, on_event, "requested")

        if _all_settled(current) and _collections_exhausted(current, planner is not None):
            final_status = "failed" if any(node.status == "failed" for node in current.nodes) else "completed"
            await emit_event(
                journal,
                current,
                on_event,
                "workflow_completed",
                message="Workflow graph reached a terminal state.",
                payload={"status": final_status, "failed_node_ids": [node.id for node in current.nodes if node.status == "failed"]},
                status=final_status,
            )
            return WorkflowResult(current.workflow_id or "", final_status, current)

        ready = ordered_ready_nodes(current)
        if planners_ran and not ready and not active and not _all_settled(current):
            continue
        if planners_ran and _all_settled(current) and not _collections_exhausted(current, planner is not None):
            continue
        dispatched = 0
        for node in ready:
            if len(active) >= max_parallel:
                break
            activate_node(node)
            await emit_event(
                journal,
                current,
                on_event,
                "node_started",
                node_id=node.id,
                message=f"Node started: {node.title or node.id}",
                payload={"attempt": node.attempts + 1, "owner": node.owner, "files": node.files},
                status="running",
            )
            active[node.id] = asyncio.create_task(_run_node(current, node, runner))
            dispatched += 1
        if dispatched:
            continue

        if active:
            outcomes = await _collect_completed(active, current, journal, on_event)
            for _, success in outcomes:
                consecutive_failures = 0 if success else consecutive_failures + 1
                if consecutive_failures >= current.failure_threshold:
                    threshold_reached = True
            continue

        # No node can progress and collection expansion did not add work: retain the graph
        # for explicit resume and expose the blocked frontier in the event journal.
        await emit_event(
            journal,
            current,
            on_event,
            "workflow_paused",
            message="Workflow paused because pending nodes are blocked or the graph is deadlocked.",
            payload={"reason": "deadlock", "blocked_nodes": blocked_nodes(current)},
            status="paused",
        )
        return WorkflowResult(current.workflow_id or "", "paused", current, "Workflow graph is deadlocked.")


def pause_workflow(workflow_id: str, *, journal: WorkflowJournal | None = None) -> None:
    """Request a cooperative pause; in-flight nodes settle before the graph is paused."""
    (journal or WorkflowJournal()).request_pause(workflow_id)


async def resume_workflow(
    workflow_id: str,
    runner: SubagentRunner,
    *,
    max_parallel: int,
    on_event: Callable[[dict[str, Any]], Any],
    planner: PlannerCallback | None = None,
    journal: WorkflowJournal | None = None,
) -> WorkflowResult:
    """Load a journaled graph and continue it through the same scheduler entry point."""
    store = journal or WorkflowJournal()
    graph = store.load_graph(workflow_id)
    store.clear_pause_request(workflow_id)
    return await run_workflow(
        graph,
        runner,
        max_parallel=max_parallel,
        on_event=on_event,
        planner=planner,
        journal=store,
        _resume=True,
    )


async def _collect_completed(
    active: dict[str, asyncio.Task[tuple[float, NodeResult | None, Exception | None]]],
    graph: WorkflowGraph,
    journal: WorkflowJournal,
    on_event: Callable[[dict[str, Any]], Any],
) -> list[tuple[str, bool]]:
    done, _ = await asyncio.wait(active.values(), return_when=asyncio.FIRST_COMPLETED)
    outcomes: list[tuple[str, bool]] = []
    node_by_id = {node.id: node for node in graph.nodes}
    for task in sorted(done, key=lambda item: item.result()[0]):
        node_id = next(key for key, value in active.items() if value is task)
        del active[node_id]
        node = node_by_id[node_id]
        try:
            _, result, error = task.result()
            if error is not None:
                raise error
            if result is None:
                raise RuntimeError("Subagent runner returned no node result")
        except Exception as exc:
            retry = fail_node(graph, node, str(exc) or exc.__class__.__name__)
            await emit_event(
                journal,
                graph,
                on_event,
                "node_failed",
                node_id=node.id,
                message=node.error or "Node failed.",
                payload={"attempt": node.attempts, "retry": retry},
                status="running",
            )
            outcomes.append((node_id, False))
        else:
            node.status = "completed"
            node.error = None
            node.output = result.response
            node.metadata = dict(result.metadata or {})
            await emit_event(
                journal,
                graph,
                on_event,
                "node_completed",
                node_id=node.id,
                message=f"Node completed: {node.title or node.id}",
                payload={"model": result.model, "metadata": node.metadata},
                status="running",
            )
            outcomes.append((node_id, True))
    return outcomes


async def _run_node(
    graph: WorkflowGraph,
    node: WorkflowNode,
    runner: SubagentRunner,
) -> tuple[float, NodeResult | None, Exception | None]:
    loop = asyncio.get_running_loop()
    try:
        return loop.time(), await run_workflow_node(graph, node, runner), None
    except Exception as exc:
        return loop.time(), None, exc


async def _advance_collections(
    graph: WorkflowGraph,
    planner: PlannerCallback,
    journal: WorkflowJournal,
    on_event: Callable[[dict[str, Any]], Any],
) -> int:
    from .graph import collection_frontier, collection_node_ids

    by_id = {node.id: node for node in graph.nodes}
    planners_ran = 0
    for collection in graph.collections:
        if not collection.explorable or collection.exhausted or collection.status == "exhausted":
            continue
        node_ids = collection_node_ids(graph, collection)
        frontier = collection_frontier(graph, collection)
        unseen = [
            node_id for node_id in node_ids
            if node_id in by_id and by_id[node_id].status == "completed" and node_id not in collection.analyzed_node_ids
        ]
        if frontier > 0 and collection.planner_runs == 0 and not collection.analyzed_node_ids and not unseen:
            collection.status = "active"
            continue
        if frontier >= collection.frontier_target and not unseen:
            collection.status = "active"
            continue
        if collection.planner_runs >= collection.max_planner_runs or collection.error_count >= collection.max_consecutive_errors:
            collection.exhausted = True
            collection.status = "exhausted"
            await emit_event(
                journal,
                graph,
                on_event,
                "collection_exhausted",
                payload={"collection_id": collection.collection_id, "reason": "planner_limit" if collection.planner_runs >= collection.max_planner_runs else "planner_error_threshold"},
            )
            continue

        collection.planner_runs += 1
        planners_ran += 1
        await emit_event(
            journal,
            graph,
            on_event,
            "planner_started",
            payload={"collection_id": collection.collection_id, "frontier": frontier, "planner_runs": collection.planner_runs, "unseen_completions": unseen},
        )
        try:
            added_ids = await expand_collection(
                graph,
                collection,
                call_model=planner,
                unseen_completions=unseen,
            )
        except Exception as exc:
            collection.error_count += 1
            collection.exhausted = collection.error_count >= collection.max_consecutive_errors
            collection.status = "exhausted" if collection.exhausted else "draining"
            await emit_event(
                journal,
                graph,
                on_event,
                "planner_failed",
                message=str(exc),
                payload={"collection_id": collection.collection_id, "error_count": collection.error_count, "exhausted": collection.exhausted},
            )
            continue
        await emit_event(
            journal,
            graph,
            on_event,
            "planner_completed",
            payload={"collection_id": collection.collection_id, "added_node_ids": added_ids, "node_count": len(added_ids)},
        )
    return planners_ran


def _all_settled(graph: WorkflowGraph) -> bool:
    return all(node.status in {"completed", "failed", "skipped", "cancelled"} for node in graph.nodes)


def _collections_exhausted(graph: WorkflowGraph, has_planner: bool) -> bool:
    if not has_planner:
        return True
    return all(not collection.explorable or collection.exhausted or collection.status == "exhausted" for collection in graph.collections)


async def _pause_result(
    graph: WorkflowGraph,
    journal: WorkflowJournal,
    on_event: Callable[[dict[str, Any]], Any],
    reason: str,
) -> WorkflowResult:
    await emit_event(
        journal,
        graph,
        on_event,
        "workflow_paused",
        message="Workflow paused after active nodes settled.",
        payload={"reason": reason},
        status="paused",
    )
    return WorkflowResult(graph.workflow_id or "", "paused", graph)
