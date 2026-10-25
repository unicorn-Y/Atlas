from __future__ import annotations

import asyncio

from atlas.workflow.journal import WorkflowJournal
from atlas.workflow.scheduler import run_workflow
from atlas.workflow.types import NodeResult, WorkflowGraph, WorkflowNode


def test_current_conversation_workflow_context_and_independent_expert_flag(tmp_path):
    journal = WorkflowJournal(tmp_path / "workflow.db")
    graph = WorkflowGraph("demo", [WorkflowNode("n1", "do it")], str(tmp_path), workflow_id="run-1")
    journal.ensure_graph(graph)
    journal.bind_context("run-1", "conversation-1", kind="expert")
    assert journal.current_for_conversation("conversation-1", kind="expert") == {
        "workflow_id": "run-1", "status": "running", "kind": "expert",
    }
    # This lifecycle association is independent of the separately persisted ExpertMode toggle.
    assert journal.current_for_conversation("conversation-2", kind="expert") is None


def test_stop_cancels_active_nodes_and_records_terminal_state(tmp_path):
    journal = WorkflowJournal(tmp_path / "workflow.db")
    graph = WorkflowGraph("demo", [WorkflowNode("n1", "wait")], str(tmp_path), workflow_id="run-2")
    ready = asyncio.Event()

    class Runner:
        async def run(self, **_kwargs):
            ready.set()
            await asyncio.Event().wait()
            return NodeResult("unreachable")

    async def scenario():
        async def on_event(event):
            if event["type"] == "node_started":
                await asyncio.to_thread(journal.request_cancel, "run-2")

        result = await run_workflow(graph, Runner(), max_parallel=1, on_event=on_event, journal=journal)
        assert result.status == "cancelled"
        assert result.graph.nodes[0].status == "cancelled"

    asyncio.run(scenario())
    assert journal.status("run-2") == "cancelled"
    assert journal.events("run-2")[-1]["type"] == "workflow_cancelled"
