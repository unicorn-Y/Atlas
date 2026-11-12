from __future__ import annotations

from types import SimpleNamespace

import pytest

from atlas.agent import AgentOrchestrator
title_generator = pytest.importorskip("agent.title_generator", reason="title generation module moved into the Atlas engine")
from atlas.memory import MemoryStore
from atlas.tools.local_execution import LocalExecutionRuntime
from atlas.usage import aggregate_run_usage, deduplicate_run_usage
from tests.fakes.fake_llm_provider import FakeLLMServer, Text, ToolCall, write_atlas_home


@pytest.mark.asyncio
async def test_four_main_requests_forward_one_child_usage_row_once(tmp_path, monkeypatch):
    for name in (
        "ATLAS_RUN_INPUT_TOKEN_LIMIT", "ATLAS_RUN_BUDGET_ID",
        "ATLAS_RUN_USAGE_AUDIT_FILE",
    ):
        monkeypatch.delenv(name, raising=False)
    audit_path = tmp_path / "run-usage.jsonl"
    monkeypatch.setenv("ATLAS_RUN_INPUT_TOKEN_LIMIT", "50000")
    monkeypatch.setenv("ATLAS_RUN_BUDGET_ID", "usage-test-budget")
    monkeypatch.setenv("ATLAS_RUN_USAGE_AUDIT_FILE", str(audit_path))
    monkeypatch.setattr(title_generator, "_auto_title_enabled", lambda: False)
    data_root = tmp_path / "atlas-data"
    from atlas.config import AtlasConfig

    monkeypatch.setattr("atlas.config._config", AtlasConfig({
        "tools": {"servers": {}, "auto_start": []},
        "agent": {"verify_before_stop": False},
        "memory": {"db_path": str(tmp_path / "store.db")},
    }))
    monkeypatch.setattr("atlas.config.DATA_ROOT", data_root)
    monkeypatch.setenv("ATLAS_DATA_DIR", str(data_root))
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with FakeLLMServer([
        ToolCall("delegate_task", {"goal": "complete a child task"}),
        Text("real child completed", prompt_tokens=60, completion_tokens=3),
        ToolCall("todo_list", {"todos": []}),
        ToolCall("todo_list", {"todos": []}),
        Text("parent completed"),
    ]) as fake:
        home = data_root / "engine"
        write_atlas_home(home, fake.base_url, extra_config=(
            "auxiliary:\n"
            "  title_generation:\n"
            "    enabled: false\n"
        ))
        monkeypatch.setenv("HERMES_HOME", str(home))
        models = SimpleNamespace(
            current_model="fake-model", current_litellm_model="fake-model",
            gateway_base_url=fake.base_url, _api_key="sk-fake-e2e",
            list_models=lambda: [{"id": "fake-model", "max_output_tokens": 256}],
        )
        memory = MemoryStore(db_path=tmp_path / "memory.sqlite3")
        await memory.init()
        local = LocalExecutionRuntime()
        agent = AgentOrchestrator(
            models, memory, local_execution=local,
            agent_backend_host=SimpleNamespace(backends={}),
        )
        child_results = []
        original_child_runner = agent._run_atlas_subtask

        async def capture_child_result(**kwargs):
            result = await original_child_runner(**kwargs)
            child_results.append(result)
            return result

        agent._delegation.atlas_runner = capture_child_result
        try:
            events = [event async for event in agent.run(
                message="delegate_task once for a bounded task and finish",
                conversation_id="usage-parent-conversation", model="fake-model",
                run_id="usage-parent-run", workspace=str(workspace),
                tool_allow=["delegate_task", "todo_list"],
            )]
            requests = fake.main_requests()
        finally:
            await local.shutdown()
            await memory.close()
    emitted_rows = [event["usage"] for event in events if event.get("type") == "run_usage"]
    rows = deduplicate_run_usage(emitted_rows)
    main_rows = [row for row in rows if row.get("purpose") == "conversation"]
    child_rows = [row for row in rows if row.get("purpose") == "subagent"]
    child_requests = [request for request in requests
                      if "子任务 Worker" in str(request.get("messages", []))]

    assert len(requests) == 5, events
    assert len(child_requests) == 1
    assert len(child_results) == 1
    assert len(main_rows) == 4, [(row.get("purpose"), row.get("request_id")) for row in rows]
    assert len(child_rows) == 1, [(row.get("purpose"), row.get("request_id"), row.get("input_tokens"))
                                  for row in rows] + [child_results[0].get("evidence")]
    assert child_rows[0]["request_id"]
    assert child_rows[0]["original_purpose"] == "conversation"
    assert child_rows[0]["subtask_id"]
    assert sum(row["input_tokens"] for row in rows) == 460
    assert sum(row["output_tokens"] for row in rows) == 53
    assert len({row["request_id"] for row in rows}) == 5
    totals = aggregate_run_usage(rows)
    latest_main_context = next(
        row["context_tokens"] for row in reversed(main_rows)
        if isinstance(row.get("context_tokens"), int)
    )
    assert totals["input_tokens"] == 460 and totals["output_tokens"] == 53
    assert totals["request_count"] == 5
    assert totals["purpose_totals"]["conversation"]["request_count"] == 4
    assert totals["purpose_totals"]["subagent"]["request_count"] == 1
    assert totals["context_tokens"] == latest_main_context
    import json

    audit_rows = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert len(audit_rows) == 5
    assert len({row["request_id"] for row in audit_rows}) == 5
    assert sum(row["budget_input_tokens"] for row in audit_rows) == 460
    assert all(row["budget_usage_unknown"] is False for row in audit_rows)
