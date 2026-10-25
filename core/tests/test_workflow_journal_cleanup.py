from __future__ import annotations

from atlas.workflow.journal import WorkflowJournal
from atlas.workflow.types import WorkflowGraph, WorkflowNode


def test_workflow_journal_releases_sqlite_file_after_each_operation(tmp_path):
    path = tmp_path / "workflow.db"
    journal = WorkflowJournal(path)
    graph = WorkflowGraph("cleanup", [WorkflowNode("n1", "run")], str(tmp_path),
                          workflow_id="cleanup-run")
    journal.ensure_graph(graph)
    journal.list_runs()

    # Windows refuses to delete a database while any connection still owns it.
    path.unlink()
    assert not path.exists()
