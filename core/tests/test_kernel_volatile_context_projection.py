from __future__ import annotations

import asyncio
import copy
import json
from unittest.mock import MagicMock

import pytest

from atlas.engine.atlas_runtime import AtlasRuntime
from atlas.agent import AgentOrchestrator, AgentRunContext
from atlas.engine.kernel.loop import _attach_turn_context, _turn_context_block
from atlas.tools.local_execution import LocalExecutionRuntime
from atlas.engine.kernel.loop import _turn_context_block, _turn_context_sections
from tests.fakes.fake_llm_provider import FakeLLMServer, Text, write_atlas_home
from tests.test_engine_model_wiring import _ProviderKeyManager

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_multiturn_wire_projects_sources_and_reads_kernel_persisted_audit(tmp_path, monkeypatch):
    from atlas.engine.session_sync import read_session_all_messages

    conversation_id = "volatile-context-wire"
    contexts = [
        [
            "Current user-local date and time: 2026-11-15T10:00",
            "Current permission mode: read-only",
            "Atlas Skill index old-index",
            "【本轮动态上下文】\nFact: Atlas launch code is ORBIT-17 [ref:memory-ref-9]",
            "InstructionsLoaded hook context:\nPreserve the user's cited source reference.",
        ],
        [
            "Current user-local date and time: 2026-11-15T10:01",
            "Current permission mode: workspace-write",
            "Atlas Skill index middle-index",
        ],
        [
            "Current user-local date and time: 2026-11-15T10:02",
            "Current permission mode: read-only",
            "Atlas Skill index current-index",
        ],
        [
            "Current user-local date and time: 2026-11-15T10:03",
            "Current permission mode: read-only",
            "Atlas Skill index latest-index",
        ],
    ]
    prompts = [
        "Remember the launch code and source-ref:doc-a#section-2",
        "What launch code did I ask you to remember?",
        "Repeat the launch code and its memory reference.",
        "Repeat the launch code and its memory reference.",
    ]

    with FakeLLMServer([Text("ONE"), Text("TWO"), Text("THREE"), Text("THREE")]) as fake:
        home = tmp_path / "engine"
        write_atlas_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
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

        for index, (prompt, volatile_context) in enumerate(zip(prompts, contexts, strict=True)):
            context = AgentRunContext(
                cancel_event=asyncio.Event(), run_id=f"volatile-{index}",
                conversation_id=conversation_id, workspace=str(tmp_path),
                permission_mode="read_only" if index != 1 else "workspace_write",
            )
            user_content = (
                [
                    {"type": "text", "text": prompts[0]},
                    {"type": "image_url", "image_url": {"url": "attachment-ref:asset-a"}},
                ] if index == 0 else prompt
            )
            events = [event async for event in runtime.run_turn(
                message=prompt,
                user_content=user_content,
                conversation_id=conversation_id,
                workspace=str(tmp_path),
                history=[],
                volatile_context=volatile_context,
                atlas_agent=agent,
                atlas_context=context,
                ephemeral=False,
            )]
            assert any(event["type"] == "atlas.result" for event in events)

        requests = fake.main_requests()
        assert len(requests) == 4
        final_wire = requests[-1]["messages"]
        final_wire_json = json.dumps(final_wire, ensure_ascii=False)
        user_wire = [message for message in final_wire if message.get("role") == "user"]
        context_wire = [
            message for message in user_wire
            if "<turn_context>" in json.dumps(message.get("content"), ensure_ascii=False)
        ]
        outline = [
            {"role": message.get("role"), "content_chars": len(str(message.get("content") or ""))}
            for message in final_wire
        ]
        assert "2026-11-15T10:00" not in final_wire_json, outline
        assert "Current permission mode: workspace-write" not in final_wire_json, outline
        assert "Atlas Skill index middle-index" not in final_wire_json, outline
        assert "Atlas Skill index latest-index" in final_wire_json, outline
        assert "Atlas Skill index current-index" not in final_wire_json, outline
        assert "2026-11-15T10:03" in final_wire_json, outline
        assert "Current permission mode: read-only" in final_wire_json, outline
        assert "ORBIT-17" in final_wire_json, outline
        assert "memory-ref-9" in final_wire_json, outline
        assert "Preserve the user's cited source reference." in final_wire_json, outline
        assert "attachment-ref:asset-a" in final_wire_json, outline
        assert "source-ref:doc-a#section-2" in final_wire_json, outline
        assert len(user_wire) == 4, outline
        assert len(context_wire) == 1, outline

    persisted = read_session_all_messages(tmp_path / "engine", conversation_id)
    user_rows = [row for row in persisted if row["role"] == "user"]
    assert len(user_rows) == 4
    assert [row["metadata"]["kernel_run_id"] for row in user_rows] == [
        "volatile-0", "volatile-1", "volatile-2", "volatile-3",
    ]
    assert [row["metadata"]["turn_context"] for row in user_rows] == [
        _turn_context_block(context) for context in contexts
    ]
    assert [row["metadata"]["turn_context_sections"] for row in user_rows] == [
        _turn_context_sections(context) for context in contexts
    ]
    message_ids = [row["metadata"]["kernel_message_id"] for row in user_rows]
    assert all(message_ids) and len(set(message_ids)) == 4


