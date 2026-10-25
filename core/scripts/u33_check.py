"""End-to-end local scenarios for every U33 construction item.

Uses temporary files, SQLite and local fake orchestration; no Electron window,
screenshots, remote channel or model request is started.
"""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from atlas.agent.subagent_capacity import SubagentCapacity
from atlas.api.app_services import AppServices
from atlas.api.runtime import RuntimeManager
from atlas.api.runtime_router import router as runtime_router
from atlas.channels.contract import MessageEvent
from atlas.channels.routing import resolve_group_recipients, resolve_route
from atlas.engine_core.goals import GoalManager
from atlas.groups.store import GroupService, GroupStore
from atlas import standing_orders
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def check_group_routes_and_mentions(root: Path) -> None:
    event = MessageEvent(
        channel="slack", account="workspace", event_id="u33-mention", chat_id="ops",
        sender_id="U-human", is_group=True, mentions=["U-reviewer"],
    )
    bindings = [{"agent_id": "reviewer", "channel": "slack", "account": "workspace",
                 "peer_kind": "group", "peer_id": "ops", "mention_names": ["U-reviewer"]}]
    assert resolve_route(bindings, event) == "reviewer"

    groups = GroupService(GroupStore(root / "groups"))
    groups.create({
        "id": "u33-room", "name": "U33 room", "member_agent_ids": ["general", "ops", "review"],
        "topic_routes": [
            {"id": "deploy", "keywords": ["deploy"], "agent_ids": ["ops"], "priority": 5},
            {"id": "fallback", "keywords": ["deploy"], "agent_ids": ["review"], "priority": 5},
        ], "default_route": ["general"], "route_fallback": "default",
    })
    saved = groups.get("u33-room")
    conflict = resolve_group_recipients(
        [{"id": item} for item in saved["member_agent_ids"]], "please deploy",
        topic_routes=saved["topic_routes"], default_route=saved["default_route"],
        fallback=saved["route_fallback"],
    )
    assert conflict["agent_ids"] == ["general"] and conflict["conflict"]
    explicit = resolve_group_recipients(
        [{"id": item} for item in saved["member_agent_ids"]], "please deploy",
        mentions=["review"], topic_routes=saved["topic_routes"],
        default_route=saved["default_route"], fallback="default",
    )
    assert explicit["agent_ids"] == ["review"] and explicit["matched_rule"] == "mention"


def check_standing_orders(root: Path) -> None:
    original_paths = standing_orders._paths
    standing_orders._paths = lambda: (root / "orders.json", root / "orders-audit.jsonl")
    try:
        order = standing_orders.create_order({
            "owner_agent_id": "agent-review", "name": "Careful review",
            "instruction": "Check edge cases and report evidence.",
            "scope": {"kind": "workspace", "workspace": "C:/work"},
            "trigger": {"keywords": ["review"]},
        })
        assert standing_orders.list_orders("evidence", "agent-review")[0]["id"] == order["id"]
        assert standing_orders.matching_orders("agent-review", "c:/WORK", "review this")
        assert not standing_orders.matching_orders("agent-review", "C:/other", "review this")
        assert standing_orders.recent_audit(order_id=order["id"])[0]["matched_keywords"] == ["review"]
        standing_orders.update_order(order["id"], {**order, "enabled": False})
        assert not standing_orders.matching_orders("agent-review", "C:/work", "review this")
        assert standing_orders.delete_order(order["id"])
        assert standing_orders.recent_audit(order_id=order["id"])
    finally:
        standing_orders._paths = original_paths


def check_subgoals(root: Path) -> None:
    manager = GoalManager("u33-goal", home=root / "goal")
    manager.set("U33 goal")
    manager.add_subgoal("first")
    manager.add_subgoal("second")
    manager.complete_subgoal(2)
    manager.edit_subgoal(2, "second revised")
    manager.remove_subgoal(1)
    assert manager.state.subgoals == ["second revised"]
    assert manager.state.completed_subgoals == [1]
    assert manager.clear_subgoals() == 1 and manager.state.subgoals == []


async def check_subtask_capacity() -> None:
    capacity = SubagentCapacity(max_concurrent=1)
    first = await capacity.acquire(parent_id="parent", depth=1)
    waiting = asyncio.create_task(capacity.acquire(parent_id="parent-2", depth=1))
    await asyncio.sleep(0)
    assert capacity.active_count == 1 and capacity.waiting_count == 1
    await capacity.release(first)
    second = await asyncio.wait_for(waiting, timeout=1)
    assert capacity.active_count == 1 and capacity.waiting_count == 0
    await capacity.release(second)


async def check_native_subtask_lifecycle(root: Path) -> None:
    class Memory:
        async def get_conversation(self, conversation_id: str):
            return {"id": conversation_id}

    class Orchestrator:
        async def _run_atlas_subtask(self, **kwargs):
            return {"status": "completed", "session_id": kwargs["atlas_options"]["resume_session_id"]}

    manager = RuntimeManager(root / "runtime.sqlite")
    await manager.init()
    await manager.save_subtask({
        "parent_run_id": "parent", "subtask_id": "child", "status": "closed",
        "goal": "continue safely", "backend": "atlas", "workspace": str(root),
        "model": "fake-model", "session_id": "child-session",
        "recovery_point": {"workspace": str(root)},
    })
    await manager.save_subtask({
        "parent_run_id": "parent", "subtask_id": "child-running", "status": "running",
        "goal": "stop safely", "backend": "atlas", "workspace": str(root),
        "model": "fake-model", "session_id": "child-running-session",
        "recovery_point": {"workspace": str(root)},
    })
    app = FastAPI()
    app.state.services = AppServices(runtime_mgr=manager, memory=Memory(), orchestrator=Orchestrator())
    app.include_router(runtime_router)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://u33.local") as client:
            listing = await client.get("/api/runs/parent/subtasks")
            listed = listing.json()["items"]
            assert listing.status_code == 200 and any(row["session_id"] == "child-session" for row in listed)
            resumed = await client.post("/api/runs/parent/subtasks/child/resume")
            assert resumed.status_code == 200
            task = manager.subtask_tasks.get(("parent", "child"))
            if task:
                await task
            terminal = await client.post("/api/runs/parent/subtasks/child/resume")
            assert terminal.status_code == 409 and "已完成的终态不支持恢复" in terminal.json()["detail"]
            closed = await client.post("/api/runs/parent/subtasks/child-running/close")
            assert closed.status_code == 200 and closed.json()["status"] == "closed"
        assert (await manager.get_subtask("parent", "child"))["status"] == "completed"
        assert (await manager.get_subtask("parent", "child-running"))["status"] == "closed"
    finally:
        await manager.close()


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="atlas-u33-") as temporary:
        root = Path(temporary)
        check_group_routes_and_mentions(root)
        check_standing_orders(root)
        check_subgoals(root)
        await check_subtask_capacity()
        await check_native_subtask_lifecycle(root)
    print("1/5 mention and topic group routing: PASS")
    print("2/5 standing order CRUD, matching, pause and audit: PASS")
    print("3/5 subgoal edit, remove, completion and clear: PASS")
    print("4/5 native child list, close, resume and terminal explanation: PASS")
    print("5/5 configurable concurrent child admission: PASS")
    print("U33 CHECK PASS")


if __name__ == "__main__":
    asyncio.run(main())
