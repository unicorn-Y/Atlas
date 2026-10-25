"""Group store records + GroupOrchestrator round-engine state machine (r4 §3.3)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from atlas.groups import (
    GroupOrchestrator,
    GroupTurnReport,
    TurnConflict,
    session_key,
)
from atlas.groups.store import DEFAULT_ROUND_CAPS, GroupService, GroupStore

GID = "team"
MEMBERS = ("alice", "bob", "carol")


class FakeLookup:
    """MemberLookup seam fake: id -> agent record (``kind`` included)."""

    def __init__(self, agents: dict[str, dict[str, Any]]) -> None:
        self.agents = agents

    def get(self, agent_id: str) -> dict[str, Any] | None:
        return self.agents.get(agent_id)


class FakeDispatcher:
    """TurnDispatcher fake: scripted per-agent replies, records every call."""

    def __init__(
        self,
        script: dict[str, list[str]] | None = None,
        default: str = "(pass)",
        on_call: Any = None,
    ) -> None:
        self.script = dict(script or {})
        self.default = default
        self.on_call = on_call
        self.on_call_result: dict[str, Any] = {}
        self.calls: list[dict[str, Any]] = []

    def __call__(self, agent_id: str, prompt: str, skey: str, context: dict[str, Any]):
        self.calls.append({
            "agent_id": agent_id, "prompt": prompt,
            "session_key": skey, "context": context,
        })
        if self.on_call is not None:
            self.on_call(agent_id, self)
        queue = self.script.get(agent_id) or []
        return queue.pop(0) if queue else self.default


def make_service(tmp_path: Path, lookup: FakeLookup | None = None) -> GroupService:
    return GroupService(GroupStore(tmp_path), lookup=lookup)


def make_group(service: GroupService, members: tuple[str, ...] = MEMBERS, **overrides: Any) -> dict:
    payload: dict[str, Any] = {"id": GID, "name": "Team", "member_agent_ids": list(members)}
    payload.update(overrides)
    return service.create(payload)


def make_orchestrator(
    service: GroupService,
    script: dict[str, list[str]] | None = None,
    default: str = "(pass)",
    on_call: Any = None,
    **kwargs: Any,
) -> tuple[GroupOrchestrator, FakeDispatcher]:
    agents = {mid: {"id": mid, "name": mid.capitalize(), "kind": "persistent"} for mid in MEMBERS}
    dispatcher = FakeDispatcher(script=script, default=default, on_call=on_call)
    orch = GroupOrchestrator(
        service, dispatcher=dispatcher, member_lookup=FakeLookup(agents), **kwargs)
    return orch, dispatcher


def run(orch: GroupOrchestrator, text: str, **incoming: Any) -> GroupTurnReport:
    payload: dict[str, Any] = {"from_actor": "user", "text": text}
    payload.update(incoming)
    return asyncio.run(orch.run_turn(GID, payload))


def call_order(dispatcher: FakeDispatcher) -> list[str]:
    return [call["agent_id"] for call in dispatcher.calls]


# -- store: records, validation, membership -----------------------------------


def test_group_defaults_and_roundtrip(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    record = make_group(service)
    assert record["enabled"] is True
    assert record["delivery"] == "origin"
    assert record["round_caps"] == DEFAULT_ROUND_CAPS
    assert record["topic_routes"] == [] and record["default_route"] == []
    assert record["route_fallback"] == "broadcast"
    reloaded = GroupService(GroupStore(tmp_path))
    assert reloaded.get(GID) == record
    assert [g["id"] for g in reloaded.list_groups()] == [GID]


def test_member_validation_via_lookup(tmp_path: Path) -> None:
    lookup = FakeLookup({
        "alice": {"id": "alice", "name": "Alice", "kind": "persistent"},
        "default": {"id": "default", "name": "Default", "kind": "role"},
    })
    service = make_service(tmp_path, lookup=lookup)
    with pytest.raises(KeyError, match="agent not found: ghost"):
        service.create({"id": GID, "name": "T", "member_agent_ids": ["ghost"]})
    with pytest.raises(ValueError, match="must be persistent agents"):
        service.create({"id": GID, "name": "T", "member_agent_ids": ["alice", "default"]})
    record = service.create({"id": GID, "name": "T", "member_agent_ids": ["alice"]})
    assert record["member_agent_ids"] == ["alice"]


def test_member_add_remove_rules(tmp_path: Path) -> None:
    lookup = FakeLookup({
        mid: {"id": mid, "name": mid, "kind": "persistent"} for mid in ("a", "b")
        } | {"role-agent": {"id": "role-agent", "name": "Role", "kind": "role"}})
    service = make_service(tmp_path, lookup=lookup)
    service.create({"id": GID, "name": "T", "member_agent_ids": ["a"]})
    assert service.add_member(GID, "b") == ["a", "b"]
    with pytest.raises(ValueError, match="already a member"):
        service.add_member(GID, "b")
    with pytest.raises(ValueError, match="must be persistent"):
        service.add_member(GID, "role-agent")
    assert service.remove_member(GID, "a") == ["b"]
    with pytest.raises(KeyError, match="not a member"):
        service.remove_member(GID, "a")
    with pytest.raises(ValueError, match="at least one member"):
        service.remove_member(GID, "b")


def test_group_field_validation(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    with pytest.raises(ValueError, match="unsupported fields"):
        service.create({"id": GID, "name": "T", "member_agent_ids": ["a"], "nope": 1})
    with pytest.raises(ValueError, match="duplicates"):
        service.create({"id": GID, "name": "T", "member_agent_ids": ["a", "a"]})
    with pytest.raises(ValueError, match="at least one member"):
        service.create({"id": GID, "name": "T", "member_agent_ids": []})
    with pytest.raises(ValueError, match="positive integer"):
        service.create({"id": GID, "name": "T", "member_agent_ids": ["a"],
                        "round_caps": {"max_rounds": 0}})
    with pytest.raises(ValueError, match="unsupported fields"):
        service.create({"id": GID, "name": "T", "member_agent_ids": ["a"],
                        "round_caps": {"bogus": 1}})
    with pytest.raises(ValueError, match="delivery"):
        service.create({"id": GID, "name": "T", "member_agent_ids": ["a"], "delivery": "wat"})
    with pytest.raises(ValueError, match="needs keywords or a role"):
        service.create({"id": GID, "name": "route", "member_agent_ids": ["a"],
                        "topic_routes": [{"id": "empty", "keywords": [], "agent_ids": ["a"]}]})
    with pytest.raises(ValueError, match="group member ids"):
        service.create({"id": GID, "name": "route", "member_agent_ids": ["a"],
                        "default_route": ["ghost"]})


def test_update_partial_caps_merge(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.create({"id": GID, "name": "T", "member_agent_ids": ["a"],
                    "round_caps": {"max_rounds": 2, "max_messages": 9}})
    updated = service.update(GID, {"round_caps": {"max_rounds": 3}, "name": "T2"})
    assert updated["round_caps"] == {
        "max_rounds": 3, "max_messages": 9,
        "max_continuations": DEFAULT_ROUND_CAPS["max_continuations"],
    }
    assert updated["created_at"] == service.get(GID)["created_at"]


def test_removing_member_prunes_route_targets(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    make_group(service, members=("alice", "bob"), topic_routes=[{
        "id": "route", "keywords": ["review"], "agent_ids": ["alice", "bob"],
    }], default_route=["bob"])
    service.remove_member(GID, "bob")
    group = service.get(GID)
    assert group["topic_routes"][0]["agent_ids"] == ["alice"]
    assert group["default_route"] == []


# -- round engine: deterministic rotation, @ resolution, passes ----------------


def test_round_robin_order_rotates_per_round(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    make_group(service)
    script = {mid: [f"hi {mid}"] for mid in MEMBERS}
    orch, dispatcher = make_orchestrator(service, script=script)
    report = run(orch, "kickoff")
    assert report.status == "settled"
    assert report.rounds == 2
    assert report.messages == 3
    assert call_order(dispatcher) == ["alice", "bob", "carol", "bob", "carol", "alice"]
    assert report.speakers == ["alice", "bob", "carol"]
    assert report.passes == ["bob", "carol", "alice"]  # round-2 rotation shifted by one


def test_explicit_mention_selects_named_members(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    make_group(service)
    orch, dispatcher = make_orchestrator(service)  # default: everyone passes
    report = run(orch, "@bob please look")
    assert call_order(dispatcher) == ["bob"]
    assert report.status == "settled" and report.rounds == 1
    run(orch, "@Carol hi")  # display name resolves too (case-insensitive)
    assert call_order(dispatcher)[-1] == "carol"


def test_topic_route_selects_members_and_records_rule_in_timeline(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    make_group(service, topic_routes=[{
        "id": "design-review", "keywords": ["design", "mockup"],
        "role": "designer", "agent_ids": ["bob"], "priority": 4,
    }], default_route=["carol"], route_fallback="default")
    orch, dispatcher = make_orchestrator(service)
    run(orch, "Please review this design")
    assert call_order(dispatcher) == ["bob"]
    timeline = orch.timeline(GID)["entries"]
    route_event = next(entry for entry in timeline if entry["kind"] == "event")
    assert "rule=design-review" in route_event["text"]
    assert "@bob" in route_event["text"]


def test_topic_route_priority_and_conflict_fallback(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    make_group(service, topic_routes=[
        {"id": "topic-a", "keywords": ["deploy"], "role": "ops", "agent_ids": ["alice"], "priority": 1},
        {"id": "topic-b", "keywords": ["deploy"], "role": "design", "agent_ids": ["bob"], "priority": 1},
        {"id": "priority", "keywords": ["release"], "role": "ops", "agent_ids": ["alice"], "priority": 8},
    ], default_route=["carol"], route_fallback="default")
    orch, dispatcher = make_orchestrator(service)
    run(orch, "deploy release")
    assert call_order(dispatcher) == ["alice"]
    assert "rule=priority" in next(entry["text"] for entry in orch.timeline(GID)["entries"] if entry["kind"] == "event")

    service2 = make_service(tmp_path / "conflict")
    make_group(service2, topic_routes=[
        {"id": "topic-a", "keywords": ["deploy"], "role": "ops", "agent_ids": ["alice"], "priority": 1},
        {"id": "topic-b", "keywords": ["deploy"], "role": "design", "agent_ids": ["bob"], "priority": 1},
    ], default_route=["carol"], route_fallback="default")
    orch2, dispatcher2 = make_orchestrator(service2)
    run(orch2, "deploy now")
    assert call_order(dispatcher2) == ["carol"]
    assert "route-conflict-default" in next(entry["text"] for entry in orch2.timeline(GID)["entries"] if entry["kind"] == "event")


def test_mention_everyone_selects_all(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    make_group(service)
    orch, dispatcher = make_orchestrator(service)
    run(orch, "@everyone attention")
    assert set(call_order(dispatcher)) == set(MEMBERS)


def test_all_pass_settles_silently(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    make_group(service)
    orch, dispatcher = make_orchestrator(service)
    report = run(orch, "anyone?")
    assert report.status == "settled"
    assert report.rounds == 1 and report.messages == 0
    assert report.passes == list(MEMBERS)
    assert dispatcher.calls[0]["prompt"].startswith('[Group chat: "Team"')


def test_member_turn_context_and_session_key(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    make_group(service)
    orch, dispatcher = make_orchestrator(
        service, script={"alice": ["hello group"]}, default="(pass)")
    run(orch, "hello")
    call = dispatcher.calls[0]
    assert call["session_key"] == session_key("alice", peer=GID, group=True)
    assert call["context"]["thread_id"] == "main"
    assert call["context"]["continuation"] is False
    assert call["context"]["session_key"] == call["session_key"]
    assert "@alice" in call["prompt"]
    assert "(pass)" in call["prompt"]
    assert "user: hello" in call["prompt"]


# -- hard caps: max_rounds / max_messages / max_continuations ------------------


def test_max_rounds_cap(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    make_group(service, round_caps={"max_rounds": 2})
    orch, dispatcher = make_orchestrator(service, default="still thinking")
    report = run(orch, "go")
    assert report.status == "capped" and report.capped_by == "max_rounds"
    assert report.rounds == 2 and report.messages == 6
    assert call_order(dispatcher) == [
        "alice", "bob", "carol",  # round 1
        "bob", "carol", "alice",  # round 2 (rotation shift), then cap
    ]


def test_max_messages_cap(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    make_group(service, members=("alice", "bob"), round_caps={"max_messages": 3})
    orch, dispatcher = make_orchestrator(service, default="ok")
    report = run(orch, "go")
    assert report.status == "capped" and report.capped_by == "max_messages"
    assert report.messages == 3
    # round 2 starts at bob; alice never runs (messages cap fires first)
    assert call_order(dispatcher) == ["alice", "bob", "bob"]


def test_handoff_gives_immediate_next_slot(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    make_group(service)
    orch, dispatcher = make_orchestrator(
        service, script={"alice": ["@carol your turn"], "carol": ["on it"]}, default="(pass)",
    )
    report = run(orch, "kickoff")
    # carol (handoff) speaks before bob (rotation slot)
    assert call_order(dispatcher)[:3] == ["alice", "carol", "bob"]
    assert report.continuations == 1
    assert report.status == "settled"
    assert dispatcher.calls[1]["context"]["continuation"] is True


def test_handoff_continuation_cap(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    make_group(
        service, members=("alice", "bob"),
        round_caps={"max_continuations": 1, "max_rounds": 1},
    )
    orch, dispatcher = make_orchestrator(
        service, script={"alice": ["@bob please"], "bob": ["@alice back at you"]},
    )
    report = run(orch, "go")
    assert call_order(dispatcher) == ["alice", "bob"]
    assert report.continuations == 1
    assert report.dropped_handoffs == ["alice"]  # over-budget handoff dropped
    assert report.rounds == 1
    assert report.status == "capped" and report.capped_by == "max_rounds"


# -- watermarks / threads / persistence ----------------------------------------


def test_watermark_isolation_between_drives(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    make_group(service)
    orch, dispatcher = make_orchestrator(
        service, script={"alice": ["first reply"], "bob": ["second reply"]}, default="(pass)",
    )
    run(orch, "msg one")
    assert "msg one" in dispatcher.calls[0]["prompt"]  # alice sees the kickoff
    assert "msg one" in dispatcher.calls[1]["prompt"]  # bob sees kickoff + alice reply
    before = len(dispatcher.calls)
    run(orch, "msg two")
    alice_second = dispatcher.calls[before]["prompt"]  # drive 2 round 1 starts at alice
    assert "msg two" in alice_second
    assert "msg one" not in alice_second  # alice's watermark is past drive 1
    assert "first reply" not in alice_second


def test_threads_are_isolated(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    make_group(service)
    orch, dispatcher = make_orchestrator(service, default="(pass)")
    run(orch, "main talk")
    dispatcher.script["alice"] = ["side reply"]
    run(orch, "side talk", thread_id="side")
    side_calls = [c for c in dispatcher.calls if c["context"]["thread_id"] == "side"]
    assert [c["agent_id"] for c in side_calls] == [
        "alice", "bob", "carol",  # round 1: alice replies, bob/carol pass
        "bob", "carol", "alice",  # round-2 rotation, all pass -> settled
    ]
    assert "side talk" in side_calls[0]["prompt"]
    assert "main talk" not in side_calls[0]["prompt"]
    assert "· side" in side_calls[0]["prompt"]
    timeline = orch.timeline(GID, thread_id="side")
    assert [e["text"] for e in timeline["entries"]] == ["side talk", "side reply"]


def test_stop_terminates_drive_at_member_boundary(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    make_group(service)
    orch, dispatcher = make_orchestrator(service)  # default reply set below

    def on_call(agent_id: str, fake: FakeDispatcher) -> None:
        if agent_id == "bob":
            fake.on_call_result["stop"] = orch.stop(GID)

    dispatcher.on_call = on_call
    dispatcher.default = "talking"
    report = run(orch, "go")
    assert dispatcher.on_call_result["stop"] == {
        "group_id": GID, "thread_id": "main", "epoch": 1}
    assert report.status == "stopped"
    assert call_order(dispatcher) == ["alice", "bob"]  # stop fired at bob; carol never runs
    assert orch.epoch(GID) == 1
    # a fresh drive adopts the new epoch and runs normally (stop hook detached)
    dispatcher.on_call = None
    dispatcher.default = "(pass)"
    report2 = run(orch, "again")
    assert report2.status == "settled" and report2.rounds == 1


def test_stranded_late_messages_are_recorded_not_replayed(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    make_group(service)
    orch, dispatcher = make_orchestrator(
        service, script={"alice": ["in-time"]}, default="(pass)")
    run(orch, "kickoff")
    entry = orch.submit_member_message(GID, "carol", "late thought")
    assert entry["kind"] == "stranded"
    with pytest.raises(ValueError, match="not a group member"):
        orch.submit_member_message(GID, "stranger", "hi")
    before = len(dispatcher.calls)
    run(orch, "next round")
    for call in dispatcher.calls[before:]:
        assert "late thought" not in call["prompt"]
    kinds = [e["kind"] for e in orch.timeline(GID)["entries"]]
    assert "stranded" in kinds
    # while a drive is running the same submission is a live member message
    orch2, dispatcher2 = make_orchestrator(service, default="(pass)")

    def on_call(agent_id: str, fake: FakeDispatcher) -> None:
        if agent_id == "alice":
            fake.on_call_result["live"] = orch2.submit_member_message(GID, "bob", "inline addition")

    dispatcher2.on_call = on_call
    report = asyncio.run(orch2.run_turn(GID, {"text": "trigger"}))
    assert dispatcher2.on_call_result["live"]["kind"] == "member"
    assert report.status == "settled"


def test_jsonl_log_and_seq_survive_restart(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    make_group(service)
    orch, _ = make_orchestrator(service, script={"alice": ["hello"]}, default="(pass)")
    first = run(orch, "kickoff")
    assert (tmp_path / "groups" / GID / "log.jsonl").is_file()  # logs live under store.root
    # a brand-new orchestrator (restart) resumes seq + epochs from disk
    orch2, _ = make_orchestrator(service)
    entries = orch2.timeline(GID)["entries"]
    assert [e["seq"] for e in entries] == [1, 2]
    late = orch2.submit_member_message(GID, "bob", "late")
    assert late["seq"] == first.ended_seq + 1
    assert orch2.epoch(GID) == 0
    orch2.stop(GID)
    orch3, _ = make_orchestrator(service)
    assert orch3.epoch(GID) == 1


def test_turn_conflict_and_validation(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    make_group(service)

    async def busy_dispatcher(agent_id: str, prompt: str, skey: str, context: dict[str, Any]):
        await orch.run_turn(GID, {"text": "nested"})  # nested drive -> conflict
        return "unreachable"

    agents = {mid: {"id": mid, "name": mid, "kind": "persistent"} for mid in MEMBERS}
    orch = GroupOrchestrator(
        service, dispatcher=busy_dispatcher, member_lookup=FakeLookup(agents))
    with pytest.raises(TurnConflict, match="already running"):
        asyncio.run(orch.run_turn(GID, {"text": "outer"}))

    with pytest.raises(KeyError, match="group not found"):
        asyncio.run(orch.run_turn("ghost", {"text": "hi"}))
    service.update(GID, {"enabled": False})
    with pytest.raises(ValueError, match="disabled"):
        asyncio.run(orch.run_turn(GID, {"text": "hi"}))
    service.update(GID, {"enabled": True})
    with pytest.raises(ValueError, match="text is required"):
        asyncio.run(orch.run_turn(GID, {"text": "  "}))
    with pytest.raises(ValueError, match="from_actor"):
        asyncio.run(orch.run_turn(GID, {"text": "hi", "from_actor": "ghost"}))
    with pytest.raises(ValueError, match="thread_id"):
        asyncio.run(orch.run_turn(GID, {"text": "hi", "thread_id": "bad thread"}))
