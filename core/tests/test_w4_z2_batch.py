"""WAVE4 Z2 batch unit coverage: token anchoring (E29), session query
classification (E31), worktree pinned revision (E32), compaction orphan
detection (E35)."""
from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.unit


# --- E29: provider usage anchored back to surface nodes -------------------

def _nodes() -> list[dict[str, int]]:
    return [{"seq": 0, "tokens": 1000}, {"seq": 1, "tokens": 3000}]


def test_anchor_scales_nodes_to_provider_total():
    from atlas.engine.agent.token_meter import anchor_surface_to_usage

    anchor = anchor_surface_to_usage(
        surface_nodes=_nodes(), surface_tokens=4000,
        provider_input_tokens=8000, request_sha256="abc123",
    )
    assert anchor is not None
    assert anchor["anchored"] is True
    assert anchor["request_sha256"] == "abc123"
    assert anchor["anchor_ratio"] == 2.0
    priced = anchor["surface_node_tokens_anchored"]
    assert [node["anchored_tokens"] for node in priced] == [2000, 6000]
    assert sum(node["anchored_tokens"] for node in priced) == 8000
    assert [node["heuristic_tokens"] for node in priced] == [1000, 3000]


def test_anchor_returns_none_without_usage_or_nodes():
    from atlas.engine.agent.token_meter import anchor_surface_to_usage

    assert anchor_surface_to_usage(
        surface_nodes=_nodes(), surface_tokens=4000, provider_input_tokens=0,
    ) is None
    assert anchor_surface_to_usage(
        surface_nodes=[], surface_tokens=0, provider_input_tokens=100,
    ) is None
    assert anchor_surface_to_usage(
        surface_nodes=[{"seq": 0}], surface_tokens=0, provider_input_tokens=100,
    ) is None


def test_anchor_does_not_mutate_input_nodes():
    from atlas.engine.agent.token_meter import anchor_surface_to_usage

    nodes = _nodes()
    anchor_surface_to_usage(
        surface_nodes=nodes, surface_tokens=4000, provider_input_tokens=1000,
    )
    assert nodes == [{"seq": 0, "tokens": 1000}, {"seq": 1, "tokens": 3000}]


# --- E31: kernel classifies the durable session reads as read-only --------

SESSION_QUERY_TOOLS = {
    "session_event_search", "session_trace", "session_event_trace", "session_event_read",
}


def test_session_query_tools_are_kernel_read_only_and_read_family():
    from atlas.engine.kernel.tools import READ_ONLY_TOOLS, tool_timeout_family
    from atlas.engine.kernel.loop import _plan_mode_denies

    assert SESSION_QUERY_TOOLS <= READ_ONLY_TOOLS
    assert {tool_timeout_family(name) for name in SESSION_QUERY_TOOLS} == {"read"}
    runtime = SimpleNamespace(dynamic_plan_mode=True, mode="act")
    assert not any(_plan_mode_denies(runtime, name) for name in SESSION_QUERY_TOOLS)


def test_scheduler_overlaps_session_queries_like_session_search():
    from atlas.engine.kernel.tools import ToolScheduler

    scheduler = ToolScheduler(dispatch=None)  # classification only
    call = {"id": "c1", "function": {"name": "session_event_read",
                                     "arguments": '{"session_id": "s", "seq": 1}'}}
    assert scheduler.supports_parallel(call) is True


def test_query_tool_schemas_are_offered_and_match_kernel_names():
    from atlas.agent.session_queries import query_tools

    offered = {item["function"]["name"] for item in query_tools()}
    assert offered == SESSION_QUERY_TOOLS
    for item in query_tools():
        parameters = item["function"]["parameters"]
        assert parameters["required"], item["function"]["name"]
        assert parameters["additionalProperties"] is False


# --- E32: worktree creation from a pinned revision -------------------------

