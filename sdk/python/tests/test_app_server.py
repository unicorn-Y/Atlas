from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import queue
import threading

import pytest

from atlas_sdk.app_server import AppServer


pytestmark = pytest.mark.unit


class _Stdout:
    def __init__(self):
        self.lines: queue.Queue[str] = queue.Queue()

    def readline(self):
        return self.lines.get()


class _Stdin:
    def __init__(self, process):
        self.process = process

    def write(self, line):
        self.process.receive(json.loads(line))
        return len(line)

    def flush(self):
        pass

    def close(self):
        self.process.stdout.lines.put("")


class _ProtocolProcess:
    def __init__(self):
        self.stdout = _Stdout()
        self.stdin = _Stdin(self)
        self.stderr = None
        self.returncode = None
        self.lock = threading.Lock()
        self.next_session = 0
        self.prompts = []
        self.client_replies = []
        self.waits = []
        self.event_requests = []
        self.pending_request_calls = []
        self.task_calls = []

    def _emit(self, message):
        self.stdout.lines.put(json.dumps({"jsonrpc": "2.0", **message}) + "\n")

    def receive(self, message):
        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params") or {}
        if method == "initialize":
            self._emit({"id": request_id, "result": {"protocolVersion": 1}})
        elif method == "session/start":
            with self.lock:
                self.next_session += 1
                index = self.next_session
            self._emit({"id": request_id, "result": {
                "session_id": f"sid-{index}",
                "conversation_id": params.get("conversation_id") or f"conv-{index}",
                "workspace": params["workspace"],
            }})
        elif method == "session/prompt":
            with self.lock:
                self.prompts.append((request_id, params["session_id"], params["prompt"]))
                prompts = list(self.prompts)
            if len(prompts) == 2:
                # Deliberately interleave notifications and complete in reverse request order.
                for _request, session_id, prompt in prompts:
                    self._emit({"method": "session/event", "params": {
                        "session_id": session_id,
                        "event": {"type": "chunk", "content": prompt},
                    }})
                    self._emit({"method": "approval/request", "params": {
                        "session_id": session_id, "event_id": f"approval-{session_id}",
                    }})
                    self._emit({"method": "input/request", "params": {
                        "session_id": session_id, "call_id": f"input-{session_id}",
                        "prompt": f"question-{session_id}",
                    }})
                for prompt_id, session_id, prompt in reversed(prompts):
                    self._emit({"id": prompt_id, "result": {
                        "session_id": session_id, "text": f"answer:{prompt}", "status": "completed",
                    }})
        elif method in {"approval/response", "input/response"}:
            with self.lock:
                self.client_replies.append((method, params))
            self._emit({"id": request_id, "result": {"accepted": True}})
        elif method == "session/close":
            self._emit({"id": request_id, "result": {}})
        elif method == "session/wait":
            with self.lock:
                self.waits.append(params["session_id"])
            self._emit({"id": request_id, "result": {}})
        elif method == "session/events":
            with self.lock:
                self.event_requests.append(dict(params))
            self._emit({"id": request_id, "result": {
                "session_id": params["session_id"],
                "conversation_id": "conv-events",
                "after_seq": params["after_seq"],
                "events": [
                    {"seq": 4, "event_type": "inbox.enqueued", "payload": {"event_id": "item-1"}},
                    {"seq": 5, "event_type": "inbox.started", "payload": {"event_id": "item-1"}},
                ][:params["limit"]],
                "next_cursor": 5 if params["limit"] >= 2 else None,
            }})
        elif method == "session/pending_requests":
            with self.lock:
                self.pending_request_calls.append(params["session_id"])
            self._emit({"id": request_id, "result": {
                "session_id": params["session_id"],
                "requests": [{
                    "request_id": "request-current", "session_id": params["session_id"],
                    "kind": "input", "status": "pending", "prompt": "Continue?",
                    "options": ["yes", "no"],
                }, {
                    "request_id": "request-old", "session_id": params["session_id"],
                    "kind": "approval", "status": "invalidated", "tool_name": "write_file",
                }],
            }})
        elif method in {"session/task_status", "session/task_cancel"}:
            with self.lock:
                self.task_calls.append((method, dict(params)))
            self._emit({"id": request_id, "result": {
                "session_id": params["session_id"],
                "request_id": params["request_id"],
                "status": "too_late" if method == "session/task_cancel" else "completed",
                "event_id": "event-task-1", "run_id": "run-task-1",
            }})
        elif method == "session/retry_recovery":
            self._emit({"id": request_id, "result": {
                "session_id": params["session_id"], "conversation_id": "conv-recovery",
                "state": "outcome_unknown", "run_id": "run-recovery",
                "attempt_id": "attempt-recovery", "attempt": 2,
                "retry_budget_attempts_remaining": 1,
                "recommended_action": "do_not_replay",
            }})

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = 0
        return self.returncode

    def terminate(self):
        self.returncode = 0

    def kill(self):
        self.returncode = -9


