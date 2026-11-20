import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from atlas.engine.kernel.inbox import DurableInbox
from atlas.engine.session_sync import read_session_events


_PROCESS_ENQUEUE = r"""
import asyncio
import json
import sys
import time
from pathlib import Path
from atlas.engine.kernel.inbox import DurableInbox

async def main():
    home, session, ready, gate, request_id, lane, content = sys.argv[1:]
    inbox = DurableInbox(Path(home), session)
    await inbox.restore()
    Path(ready).write_text("ready", encoding="utf-8")
    while not Path(gate).exists():
        time.sleep(0.01)
    try:
        event_id, created = await inbox.inject_with_receipt(
            content, lane=lane, request_id=request_id,
        )
    except Exception as exc:
        result = {"ok": False, "error": type(exc).__name__, "message": str(exc)}
    else:
        result = {"ok": True, "event_id": event_id, "created": created}
    print("RESULT:" + json.dumps(result, sort_keys=True))

asyncio.run(main())
"""

_PROCESS_MARK_STARTED = r"""
import asyncio
import json
import sys
import time
from pathlib import Path
from atlas.engine.kernel.inbox import DurableInbox

async def main():
    home, session, event_id, ready, gate, run_id = sys.argv[1:]
    inbox = DurableInbox(Path(home), session)
    await inbox.restore()
    Path(ready).write_text("ready", encoding="utf-8")
    while not Path(gate).exists():
        time.sleep(0.01)
    started = await inbox.mark_started(event_id, lane="next-turn", run_id=run_id)
    item = await inbox.peek("next-turn")
    print("RESULT:" + json.dumps({
        "started": started,
        "owner_run_id": item.started_run_id if item is not None else None,
    }, sort_keys=True))

asyncio.run(main())
"""

_PROCESS_INBOX_BOUNDARY = r"""
import asyncio
import json
import sys
import time
from pathlib import Path
from atlas.engine.kernel.inbox import DurableInbox

async def main():
    home, session, event_id, action, run_id, ready, gate, result_path = sys.argv[1:]
    inbox = DurableInbox(Path(home), session)
    await inbox.restore()
    Path(ready).write_text("ready", encoding="utf-8")
    while not Path(gate).exists():
        time.sleep(0.01)
    if action == "start":
        result = await inbox.mark_started(event_id, lane="next-turn", run_id=run_id)
    else:
        result = await inbox.cancel(event_id, lane="next-turn")
    Path(result_path).write_text(json.dumps({"result": result}), encoding="utf-8")

asyncio.run(main())
"""


def _run_cross_process_enqueue_race(tmp_path, session_id, contents):
    home = tmp_path / "engine"
    race_dir = tmp_path / "race"
    race_dir.mkdir()
    gate = race_dir / "go"
    ready = [race_dir / f"ready-{index}" for index in range(len(contents))]
    children = []
    try:
        for index, content in enumerate(contents):
            children.append(subprocess.Popen(
                [
                    sys.executable, "-c", _PROCESS_ENQUEUE, str(home), session_id,
                    str(ready[index]), str(gate), "same-cross-process-request",
                    "next-turn", content,
                ],
                cwd=Path(__file__).resolve().parents[1],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            ))

        deadline = time.monotonic() + 20
        while not all(path.exists() for path in ready):
            failed = [child for child in children if child.poll() is not None]
            if failed:
                details = [child.communicate() for child in failed]
                raise AssertionError(f"enqueue child exited before barrier: {details!r}")
            if time.monotonic() >= deadline:
                raise AssertionError("enqueue children did not reach the write barrier")
            time.sleep(0.02)

        gate.write_text("go", encoding="utf-8")
        results = []
        for child in children:
            stdout, stderr = child.communicate(timeout=20)
            assert child.returncode == 0, f"child exit={child.returncode}; stderr={stderr[-2000:]}"
            result_line = next((line for line in reversed(stdout.splitlines())
                                if line.startswith("RESULT:")), None)
            assert result_line is not None, f"missing child result; stderr={stderr[-2000:]}"
            results.append(json.loads(result_line.removeprefix("RESULT:")))
        return home, results
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=5)