@pytest.mark.asyncio
async def test_durable_next_turn_inbox_keeps_user_role_on_actual_model_wire(tmp_path, monkeypatch):
    from atlas.engine.kernel.inbox import DurableInbox

    conversation_id = "durable-inbox-user-source"
    with FakeLLMServer([Text("queued prompt observed")]) as fake:
        home = tmp_path / "engine"
        write_atlas_home(home, fake.base_url)
        monkeypatch.setenv("HERMES_HOME", str(home))
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
        inbox = DurableInbox(home, conversation_id)
        await inbox.inject("queued user-origin content", lane="next-turn", request_id="sdk-queued-1")
        await inbox.inject("queued next-step context", lane="next-step", request_id="sdk-step-1")
        context = AgentRunContext(
            cancel_event=asyncio.Event(), run_id="queued-inbox-run",
            conversation_id=conversation_id, workspace=str(tmp_path),
        )
        context.inbox = inbox

        events = [event async for event in runtime.run_turn(
            message="current prompt", conversation_id=conversation_id,
            workspace=str(tmp_path), history=[], volatile_context=[],
            atlas_agent=agent, atlas_context=context, ephemeral=False,
        )]
        assert any(event["type"] == "atlas.result" for event in events)

        requests = fake.main_requests()
        assert len(requests) == 1
        messages = requests[0]["messages"]
        next_turn = [message for message in messages if "[Durable next-turn injection]" in str(message.get("content"))]
        next_step = [message for message in messages if "[Durable next-step injection]" in str(message.get("content"))]
        assert len(next_turn) == 1
        assert next_turn[0]["role"] == "user"
        assert "queued user-origin content" in next_turn[0]["content"]
        assert len(next_step) == 1
        assert next_step[0]["role"] == "developer"


def test_current_context_uses_run_identity_for_duplicate_prompt_and_multimodal_expansion():
    from atlas.engine.kernel.loop import _current_user_message

    current_block = _turn_context_block(["Current user-local date and time: current"])
    messages = [
        {"role": "user", "kernel_run_id": "run", "kernel_message_id": "old", "content": "same"},
        {"role": "assistant", "content": "prior"},
        {"role": "user", "kernel_run_id": "run", "kernel_message_id": "new", "content": [
            {"type": "text", "text": "same"},
            {"type": "image_url", "image_url": {"url": "attachment://expanded"}},
        ]},
        {"role": "user", "kernel_run_id": "run", "kernel_message_id": "steer",
         "steered": True, "content": "same"},
    ]
    _attach_turn_context(messages, "new", current_block)
    assert messages[0]["content"] == "same"
    assert messages[2]["content"][0] == {"type": "text", "text": current_block}
    assert messages[2]["content"][1]["text"] == "same"
    assert messages[2]["content"][2]["image_url"]["url"] == "attachment://expanded"
    assert messages[3]["content"] == "same"
    assert _current_user_message(messages, "run", "new") is messages[2]


def test_legacy_original_user_alias_survives_canonical_history_refresh():
    from atlas.engine.kernel.loop import _current_user_message, _session_history

    rows = [
        {"role": "user", "content": "same", "metadata": {"kernel_run_id": "run"}},
        {"role": "user", "content": "same", "metadata": {
            "kernel_run_id": "run", "steered": True,
        }},
    ]
    initial = _session_history(rows)
    bound = _current_user_message(initial, "run", "run:user")
    assert bound is initial[0]
    assert bound["kernel_message_id"] == "run:user"

    canonical_refresh = _session_history(rows)
    bound_after_read = _current_user_message(canonical_refresh, "run", "run:user")
    assert bound_after_read is canonical_refresh[0]
    assert bound_after_read["kernel_message_id"] == "run:user"


