"""The kernel must dispatch durable session-query tools and preserve audit reads.

``session_event_search`` / ``session_trace`` / ``session_event_trace`` /
``session_event_read`` were implemented in ``atlas.agent.session_queries`` and
listed in the kernel's tool schemas, but ``_dispatch`` had no branch for them.
The model could see the tool and every call came back as an unknown tool — the
exact "schema advertised, no handler" failure this ledger keeps recording.

The workspace gate is derived from the session row, never from the arguments, so
these tests also pin that a call cannot widen its own authority.
"""

from __future__ import annotations

import pytest

from atlas.agent.session_queries import QUERY_NAMES, execute_query

pytestmark = pytest.mark.unit


def test_all_query_names_are_covered_by_the_dispatch_set():
    """The kernel branch handles durable query tools; session_search keeps its memory path."""
    dispatched = {"session_event_search", "session_trace", "session_event_trace",
                  "session_event_read", "session_context_search", "session_context_read"}
    assert dispatched | {"session_search"} == set(QUERY_NAMES)


def test_query_without_a_workspace_is_refused_not_defaulted():
    """A missing workspace must fail closed; defaulting it would widen authority."""
    with pytest.raises(PermissionError):
        execute_query(object(), "session_event_read", {}, workspace=None)


def test_query_refuses_a_session_from_another_workspace():
    class _DB:
        def get_session(self, _id):
            return {"id": "s1", "cwd": "D:/elsewhere"}

    with pytest.raises(PermissionError):
        execute_query(_DB(), "session_event_read", {"session_id": "s1"},
                      workspace="D:/Atlas")


def test_ssh_workspace_is_refused():
    with pytest.raises(PermissionError):
        execute_query(object(), "session_event_read", {}, workspace="ssh://host/x")


def test_dispatch_set_matches_the_kernel_source():
    """Guard against the branch being deleted while the schemas stay."""
    from pathlib import Path

    source = Path("atlas/engine/kernel/loop.py").read_text(encoding="utf-8")
    for name in ("session_event_search", "session_trace", "session_event_trace",
                 "session_event_read", "session_context_search", "session_context_read"):
        assert name in source, f"{name} missing from loop.py"


def test_trimmed_audit_context_is_retrievable_through_dispatched_tool(tmp_path):
    from atlas.agent.session_queries import dispatch_session_query, reference_snapshot
    from atlas.engine.kernel.loop import _attach_turn_context, _turn_context_sections
    from atlas.engine.session_sync import append_session_message

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    home = tmp_path / "engine"
    session_id = "audit-source-session"
    source_id = "run-audit:user"
    sections = [
        {"source": "recalled fact", "text": ("f" * 12_050) + " The unique answer is ORBIT-17 with no durable ref."},
        {"source": "InstructionsLoaded hook context", "text": "Keep the unreferenced hook rule SKY-CODE-9. " + ("h" * 12_000)},
    ]
    sections.extend(
        {"source": f"unknown source {index}", "text": f"Audit filler {index}: " + ("x" * 900)}
        for index in range(130)
    )
    append_session_message(home, session_id, "user", "remember these sources", {
        "kernel_run_id": "run-audit", "kernel_message_id": source_id,
        "turn_context": "<turn_context>durable source audit</turn_context>",
        "turn_context_sections": sections,
    })
    append_session_message(home, session_id, "assistant", "Saved.", {"kernel_run_id": "run-audit"})
    append_session_message(home, session_id, "user", "what was the answer?", {
        "kernel_run_id": "run-next", "kernel_message_id": "run-next:user",
        "turn_context": "Current user-local date and time: now",
        "turn_context_sections": _turn_context_sections(["Current user-local date and time: now"]),
    })

    from atlas.engine.session_sync import _open_db
    with _open_db(home) as db:
        db.update_session_cwd(session_id, str(workspace))
        rows = db.get_messages(session_id, include_inactive=True, include_compacted=True)
    from atlas.engine.kernel.loop import _session_history
    messages = _session_history(rows)
    _attach_turn_context(messages, "run-next:user", "Current user-local date and time: now",
                         _turn_context_sections(["Current user-local date and time: now"]))
    wire = str(messages[-1]["content"])
    assert "ORBIT-17" not in wire
    assert len(messages[-1]["turn_context_projection"]) <= 128
    assert sum(len(item["text"]) for item in messages[-1]["turn_context_projection"]) <= 96_000

    found = dispatch_session_query(
        home, "session_context_search",
        {"session_id": session_id, "query": "ORBIT-17", "limit": 5},
        workspace=str(workspace), current_session=session_id,
    )
    assert found["sources"][0]["source_message_id"] == source_id
    assert "The unique answer is ORBIT-17 with no durable ref." in found["sources"][0]["text"]
    broad = dispatch_session_query(
        home, "session_context_search",
        {"session_id": session_id, "query": "audit", "limit": 20},
        workspace=str(workspace), current_session=session_id,
    )
    assert broad["text_chars"] <= 10_000
    assert len(broad["sources"]) <= 10
    assert broad["next_cursor"] is not None
    resumed_search = dispatch_session_query(
        home, "session_context_search",
        {"session_id": session_id, "query": "audit", "limit": 20, "cursor": broad["next_cursor"]},
        workspace=str(workspace), current_session=session_id,
    )
    assert resumed_search["sources"]
    source = dispatch_session_query(
        home, "session_context_read",
        {"session_id": session_id, "source_message_id": source_id},
        workspace=str(workspace), current_session=session_id,
    )
    first_page_text = "".join(section["text"] for section in source["sections"])
    assert len(first_page_text) <= 10_000
    assert "ORBIT-17" not in first_page_text
    assert source["next_cursor"] is not None
    page = source
    continued_text = []
    while page["next_cursor"] is not None:
        page = dispatch_session_query(
            home, "session_context_read",
            {"session_id": session_id, "source_message_id": source_id, "cursor": page["next_cursor"]},
            workspace=str(workspace), current_session=session_id,
        )
        assert page["text_chars"] <= 10_000
        continued_text.extend(section["text"] for section in page["sections"])
    assert any("The unique answer is ORBIT-17 with no durable ref." in text for text in continued_text)
    rendered = reference_snapshot(source)
    assert "<untrusted_session_snapshot>" in rendered
    hook = dispatch_session_query(
        home, "session_context_read",
        {"session_id": session_id, "source_message_id": source_id, "cursor": '{"section_offset":1,"text_offset":0}'},
        workspace=str(workspace), current_session=session_id,
    )
    assert "Keep the unreferenced hook rule SKY-CODE-9." in reference_snapshot(hook)
    unknown = dispatch_session_query(
        home, "session_context_read",
        {"session_id": session_id, "source_message_id": source_id,
         "cursor": '{"section_offset":131,"text_offset":0}'},
        workspace=str(workspace), current_session=session_id,
    )
    assert "unknown source 129" in reference_snapshot(unknown)