class _AttemptProtocolProcess(_ProtocolProcess):
    def receive(self, message):
        if message.get("method") != "session/prompt":
            return super().receive(message)
        params = message.get("params") or {}
        session_id = params["session_id"]
        request_id = message["id"]
        for event in (
            {"type": "chunk", "content": "OLD", "attempt": 1, "attempt_id": "attempt-old"},
            {"type": "message.rollback", "attempt": 1, "attempt_id": "attempt-old"},
            {"type": "chunk", "content": "NEW", "attempt": 2, "attempt_id": "attempt-new"},
        ):
            self._emit({"method": "session/event", "params": {
                "session_id": session_id, "event": event,
            }})
        self._emit({"id": request_id, "result": {
            "session_id": session_id, "text": "NEW", "status": "completed",
        }})


def test_concurrent_session_prompts_route_interleaved_responses_and_events(monkeypatch):
    process = _ProtocolProcess()
    monkeypatch.setattr("atlas_sdk.app_server.subprocess.Popen", lambda *args, **kwargs: process)
    server = AppServer("atlas", workspace=".").start()
    first = server.new_session()
    second = server.new_session()
    events = {first.session_id: [], second.session_id: []}

    def prompt(session, text):
        return server.prompt(
            session.session_id,
            text,
            on_event=events[session.session_id].append,
            approve=lambda params: params["session_id"] == first.session_id,
            answer=lambda params: f"reply:{params['session_id']}",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(prompt, first, "first")
        second_future = pool.submit(prompt, second, "second")
        first_result = first_future.result(timeout=3)
        second_result = second_future.result(timeout=3)

    assert (first_result.text, second_result.text) == ("answer:first", "answer:second")
    assert events[first.session_id] == [{"type": "chunk", "content": "first"}]
    assert events[second.session_id] == [{"type": "chunk", "content": "second"}]
    assert sorted((method, params["event_id"], params["choice"])
                  for method, params in process.client_replies if method == "approval/response") == [
        ("approval/response", "approval-sid-1", "allow"),
        ("approval/response", "approval-sid-2", "deny"),
    ]
    assert sorted((method, params["call_id"], params["value"])
                  for method, params in process.client_replies if method == "input/response") == [
        ("input/response", "input-sid-1", "reply:sid-1"),
        ("input/response", "input-sid-2", "reply:sid-2"),
    ]
    server.close()


def test_prompt_keeps_rollback_event_and_returns_only_committed_attempt(monkeypatch):
    process = _AttemptProtocolProcess()
    monkeypatch.setattr("atlas_sdk.app_server.subprocess.Popen", lambda *args, **kwargs: process)
    server = AppServer("atlas", workspace=".").start()
    session = server.new_session()
    events = []

    result = server.prompt(session.session_id, "retry", on_event=events.append)

    assert result.text == "NEW"
    assert [event["type"] for event in events] == ["chunk", "message.rollback", "chunk"]
    assert events[1]["attempt_id"] == "attempt-old"
    server.close()


def test_sdk_reads_typed_retry_recovery_state(monkeypatch):
    process = _ProtocolProcess()
    monkeypatch.setattr("atlas_sdk.app_server.subprocess.Popen", lambda *args, **kwargs: process)
    server = AppServer("atlas", workspace=".").start()
    session = server.new_session(conversation_id="conv-recovery")
    try:
        recovery = server.retry_recovery(session.session_id)
        from atlas_sdk.app_server import AppServerRetryRecovery

        assert isinstance(recovery, AppServerRetryRecovery)
        assert recovery.conversation_id == session.conversation_id == "conv-recovery"
        assert recovery.state == "outcome_unknown"
        assert recovery.run_id == "run-recovery"
        assert recovery.retry_budget_attempts_remaining == 1
        assert recovery.recommended_action == "do_not_replay"
    finally:
        server.close()


def test_sdk_wait_uses_session_settle_barrier(monkeypatch):
    process = _ProtocolProcess()
    monkeypatch.setattr("atlas_sdk.app_server.subprocess.Popen", lambda *args, **kwargs: process)
    server = AppServer("atlas", workspace=".").start()
    session = server.new_session(conversation_id="conv-wait")
    try:
        assert server.wait(session.session_id) is None
        assert process.waits == [session.session_id]
    finally:
        server.close()


def test_sdk_reads_typed_durable_event_page_and_validates_cursor(monkeypatch):
    process = _ProtocolProcess()
    monkeypatch.setattr("atlas_sdk.app_server.subprocess.Popen", lambda *args, **kwargs: process)
    server = AppServer("atlas", workspace=".").start()
    session = server.new_session(conversation_id="conv-events")
    try:
        from atlas_sdk import AppServerEventPage, AppServerSessionEvent

        page = server.session_events(session.session_id, after_seq=3, limit=2)
        assert isinstance(page, AppServerEventPage)
        assert page.conversation_id == "conv-events"
        assert isinstance(page.events[0], AppServerSessionEvent)
        assert [event.seq for event in page.events] == [4, 5]
        assert page.next_cursor == 5
        assert process.event_requests == [{
            "session_id": session.session_id, "after_seq": 3, "limit": 2,
        }]
        with pytest.raises(ValueError, match="limit"):
            server.session_events(session.session_id, after_seq=3, limit=0)
        with pytest.raises(ValueError, match="after_seq"):
            server.session_events(session.session_id, after_seq=-1)
    finally:
        server.close()


def test_sdk_reads_pending_request_and_uses_request_identity_for_response(monkeypatch):
    process = _ProtocolProcess()
    monkeypatch.setattr("atlas_sdk.app_server.subprocess.Popen", lambda *args, **kwargs: process)
    server = AppServer("atlas", workspace=".").start()
    session = server.new_session(conversation_id="conv-pending")
    try:
        from atlas_sdk import AppServerPendingRequest

        requests = server.pending_requests(session.session_id)
        assert len(requests) == 2
        assert isinstance(requests[0], AppServerPendingRequest)
        assert requests[0].request_id == "request-current"
        assert requests[0].kind == "input"
        assert requests[0].prompt == "Continue?"
        assert requests[0].options == ("yes", "no")
        server.respond_input("request-current", "yes")
        server.respond_approval("request-old", "allow")
        assert process.pending_request_calls == [session.session_id]
        assert process.client_replies[-2:] == [
            ("input/response", {"request_id": "request-current", "value": "yes"}),
            ("approval/response", {"request_id": "request-old", "choice": "allow"}),
        ]
        with pytest.raises(ValueError, match="request_id"):
            server.respond_input("", "yes")
        with pytest.raises(ValueError, match="allow.*deny"):
            server.respond_approval("request-current", "maybe")
    finally:
        server.close()


def test_sdk_queries_task_status_and_returns_typed_cancel_result(monkeypatch):
    process = _ProtocolProcess()
    monkeypatch.setattr("atlas_sdk.app_server.subprocess.Popen", lambda *args, **kwargs: process)
    server = AppServer("atlas", workspace=".").start()
    session = server.new_session(conversation_id="conv-task-status")
    try:
        from atlas_sdk import AppServerTaskStatus

        status = server.task_status(session.session_id, "task-1")
        assert isinstance(status, AppServerTaskStatus)
        assert status.status == "completed"
        assert status.event_id == "event-task-1"
        result = server.cancel_task(session.session_id, "task-1")
        assert isinstance(result, AppServerTaskStatus)
        assert result.status == "too_late"
        assert process.task_calls == [
            ("session/task_status", {"session_id": session.session_id, "request_id": "task-1"}),
            ("session/task_cancel", {"session_id": session.session_id, "request_id": "task-1"}),
        ]
        with pytest.raises(ValueError, match="request_id"):
            server.task_status(session.session_id, "")
    finally:
        server.close()