def _run_cross_process_start_race(tmp_path, session_id, event_id):
    home = tmp_path / "engine"
    race_dir = tmp_path / "start-race"
    race_dir.mkdir()
    gate = race_dir / "go"
    ready = [race_dir / f"ready-{index}" for index in range(2)]
    children = []
    try:
        for index in range(2):
            children.append(subprocess.Popen(
                [
                    sys.executable, "-c", _PROCESS_MARK_STARTED, str(home), session_id,
                    event_id, str(ready[index]), str(gate), f"worker-run-{index}",
                ],
                cwd=Path(__file__).resolve().parents[1],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            ))

        deadline = time.monotonic() + 20
        while not all(path.exists() for path in ready):
            failed = [child for child in children if child.poll() is not None]
            if failed:
                details = [child.communicate() for child in failed]
                raise AssertionError(f"claim child exited before barrier: {details!r}")
            if time.monotonic() >= deadline:
                raise AssertionError("claim children did not reach the write barrier")
            time.sleep(0.02)

        gate.write_text("go", encoding="utf-8")
        results = []
        for child in children:
            stdout, stderr = child.communicate(timeout=20)
            assert child.returncode == 0, f"child exit={child.returncode}; stderr={stderr[-2000:]}"
            result_line = next((line for line in reversed(stdout.splitlines())
                                if line.startswith("RESULT:")), None)
            assert result_line is not None, f"missing child result; stderr={stderr[-2000:]}"
            results.append(json.loads(result_line.removeprefix("RESULT:")))
        return home, results
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=5)


def _run_cross_process_cancel_start_order(tmp_path, session_id, event_id, first_action):
    race_dir = tmp_path / f"boundary-{first_action}"
    race_dir.mkdir()
    actions = ("start", "cancel")
    gates = {action: race_dir / f"{action}.go" for action in actions}
    ready = {action: race_dir / f"{action}.ready" for action in actions}
    results = {action: race_dir / f"{action}.result" for action in actions}
    children = {}
    try:
        for action in actions:
            children[action] = subprocess.Popen(
                [
                    sys.executable, "-c", _PROCESS_INBOX_BOUNDARY,
                    str(tmp_path / "engine"), session_id, event_id, action,
                    "boundary-worker-run", str(ready[action]), str(gates[action]),
                    str(results[action]),
                ],
                cwd=Path(__file__).resolve().parents[1],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )

        deadline = time.monotonic() + 20
        while not all(path.exists() for path in ready.values()):
            failed = [child for child in children.values() if child.poll() is not None]
            if failed:
                details = [child.communicate() for child in failed]
                raise AssertionError(f"boundary child exited before stale snapshot: {details!r}")
            if time.monotonic() >= deadline:
                raise AssertionError("boundary children did not restore the queued snapshot")
            time.sleep(0.02)

        gates[first_action].write_text("go", encoding="utf-8")
        first_deadline = time.monotonic() + 10
        while not results[first_action].exists():
            if children[first_action].poll() is not None:
                raise AssertionError(f"first {first_action} operation exited without a result")
            if time.monotonic() >= first_deadline:
                raise AssertionError(f"first {first_action} operation did not finish")
            time.sleep(0.01)
        gates["cancel" if first_action == "start" else "start"].write_text("go", encoding="utf-8")

        outcomes = {}
        for action, child in children.items():
            stdout, stderr = child.communicate(timeout=20)
            assert child.returncode == 0, f"{action} child exit={child.returncode}; stderr={stderr[-2000:]}"
            outcomes[action] = json.loads(results[action].read_text(encoding="utf-8"))["result"]
        return tmp_path / "engine", outcomes
    finally:
        for child in children.values():
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=5)