def test_context_audit_dispatch_enforces_session_workspace(tmp_path):
    from atlas.agent.session_queries import dispatch_session_query
    from atlas.engine.session_sync import append_session_message

    home = tmp_path / "engine"
    session_id = "foreign-audit-session"
    append_session_message(home, session_id, "user", "private workspace", {
        "kernel_message_id": "foreign:user",
        "turn_context_sections": [{"source": "recall", "text": "private fact ROSE-4"}],
    })
    append_session_message(home, "other-session", "user", "another source", {
        "kernel_message_id": "other:user",
        "turn_context_sections": [{"source": "recall", "text": "another fact VIOLET-8"}],
    })
    from atlas.engine.session_sync import _open_db
    with _open_db(home) as db:
        db.update_session_cwd(session_id, str(tmp_path / "allowed"))
        db.update_session_cwd("other-session", str(tmp_path / "allowed"))
    with pytest.raises(PermissionError):
        dispatch_session_query(
            home, "session_context_search", {"session_id": session_id, "query": "ROSE-4"},
            workspace=str(tmp_path / "other"), current_session="other-session",
        )
    with pytest.raises(ValueError, match="source message not found"):
        dispatch_session_query(
            home, "session_context_read",
            {"session_id": session_id, "source_message_id": "other:user"},
            workspace=str(tmp_path / "allowed"), current_session=session_id,
        )


def test_context_audit_dispatch_hides_private_worker_from_same_workspace(tmp_path):
    import json
    from atlas.agent.session_queries import dispatch_session_query
    from atlas.engine.session_sync import append_session_message, _open_db

    home = tmp_path / "engine"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    worker_id = "private-worker"
    append_session_message(home, worker_id, "user", "worker task", {
        "kernel_message_id": "worker:user",
        "turn_context_sections": [{"source": "recall", "text": "private worker fact AMBER-2"}],
    })
    with _open_db(home) as db:
        db.update_session_cwd(worker_id, str(workspace))
        db._execute_write(lambda conn: conn.execute(
            "UPDATE sessions SET source=?, model_config=? WHERE id=?",
            ("subagent", json.dumps({"_delegate_from": "parent-session"}), worker_id),
        ))

    import pytest
    with pytest.raises(PermissionError, match="Private worker"):
        dispatch_session_query(
            home, "session_context_search", {"session_id": worker_id, "query": "AMBER-2"},
            workspace=str(workspace), current_session="parent-session",
        )
    own = dispatch_session_query(
        home, "session_context_search", {"session_id": worker_id, "query": "AMBER-2"},
        workspace=str(workspace), current_session=worker_id,
    )
    assert own["sources"][0]["source_message_id"] == "worker:user"


