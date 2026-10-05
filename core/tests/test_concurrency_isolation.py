"""H3 concurrency isolation: 8 concurrent sessions share one HermesRuntime.

Taskbook §5 测试: run 8 sessions concurrently with different workspaces, models and
permission modes — including 2 simulated SSH workspaces, 2 approval-gated sessions,
one delegation session and one long-lived resident session — and assert that every
session's tool events, cwd, approvals and usage stay inside its own stream, with
tools executing in the right directory. Repeated waves (default 20) must all pass;
after the first wave the per-session agent cache serves every turn without new
constructions.

Scope note: the heartbeat scheduler and group-chat orchestrators are separate
subsystems outside the H3 engine lane (they own their integration tests). Their
concurrency contribution here is modeled by the resident long-lived session, while
the isolation seams under test (session-keyed tool context registry, per-session
policy routing, per-session agent cache) are the production ones.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import pytest
from run_agent import AIAgent

from atlas.engine.hermes_runtime import HermesRuntime
from atlas.ssh import SSHWorkspaceManager
from tests.fakes.fake_llm_provider import FakeLLMServer, Text, ToolCall, write_hermes_home

REPEATS = int(os.environ.get("ATLAS_H3_ISOLATION_REPEATS", "20"))
DONE_TIMEOUT = 240.0


class FakeAtlasAgent:
    """Atlas-side run double providing the surface the policy hooks read."""

    def __init__(self, marker: str):
        self._delegation = object()
        self.marker = marker

    def _model_facing_tools(self) -> list:
        return []

    def _checkpoint_path(self, path, workspace, run_id, conversation_id) -> str:
        return f"ckpt:{self.marker}:{path}"


def _atlas_context(
    conversation: str, workspace: str, permission_mode: str, approval_callback=None,
) -> SimpleNamespace:
    return SimpleNamespace(
        conversation_id=conversation, workspace=workspace, mode="act", run_id="iso-run",
        tool_allow=None, tool_deny=[], read_only=False,
        permission_mode=permission_mode, allowed_paths=[],
        event_queue=asyncio.Queue(), pause_event=None, cancel_event=None,
        approval_callback=approval_callback, user_hook_callback=None,
        hermes_write_checkpoint_created=False, changed_paths=set(),
        verification_passed=True, verify_nudge_sent=False, file_edit_counts={},
        hermes_preapproved_writes=set(), process_notifications=asyncio.Queue(),
    )


def _models(fake) -> SimpleNamespace:
    return SimpleNamespace(
        current_model="main-model", current_litellm_model="openai/main-model",
        gateway_base_url=fake.base_url, _api_key="sk-fake-e2e",
        list_models=lambda: [
            {"id": "main-model", "litellm_model": "openai/main-model",
             "max_output_tokens": 256},
            {"id": "worker-model", "litellm_model": "openai/worker-model",
             "max_output_tokens": 256},
        ],
    )


def _session_plan(tmp_path: Path) -> tuple[list[dict], dict[int, str]]:
    """One wave: 8 sessions with distinct workspaces/models/permission surfaces."""
    workspaces = {index: str(tmp_path / f"ws-{index}") for index in range(7)}
    for path in workspaces.values():
        Path(path).mkdir(parents=True, exist_ok=True)
    # Seed the two write targets so every wave can read-then-write (Hermes'
    # stale-overwrite guard refuses a blind whole-file rewrite).
    (Path(workspaces[1]) / "out.txt").write_text("seed", encoding="utf-8")
    (Path(workspaces[2]) / "out.txt").write_text("seed", encoding="utf-8")
    remote_alpha = tmp_path / "remote-alpha"
    remote_beta = tmp_path / "remote-beta"
    remote_alpha.mkdir(parents=True, exist_ok=True)
    remote_beta.mkdir(parents=True, exist_ok=True)
    plan = [
        {"key": "plain", "conversation": "iso-plain", "workspace": workspaces[0],
         "model": "main-model", "permission": "full_access", "script": []},
        {"key": "write", "conversation": "iso-write", "workspace": workspaces[1],
         "model": "main-model", "permission": "full_access",
         "write_root": workspaces[1], "write_content": "session write"},
        {"key": "approval", "conversation": "iso-approval", "workspace": workspaces[2],
         "model": "worker-model", "permission": "ask_writes",
         "write_root": workspaces[2], "write_content": "approved write"},
        {"key": "readonly", "conversation": "iso-readonly", "workspace": workspaces[3],
         "model": "worker-model", "permission": "read_only",
         "script": [ToolCall("write_file", {
                        "path": str(Path(workspaces[3]) / "out.txt"),
                        "content": "denied write"}),
                    Text("done-readonly")]},
        {"key": "ssh-alpha", "conversation": "iso-ssh-alpha",
         "workspace": "ssh://alpha/simulated-alpha",
         "model": "main-model", "permission": "full_access", "script": [],
         "remote_cwd": str(remote_alpha)},
        {"key": "ssh-beta", "conversation": "iso-ssh-beta",
         "workspace": "ssh://beta/simulated-beta",
         "model": "worker-model", "permission": "full_access", "script": [],
         "remote_cwd": str(remote_beta)},
        {"key": "delegate", "conversation": "iso-delegate", "workspace": workspaces[5],
         "model": "main-model", "permission": "full_access",
         "script": [ToolCall("delegate_task", {"goal": "delegate for iso-delegate"}),
                    Text("done-delegate")]},
        {"key": "resident", "conversation": "iso-resident", "workspace": workspaces[6],
         "model": "worker-model", "permission": "full_access", "script": [],
         "resident": True},
    ]
    return plan, workspaces


async def _collect(stream, sink: list[dict]) -> None:
    async for event in stream:
        sink.append(event)


def wave_script(item: dict, wave: int, workspaces: dict[int, str]) -> list:
    """Per-wave script; write sessions read-then-write wave-unique content."""
    if "write_root" not in item:
        return item["script"]
    target = str(Path(item["write_root"]) / "out.txt")
    return [
        ToolCall("read_file", {"path": target}),
        ToolCall("write_file", {"path": target,
                                "content": f"{item['write_content']} wave {wave}"}),
        Text(f"done-{item['key']}"),
    ]


@pytest.mark.asyncio
async def test_eight_concurrent_sessions_isolated_across_repeated_waves(
    tmp_path, monkeypatch,
):
    plan, workspaces = _session_plan(tmp_path)
    monkeypatch.setattr(
        SSHWorkspaceManager, "hosts",
        lambda self: [
            {"alias": "alpha", "hostname": "alpha", "user": "alice"},
            {"alias": "beta", "hostname": "beta", "user": "bob"},
        ],
    )
    monkeypatch.setattr(
        SSHWorkspaceManager, "parse_workspace",
        staticmethod(lambda uri: (
            uri.split("://", 1)[1].split("/", 1)[0],
            next(item["remote_cwd"] for item in plan if item["workspace"] == uri),
        )),
    )

    routing: dict = {"release": None}
    approvals: dict[str, list[dict]] = {}
    delegated: list[dict] = []
    streams: dict[str, list[dict]] = {item["conversation"]: [] for item in plan}
    contexts: dict[str, SimpleNamespace] = {}
    blocked_results: dict[str, list[dict]] = {}

    def responder(record) -> Text:
        body_messages = (record.get("body") or {}).get("messages") or []
        last_user = next(
            (message for message in reversed(body_messages)
             if message.get("role") == "user"),
            None,
        )
        content = str((last_user or {}).get("content") or "")
        for item in plan:
            if f"[{item['conversation']}]" in content:
                if item.get("resident"):
                    release = routing["release"]
                    assert release is not None
                    release.wait(timeout=DONE_TIMEOUT)
                    return Text("done-resident")
                queue = routing["queues"].get(item["conversation"])
                if queue:
                    return queue.popleft()
                return Text(f"done-{item['key']}")
        return Text("done-unmatched")

    with FakeLLMServer(responder) as fake:
        from http.server import ThreadingHTTPServer

        from tools.registry import registry

        # 8 sessions open keep-alive connections simultaneously; the stdlib default
        # listen backlog (5) refuses the tail under Windows, so widen it for this test.
        monkeypatch.setattr(ThreadingHTTPServer, "request_queue_size", 64)

        class FixtureConfig(dict):
            db_path = tmp_path / "config.db"

        # No MCP servers in this fixture: registration-once behavior is covered in
        # test_runtime_resources; here config stays empty so the wave stays hermetic.
        monkeypatch.setattr("atlas.config.get_config", lambda: FixtureConfig({
            "tools.servers": {}, "tools.auto_start": [],
            "agent.verify_before_stop": True,
        }))

        real_get_entry = registry.get_entry

        def fake_get_entry(name, **kwargs):
            if name == "delegate_task":
                def run_delegate(args, **kwargs):
                    delegated.append({"args": args, "session_id": kwargs.get("session_id")})
                    return json.dumps({"delegated": True}, ensure_ascii=False)

                return SimpleNamespace(handler=run_delegate)
            return real_get_entry(name, **kwargs)

        monkeypatch.setattr(registry, "get_entry", fake_get_entry)
        # The policy hooks stay REAL: they are the production per-session seam.

        constructions: list[dict] = []

        def factory(**kwargs):
            constructions.append(dict(kwargs))
            return AIAgent(**kwargs)

        runtime = HermesRuntime(
            data_dir=tmp_path / "data", model_manager=_models(fake),
            agent_factory=factory,
        )
        try:
            for wave in range(REPEATS):
                release = threading.Event()
                routing["release"] = release
                routing["queues"] = {
                    item["conversation"]: deque(wave_script(item, wave, workspaces))
                    for item in plan
                }
                approvals.clear()
                delegated.clear()
                blocked_results.clear()
                for sink in streams.values():
                    sink.clear()

                pending = []
                for item in plan:
                    if item["key"] == "approval":
                        def approval_callback(
                            approval_id, tool, arguments, _item=item,
                        ):
                            approvals.setdefault(_item["conversation"], []).append(
                                {"tool": tool, "arguments": arguments})
                            return "allow"
                    elif item["key"] == "readonly":
                        def approval_callback(
                            approval_id, tool, arguments, _item=item,
                        ):
                            approvals.setdefault(_item["conversation"], []).append(
                                {"tool": tool, "arguments": arguments})
                            return "deny"
                    else:
                        approval_callback = None
                    context = _atlas_context(
                        item["conversation"], item["workspace"], item["permission"],
                        approval_callback,
                    )
                    contexts[item["conversation"]] = context
                    pending.append((item, asyncio.ensure_future(_collect(
                        runtime.run_turn(
                            message=(
                                f"[{item['conversation']}] hold the line"
                                if item.get("resident") else
                                f"[{item['conversation']}] do your part"
                            ),
                            conversation_id=item["conversation"],
                            workspace=item["workspace"], history=[],
                            model_id=item["model"],
                            atlas_agent=FakeAtlasAgent(item["conversation"]),
                            atlas_context=context,
                        ), streams[item["conversation"]]))))

                others = [task for item, task in pending if not item.get("resident")]
                resident = [task for item, task in pending if item.get("resident")][0]
                await asyncio.wait_for(asyncio.gather(*others), timeout=DONE_TIMEOUT)
                # Drained policy-block bridges (they target the context queue, not
                # the stream — see hermes_policy._blocked).
                blocked_results = {
                    item["conversation"]: _drain_queue(contexts[item["conversation"]].event_queue)
                    for item in plan
                }
                assert not resident.done(), "resident turn ended before its release"
                release.set()
                await asyncio.wait_for(resident, timeout=DONE_TIMEOUT)
                _assert_wave_isolated(
                    plan, workspaces, approvals, delegated, constructions,
                    streams, blocked_results, wave,
                )
            cached_keys = set(runtime._agent_cache)
        finally:
            await runtime.aclose()

    # One construction per session across every wave (per-session agent reuse).
    assert len(constructions) == len(plan), (
        f"expected {len(plan)} constructions, saw {len(constructions)}"
    )
    assert cached_keys == {item["conversation"] for item in plan}


def _drain_queue(queue: asyncio.Queue) -> list[dict]:
    drained: list[dict] = []
    while not queue.empty():
        drained.append(queue.get_nowait())
    return drained


def _assert_wave_isolated(
    plan: list[dict], workspaces: dict[int, str], approvals: dict[str, list[dict]],
    delegated: list[dict], constructions: list[dict], streams: dict[str, list[dict]],
    blocked_results: dict[str, list[dict]], wave: int,
) -> None:
    for item in plan:
        events = streams[item["conversation"]]
        finals = [event for event in events if event.get("type") == "hermes.result"]
        assert finals, f"wave {wave}: {item['key']} produced no result"
        assert f"done-{item['key']}" in str(
            finals[-1].get("result", {}).get("final_response", "")), (
                f"wave {wave}: {item['key']} got a foreign final answer"
        )
        tool_events = [event for event in events
                       if event.get("type") in {"tool_call", "tool_result"}]

        if item["key"] in {"plain", "ssh-alpha", "ssh-beta", "resident"}:
            assert not tool_events, f"wave {wave}: {item['key']} saw tool events"
        if "write_root" in item:
            reads = [event for event in tool_events if event.get("name") == "read_file"]
            assert reads, f"wave {wave}: {item['key']} lost its read event"
            assert not any(
                event.get("is_error") for event in reads
            ), f"wave {wave}: {item['key']} read failed"
        if item["key"] == "write":
            assert [event for event in tool_events if event.get("name") == "write_file"]
            errors = [event for event in tool_events if event.get("is_error")]
            assert not errors, f"wave {wave}: write session errors: {errors!r}"[:2000]
            assert (Path(workspaces[1]) / "out.txt").read_text(
                encoding="utf-8") == f"session write wave {wave}"
        if item["key"] == "approval":
            asked = approvals.get(item["conversation"], [])
            assert len(asked) == 1 and asked[0]["tool"] == "write_file", (
                f"wave {wave}: approval surface saw {asked}"
            )
            assert (Path(workspaces[2]) / "out.txt").read_text(
                encoding="utf-8") == f"approved write wave {wave}"
        if item["key"] == "readonly":
            # Read-only blocks before any approval is consulted; no file lands. The
            # failure reaches Atlas through the policy block bridge on the context
            # queue (hermes_policy._blocked), not as a stream tool_result.
            assert approvals.get(item["conversation"], []) == []
            assert not (Path(workspaces[3]) / "out.txt").exists()
            blocked = blocked_results.get(item["conversation"], [])
            assert any(
                event.get("type") == "tool_result" and event.get("is_error")
                for event in blocked
            ), f"wave {wave}: read-only write was not blocked: {blocked!r}"[:1500]
        if item["key"] == "delegate":
            assert delegated and delegated[0]["session_id"] == item["conversation"], (
                f"wave {wave}: delegation escaped its session: {delegated}"
            )
            assert delegated[0]["args"].get("goal") == "delegate for iso-delegate"

        usage = [event for event in events if event.get("type") == "run_usage"]
        assert usage, f"wave {wave}: {item['key']} missing usage"
        expected_model = ("worker-model" if item["model"] == "worker-model"
                          else "main-model")
        assert usage[-1]["usage"]["model"] == expected_model, (
            f"wave {wave}: {item['key']} reported {usage[-1]['usage']['model']}"
        )

    # Approvals only ever surfaced in the two write-gated sessions' own callbacks.
    assert set(approvals) <= {"iso-approval", "iso-readonly"}
    # Writes landed only in their own session's workspace, nowhere else.
    wrote = {workspaces[1], workspaces[2]}
    for index, root in workspaces.items():
        if Path(root) not in [Path(workspaces[1]), Path(workspaces[2])]:
            assert not (Path(root) / "out.txt").exists(), (
                f"wave {wave}: workspace ws-{index} received a foreign write"
            )
    assert (Path(workspaces[1]) / "out.txt").exists()
    assert (Path(workspaces[2]) / "out.txt").exists()
    del wrote
    # SSH sessions were constructed with their own remote cwd mapping.
    for item in plan:
        if not item["workspace"].startswith("ssh://"):
            continue
        matching = [kwargs for kwargs in constructions
                    if kwargs.get("session_id") == item["conversation"]]
        assert matching, f"wave {wave}: {item['conversation']} never constructed"
        assert matching[-1]["cwd"] == item["remote_cwd"]
    # A session's tool events never carry another session's identity.
    for item in plan:
        own = json.dumps(
            [event for event in streams[item["conversation"]]
             if event.get("type") in {"tool_call", "tool_result"}],
            ensure_ascii=False, default=str,
        )
        for other in plan:
            if other["conversation"] == item["conversation"]:
                continue
            assert other["conversation"] not in own, (
                f"wave {wave}: {item['key']} stream leaked {other['key']} payload"
            )
