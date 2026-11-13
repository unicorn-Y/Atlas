from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from atlas.api.runtime import RunState
from atlas.api.runtime_ws_router import page_run_events


@pytest.mark.unit
def test_run_event_page_exposes_cursor_header_tail_and_bounded_events() -> None:
    run = RunState("run-1", "conversation-1", "model")
    run.next_envelope("run.started", {"content": "hello"})
    for index in range(1, 6):
        run.next_envelope("message.delta", {"content": str(index)})
    services = SimpleNamespace(runtime_mgr=SimpleNamespace(runs={run.run_id: run}))

    page = asyncio.run(page_run_events(run.run_id, services, 2, 2))

    assert [event["sequence"] for event in page["events"]] == [3, 4]
    assert page["next_cursor"] == 4
    assert page["cursor"] == 6
    assert page["has_more"] is True
    assert page["header"][0]["sequence"] == 1
    assert [event["sequence"] for event in page["tail"]] == [1, 2, 3, 4, 5, 6]
    assert page["projection_baseline"] == {"run_id": "run-1", "sequence": 6}