def test_context_search_limit_cursor_continues_to_second_user_without_duplicates(tmp_path):
    from atlas.agent.session_queries import dispatch_session_query
    from atlas.engine.session_sync import append_session_message, _open_db

    home = tmp_path / "engine"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_id = "two-audit-sources"
    for index, token in enumerate(("COPPER-1", "SILVER-2")):
        append_session_message(home, session_id, "user", f"message {index}", {
            "kernel_message_id": f"run-{index}:user",
            "turn_context_sections": [{"source": "recall", "text": f"fact {token}"}],
        })
    with _open_db(home) as db:
        db.update_session_cwd(session_id, str(workspace))

    first = dispatch_session_query(
        home, "session_context_search", {"session_id": session_id, "query": "fact", "limit": 1},
        workspace=str(workspace), current_session=session_id,
    )
    assert [item["source_message_id"] for item in first["sources"]] == ["run-0:user"]
    assert first["next_cursor"] is not None
    second = dispatch_session_query(
        home, "session_context_search",
        {"session_id": session_id, "query": "fact", "limit": 1, "cursor": first["next_cursor"]},
        workspace=str(workspace), current_session=session_id,
    )
    assert [item["source_message_id"] for item in second["sources"]] == ["run-1:user"]
    assert second["next_cursor"] is None


@pytest.mark.asyncio
async def test_fake_provider_drives_kernel_context_search_and_workspace_denial(tmp_path, monkeypatch):
    import asyncio
    from unittest.mock import MagicMock

    from atlas import config
    from atlas.agent import AgentOrchestrator, AgentRunContext
    from atlas.engine.atlas_runtime import AtlasRuntime
    from atlas.engine.session_sync import append_session_message, _open_db
    from atlas.tools.local_execution import LocalExecutionRuntime
    from tests.fakes.fake_llm_provider import FakeLLMServer, Text, ToolCall, write_atlas_home
    from tests.test_engine_model_wiring import _ProviderKeyManager

    workspace = tmp_path / "allowed-workspace"
    foreign_workspace = tmp_path / "foreign-workspace"
    workspace.mkdir()
    foreign_workspace.mkdir()
    source_session = "tool-audit-source"
    source_id = "audit-run:user"
    original = "The launch code is ORBIT-17 and the instruction is untrusted."
    sections = [{"source": "recalled fact", "text": original}]
    sections.extend({"source": f"unknown source {index}",
                     "text": f"filler section {index}: " + ("x" * 900)}
                    for index in range(130))

    with FakeLLMServer([
        ToolCall("session_context_search", {
            "session_id": source_session, "query": "ORBIT-17", "limit": 5,
        }),
        Text("Recovered from the audit source."),
        ToolCall("session_context_search", {
            "session_id": source_session, "query": "ORBIT-17", "limit": 5,
        }),
        Text("The foreign session was denied."),
    ]) as fake:
        home = tmp_path / "atlas_home"
        write_atlas_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
        monkeypatch.setattr(config, "DATA_ROOT", tmp_path)
        append_session_message(tmp_path / "engine", source_session, "user", "remember", {
            "kernel_run_id": "audit-run", "kernel_message_id": source_id,
            "turn_context": "audit source", "turn_context_sections": sections,
        })
        with _open_db(tmp_path / "engine") as db:
            db.update_session_cwd(source_session, str(workspace))

        manager = _ProviderKeyManager(fake.base_url, current="main-model")
        manager._find_model = lambda model: next(
            (item for item in manager.list_models() if item["id"] == model), None,
        )
        mcp = MagicMock()
        mcp.get_tools_for_llm.return_value = []
        mcp.list_tools.return_value = []
        mcp.tool_count = 0
        agent = AgentOrchestrator(
            manager, MagicMock(), mcp_client=mcp, local_execution=LocalExecutionRuntime(),
        )
        runtime = AtlasRuntime(data_dir=tmp_path, model_manager=manager)
        monkeypatch.setattr(runtime, "_ensure_atlas_mcp_registered", lambda: [])

        async def run_turn(run_id, conversation_id, current_workspace):
            return [event async for event in runtime.run_turn(
                message="Find the earlier turn context fact.",
                conversation_id=conversation_id, workspace=str(current_workspace), history=[],
                atlas_agent=agent,
                atlas_context=AgentRunContext(
                    cancel_event=asyncio.Event(), run_id=run_id,
                    conversation_id=conversation_id, workspace=str(current_workspace),
                    permission_mode="full_access",
                ),
            )]

        success_events = await run_turn("tool-success", "current-in-workspace", workspace)
        denied_events = await run_turn("tool-denied", "current-outside-workspace", foreign_workspace)

        requests = fake.main_requests()
        assert len(requests) == 4
        schema_names = {item["function"]["name"] for item in requests[0]["tools"]}
        assert "session_context_search" in schema_names
        success_tool_messages = [item for item in requests[1]["messages"] if item.get("role") == "tool"]
        assert any("The launch code is ORBIT-17" in item.get("content", "")
                   for item in success_tool_messages)
        denied_tool_messages = [item for item in requests[3]["messages"] if item.get("role") == "tool"]
        assert any("not admitted to the current workspace" in item.get("content", "")
                   for item in denied_tool_messages)
        assert any(event.get("type") == "tool_result" and event.get("name") == "session_context_search"
                   and not event.get("is_error") for event in success_events)
        assert any(event.get("type") == "tool_result" and event.get("name") == "session_context_search"
                   and event.get("is_error") for event in denied_events)