def _git(root, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _init_repo(root) -> str:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "w4z2@example.invalid")
    _git(root, "config", "user.name", "w4z2")
    (root / "marker.txt").write_text("pinned revision content\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "pinned base")
    sha = _git(root, "rev-parse", "HEAD")
    (root / "after.txt").write_text("later commit\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "later")
    return sha


def test_worktree_service_creates_from_pinned_commit(tmp_path):
    from atlas.task_artifacts import WorktreeService

    repo = tmp_path / "repo"
    pinned = _init_repo(repo)
    service = WorktreeService(tmp_path / "services")
    created = service.create(repo, "conv-pin-1234", pinned, "pin")
    worktree = created["worktree_path"]
    assert _git(repo, "rev-parse", "HEAD") != pinned  # base moved on
    assert _git(worktree, "rev-parse", "HEAD") == pinned
    assert (Path(worktree) / "marker.txt").read_text(encoding="utf-8").startswith("pinned")
    assert created["worktree_branch"].startswith("atlas/")


def test_worktree_schema_documents_pinned_revision_and_in_run_use():
    from atlas.tools.workspace_workflows import workspace_workflow_schemas

    schema = next(item for item in workspace_workflow_schemas()
                  if item["function"]["name"] == "workspace_worktree_manage")
    description = schema["function"]["description"]
    assert "commit SHA" in description
    assert "same run" in description
    assert "commit SHA" in schema["function"]["parameters"]["properties"]["base_branch"]["description"]


# --- E31b: kernel runs stamp the session workspace so admission passes -----

def test_ensure_session_workspace_fills_null_and_never_clobbers(tmp_path):
    from atlas.engine.session_sync import ensure_session_workspace
    from atlas.engine.state.atlas_state import SessionDB

    workspace = str(tmp_path)
    ensure_session_workspace(tmp_path, "s-ws", workspace)
    with SessionDB(db_path=tmp_path / "state.db") as db:
        row = db.get_session("s-ws")
    assert row is not None
    assert str(row.get("cwd")).casefold() == workspace.casefold()

    with SessionDB(db_path=tmp_path / "state.db") as db:
        db._execute_write(lambda conn: conn.execute(
            "UPDATE sessions SET cwd = ? WHERE id = ?", (r"D:\elsewhere", "s-ws"),
        ))
    ensure_session_workspace(tmp_path, "s-ws", workspace)
    with SessionDB(db_path=tmp_path / "state.db") as db:
        assert db.get_session("s-ws")["cwd"] == r"D:\elsewhere"


def test_ensure_session_workspace_skips_ssh_and_empty():
    from atlas.engine.session_sync import ensure_session_workspace

    # Must not raise and must not touch any store for these inputs.
    ensure_session_workspace("/nonexistent-home", "s", "ssh://user@host/repo")
    ensure_session_workspace("/nonexistent-home", "", "D:\\nowhere")
    ensure_session_workspace("/nonexistent-home", "s", "")


def test_execute_query_admits_session_stamped_by_run_start(tmp_path):
    from atlas.agent.session_queries import execute_query
    from atlas.engine.session_sync import ensure_session_workspace
    from atlas.engine.state.atlas_state import SessionDB

    workspace = str(tmp_path)
    ensure_session_workspace(tmp_path, "s-admit", workspace)
    with SessionDB(db_path=tmp_path / "state.db") as db:
        db.append_session_event("s-admit", "turn/start", {"turn_id": "t1"})
        payload = execute_query(db, "session_event_read",
                                {"session_id": "s-admit", "seq": 1},
                                workspace=workspace, current_session="s-admit")
    assert payload["event"]["event_type"] == "turn/start"


# --- E35: durable compaction brackets are orphan-detectable ----------------

def test_orphan_detection_reports_start_without_end(tmp_path):
    from atlas.engine.session_sync import (
        append_session_message,
        begin_session_compaction,
        detect_orphaned_compactions,
    )
    from atlas.engine.state.atlas_state import SessionDB

    append_session_message(tmp_path, "s", "user", "before compaction")
    holder = "atlas:run-crash:abc"
    watermark = begin_session_compaction(tmp_path, "s", holder)
    orphans = detect_orphaned_compactions(tmp_path, "s")
    assert len(orphans) == 1
    assert orphans[0]["holder"] == holder
    assert orphans[0]["watermark"] == watermark

    with SessionDB(db_path=tmp_path / "state.db") as db:
        db.append_session_event("s", "compaction/end",
                                {"holder": holder, "reason": "completed"})
    assert detect_orphaned_compactions(tmp_path, "s") == []


def test_orphan_detection_ignores_aborted_and_completed_brackets(tmp_path):
    from atlas.engine.session_sync import (
        abort_session_compaction,
        append_session_message,
        begin_session_compaction,
        detect_orphaned_compactions,
    )

    append_session_message(tmp_path, "s", "user", "content")
    holder = "atlas:run-abort:def"
    begin_session_compaction(tmp_path, "s", holder)
    abort_session_compaction(tmp_path, "s", holder)
    assert detect_orphaned_compactions(tmp_path, "s") == []


def test_kernel_records_journal_brackets_around_compaction_keywords():
    """The loop records compaction_start before publication and compaction_end
    after it; assert the record sites exist so a journal bracket pair is
    actually emitted (the live run is the durable evidence)."""
    import inspect

    from atlas.engine.kernel import loop as kernel_loop

    source = inspect.getsource(kernel_loop)
    assert 'record("compaction_start"' in source
    assert source.count('record("compaction_end"') >= 2
    assert 'record("compaction_end", holder=holder, reason="completed"' in source