@pytest.mark.unit
def test_parallel_inboxes_share_one_durable_enqueue_receipt(tmp_path):
    async def scenario():
        home = tmp_path / "engine"
        first = DurableInbox(home, "parallel-enqueue-session")
        second = DurableInbox(home, "parallel-enqueue-session")
        await asyncio.gather(first.restore(), second.restore())

        receipts = await asyncio.gather(
            first.inject_with_receipt(
                "one durable prompt", lane="next-turn", request_id="parallel-request",
            ),
            second.inject_with_receipt(
                "one durable prompt", lane="next-turn", request_id="parallel-request",
            ),
        )

        assert receipts[0][0] == receipts[1][0]
        assert sorted(created for _event_id, created in receipts) == [False, True]
        assert (await second.peek("next-turn")).event_id == receipts[0][0]
        events = await asyncio.to_thread(
            read_session_events, home, "parallel-enqueue-session", after_seq=0, limit=100,
        )
        enqueued = [event for event in events if event.get("event_type") == "inbox.enqueued"]
        assert len(enqueued) == 1
        assert enqueued[0]["payload"] == {
            "event_id": receipts[0][0],
            "lane": "next-turn",
            "content": "one durable prompt",
            "request_id": "parallel-request",
        }

    asyncio.run(scenario())


@pytest.mark.unit
def test_parallel_inboxes_reject_conflicting_payload_for_same_request_id(tmp_path):
    async def scenario():
        home = tmp_path / "engine"
        first = DurableInbox(home, "parallel-conflict-session")
        second = DurableInbox(home, "parallel-conflict-session")
        await asyncio.gather(first.restore(), second.restore())

        results = await asyncio.gather(
            first.inject_with_receipt(
                "payload A", lane="next-turn", request_id="one-request-id",
            ),
            second.inject_with_receipt(
                "payload B", lane="next-turn", request_id="one-request-id",
            ),
            return_exceptions=True,
        )

        successes = [result for result in results if not isinstance(result, Exception)]
        conflicts = [result for result in results if isinstance(result, ValueError)]
        assert len(successes) == 1
        assert len(conflicts) == 1
        assert "different payload" in str(conflicts[0])
        events = await asyncio.to_thread(
            read_session_events, home, "parallel-conflict-session", after_seq=0, limit=100,
        )
        enqueued = [event for event in events if event.get("event_type") == "inbox.enqueued"]
        assert len(enqueued) == 1
        assert enqueued[0]["payload"]["content"] in {"payload A", "payload B"}

    asyncio.run(scenario())


@pytest.mark.unit
def test_separate_processes_share_one_durable_enqueue_receipt(tmp_path):
    session_id = "cross-process-enqueue-session"
    home, results = _run_cross_process_enqueue_race(
        tmp_path, session_id, ["one durable prompt", "one durable prompt"],
    )

    assert all(result["ok"] for result in results)
    assert results[0]["event_id"] == results[1]["event_id"]
    assert sorted(result["created"] for result in results) == [False, True]
    events = read_session_events(home, session_id, after_seq=0, limit=100)
    enqueued = [event for event in events if event.get("event_type") == "inbox.enqueued"]
    assert len(enqueued) == 1
    assert enqueued[0]["payload"]["request_id"] == "same-cross-process-request"


@pytest.mark.unit
def test_separate_processes_reject_conflicting_enqueue_payload(tmp_path):
    session_id = "cross-process-conflict-session"
    home, results = _run_cross_process_enqueue_race(
        tmp_path, session_id, ["payload A", "payload B"],
    )

    successes = [result for result in results if result["ok"]]
    conflicts = [result for result in results if result.get("error") == "ValueError"]
    assert len(successes) == 1
    assert len(conflicts) == 1
    assert "different payload" in conflicts[0]["message"]
    events = read_session_events(home, session_id, after_seq=0, limit=100)
    enqueued = [event for event in events if event.get("event_type") == "inbox.enqueued"]
    assert len(enqueued) == 1
    assert enqueued[0]["payload"]["content"] in {"payload A", "payload B"}