def test_recalled_reference_survives_compaction_tail_and_snapshot_restore(tmp_path):
    from atlas.engine.kernel.loop import (
        _compaction_payload, _compaction_snapshot_state, _session_history,
        _turn_context_sections,
    )
    from atlas.engine.session_sync import (
        append_session_message, append_user_message_before_model,
        begin_session_compaction, compact_session_messages,
        read_session_model_messages, restore_session_snapshot,
    )
    from atlas.engine.state.atlas_state import SessionDB

    home = tmp_path / "sessions"
    session_id = "context-compaction-projection"
    fact_context = ["【本轮动态上下文】\nThe unique answer is ORBIT-17 [ref:memory:orbit-17]"]
    old_message_id = "run-old-message"
    current_message_id = "run-current-message"
    append_session_message(home, session_id, "user", "remember the answer", {
        "kernel_run_id": "run-old", "kernel_message_id": old_message_id,
        "turn_context": _turn_context_block(fact_context),
        "turn_context_sections": _turn_context_sections(fact_context),
    })
    append_session_message(home, session_id, "assistant", "Remembered.", {
        "kernel_run_id": "run-old",
    })
    append_user_message_before_model(home, session_id, "next turn", {
        "kernel_run_id": "run-current", "kernel_message_id": current_message_id,
        "turn_context_sections": _turn_context_sections([
            "Current user-local date and time: now",
        ]),
        "turn_context": _turn_context_block(["Current user-local date and time: now"]),
    })
    held = _session_history(read_session_model_messages(home, session_id))
    prompt_history = copy.deepcopy(held)
    current = prompt_history[-1]
    _attach_turn_context(
        prompt_history, current_message_id, current["turn_context"],
        current["turn_context_sections"],
    )
    projection = current["turn_context_projection"]
    ref_index = current["turn_context_ref_index"]
    compacted, tail_count, carried = _compaction_payload(
        [
            {"role": "user", "content": "[Conversation continuation summary] Earlier dialogue summarized."},
            prompt_history[-1],
        ],
        held,
        synthetic_system_prompt="synthetic",
        method="summary",
    )
    assert tail_count == 1
    assert len(compacted) == 2
    assert "ORBIT-17" not in " ".join(item["content"] if isinstance(item.get("content"), str) else ""
                                        for item in compacted)
    holder = "context-projection-test"
    watermark = begin_session_compaction(home, session_id, holder)
    production_snapshot_state = _compaction_snapshot_state(
        prompt_history, current_message_id, plan=None, todo=None, open_tool_call_ids=[],
    )
    assert production_snapshot_state["turn_context_projection"] == projection
    assert production_snapshot_state["turn_context_ref_index"] == ref_index
    compact_session_messages(
        home, session_id, holder, watermark, held, compacted,
        tail_count=tail_count, carried_messages=carried,
        snapshot_state=production_snapshot_state,
    )
    restored = restore_session_snapshot(home, session_id)
    assert restored["snapshot"]["state"]["turn_context_projection"] == projection
    assert restored["snapshot"]["state"]["turn_context_ref_index"] == [
        "[ref:memory:orbit-17]",
    ]
    with SessionDB(db_path=home / "state.db") as db:
        searchable = db.search_messages("memory", limit=10)
    assert any("[Retained context refs for searchable audit]" in row.get("snippet", "")
               or "[ref:memory:orbit-17]" in row.get("snippet", "") for row in searchable)

    next_id = "run-after-compact-message"
    append_user_message_before_model(home, session_id, "what was the answer?", {
        "kernel_run_id": "run-after-compact", "kernel_message_id": next_id,
        "turn_context_sections": _turn_context_sections([
            "Current user-local date and time: later",
        ]),
    })
    restored_history = _session_history(read_session_model_messages(home, session_id))
    _attach_turn_context(
        restored_history, next_id,
        _turn_context_block(["Current user-local date and time: later"]),
        _turn_context_sections(["Current user-local date and time: later"]),
        restored["snapshot"]["state"]["turn_context_projection"],
        restored["snapshot"]["state"]["turn_context_ref_index"],
    )
    wire = json.dumps(restored_history[-1]["content"], ensure_ascii=False)
    assert "ORBIT-17" in wire
    assert "ref:memory:orbit-17" in wire
    assert "Current user-local date and time: later" in wire
    assert "Current user-local date and time: now" not in wire