@pytest.mark.unit
def test_separate_process_workers_atomically_claim_one_pending_item(tmp_path):
    session_id = "cross-process-worker-claim-session"
    home = tmp_path / "engine"

    async def seed():
        inbox = DurableInbox(home, session_id)
        await inbox.restore()
        return (await inbox.inject_with_receipt(
            "one durable prompt", lane="next-turn", request_id="claim-request",
        ))[0]

    event_id = asyncio.run(seed())
    home, results = _run_cross_process_start_race(tmp_path, session_id, event_id)

    assert sorted(result["started"] for result in results) == [False, True]
    owner_run_ids = {result["owner_run_id"] for result in results}
    assert len(owner_run_ids) == 1
    owner_run_id = next(iter(owner_run_ids))
    assert owner_run_id in {"worker-run-0", "worker-run-1"}
    events = read_session_events(home, session_id, after_seq=0, limit=100)
    started = [
        event for event in events
        if event.get("event_type") == "inbox.started"
        and event.get("payload", {}).get("event_id") == event_id
    ]
    assert len(started) == 1
    assert started[0]["payload"]["run_id"] == owner_run_id


@pytest.mark.parametrize("first_action", ["start", "cancel"])
@pytest.mark.unit
def test_separate_process_cancel_and_start_share_one_lifecycle_boundary(tmp_path, first_action):
    session_id = f"cross-process-{first_action}-boundary-session"
    home = tmp_path / "engine"

    async def seed():
        inbox = DurableInbox(home, session_id)
        await inbox.restore()
        return (await inbox.inject_with_receipt(
            "one durable prompt", lane="next-turn", request_id="boundary-request",
        ))[0]

    event_id = asyncio.run(seed())
    home, outcomes = _run_cross_process_cancel_start_order(
        tmp_path, session_id, event_id, first_action,
    )
    expected = {"start": True, "cancel": False} if first_action == "start" else {
        "start": False, "cancel": True,
    }
    assert outcomes == expected

    events = read_session_events(home, session_id, after_seq=0, limit=100)
    lifecycle = [
        event for event in events
        if event.get("event_type") in {"inbox.started", "inbox.cancelled"}
        and event.get("payload", {}).get("event_id") == event_id
    ]
    assert [event["event_type"] for event in lifecycle] == [
        "inbox.started" if first_action == "start" else "inbox.cancelled",
    ]


@pytest.mark.unit
def test_inbox_refresh_after_ack_observes_another_process_enqueue(tmp_path):
    async def scenario():
        home = tmp_path / "engine"
        first = DurableInbox(home, "incremental-refresh-session")
        second = DurableInbox(home, "incremental-refresh-session")

        first_event, created = await first.inject_with_receipt(
            "first queued item", lane="next-turn", request_id="refresh-first",
        )
        assert created
        assert await first.mark_started(
            first_event, lane="next-turn", run_id="refresh-first-run",
        )
        await second.restore()

        second_event, created = await second.inject_with_receipt(
            "second queued item", lane="next-turn", request_id="refresh-second",
        )
        assert created and second_event != first_event
        assert await first.ack(first_event, lane="next-turn")

        item = await first.peek("next-turn")
        assert item is not None
        assert item.event_id == second_event
        assert item.request_id == "refresh-second"
        assert item.content == "second queued item"

    asyncio.run(scenario())


@pytest.mark.unit
def test_inbox_event_page_filters_history_and_advances_cursor_across_other_events(tmp_path):
    from atlas.engine.session_sync import append_session_event, read_session_inbox_events

    async def scenario():
        home = tmp_path / "engine"
        session_id = "inbox-event-page-session"
        inbox = DurableInbox(home, session_id)
        append_session_event(home, session_id, "model/attempt", {"status": "started"})
        event_id, created = await inbox.inject_with_receipt(
            "queued item", lane="next-turn", request_id="event-page-request",
        )
        assert created
        assert await inbox.mark_started(event_id, lane="next-turn", run_id="event-page-run")
        high_water = append_session_event(home, session_id, "turn/end", {"turn_id": "other"})

        first, first_cursor = read_session_inbox_events(
            home, session_id, after_seq=0, limit=1,
        )
        second, second_cursor = read_session_inbox_events(
            home, session_id, after_seq=first_cursor, limit=1,
        )
        final, final_cursor = read_session_inbox_events(
            home, session_id, after_seq=second_cursor, limit=1,
        )

        assert [row["event_type"] for row in first] == ["inbox.enqueued"]
        assert [row["event_type"] for row in second] == ["inbox.started"]
        assert first_cursor < second_cursor < high_water
        assert final == []
        assert final_cursor == high_water

    asyncio.run(scenario())