def test_budgeted_old_context_reintroduced_in_current_turn_is_not_deduped_away():
    same_fact = "F" * 6_100 + " [ref:memory:oversized-fact]"
    messages = [
        {"role": "user", "kernel_run_id": "old", "kernel_message_id": "old-id",
         "turn_context_sections": _turn_context_sections([same_fact]), "content": "old"},
        {"role": "user", "kernel_run_id": "current", "kernel_message_id": "current-id",
         "content": "new"},
    ]
    _attach_turn_context(messages, "current-id", "", _turn_context_sections([same_fact]))
    current_wire = json.dumps(messages[1]["content"], ensure_ascii=False)
    assert same_fact in current_wire
    assert "[ref:memory:oversized-fact]" in messages[1]["turn_context_ref_index"]


def test_legacy_plan_context_keeps_blank_line_json_inside_one_known_source():
    from atlas.engine.kernel.loop import _legacy_turn_context_sections

    legacy = _turn_context_block([
        "Follow this structured task plan. Complete pending subtasks in order.\n"
        "Plan JSON:\n{\n  \"steps\": [\n    {\"title\": \"keep blank lines\"}\n  ]\n}",
    ])
    sections = _legacy_turn_context_sections(legacy)
    assert len(sections) == 1
    assert sections[0]["current_only"] is True
    assert '"title": "keep blank lines"' in sections[0]["text"]


def test_legacy_hook_boundary_survives_adjacent_to_stale_clock():
    from atlas.engine.kernel.loop import _legacy_turn_context_sections

    legacy = _turn_context_block([
        "Current user-local date and time: 2026-11-15T10:00",
        "InstructionsLoaded hook context:\nKeep the required source citation in later turns.",
    ])
    sections = _legacy_turn_context_sections(legacy)
    assert len(sections) == 2
    assert sections[0]["current_only"] is True
    assert sections[1]["current_only"] is False
    assert "required source citation" in sections[1]["text"]


def test_context_audit_metadata_survives_replay_and_fork(tmp_path):
    from atlas.engine.session_sync import (
        append_session_message, fork_session_through_turn, read_session_model_messages,
        restore_session, rewind_user_turn,
    )

    home = tmp_path / "sessions"
    context = ["【本轮动态上下文】\nFact: ORBIT-17 [ref:memory:orbit-17]"]
    first_id = append_session_message(home, "source", "user", "remember", {
        "kernel_run_id": "run-one", "kernel_message_id": "run-one:user",
        "turn_context": _turn_context_block(context),
        "turn_context_sections": _turn_context_sections(context),
    })
    append_session_message(home, "source", "assistant", "saved", {"kernel_run_id": "run-one"})
    append_session_message(home, "source", "user", "second", {
        "kernel_run_id": "run-two", "kernel_message_id": "run-two:user",
        "turn_context": _turn_context_block(["Current user-local date and time: now"]),
        "turn_context_sections": _turn_context_sections(["Current user-local date and time: now"]),
    })
    append_session_message(home, "source", "assistant", "continued", {"kernel_run_id": "run-two"})

    snapshot = rewind_user_turn(home, "source", 1)
    restore_session(home, snapshot)
    replayed = read_session_model_messages(home, "source")
    replay_user = next(item for item in replayed if item["role"] == "user")
    assert replay_user["message_uid"] == first_id
    assert replay_user["display_metadata"]["kernel_message_id"] == "run-one:user"
    assert replay_user["display_metadata"]["turn_context_sections"] == _turn_context_sections(context)

    fork_session_through_turn(home, "source", "forked", 1, branch_message_id=first_id)
    forked = read_session_model_messages(home, "forked")
    fork_user = next(item for item in forked if item["role"] == "user")
    assert fork_user["display_metadata"]["kernel_message_id"] == "run-one:user"
    assert fork_user["display_metadata"]["turn_context"] == _turn_context_block(context)
