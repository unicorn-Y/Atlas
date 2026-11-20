"""Typed client for Atlas' versioned JSON-RPC app-server stdio protocol."""
from __future__ import annotations

from dataclasses import dataclass
from collections import deque
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
from typing import Any, Callable, Literal, Sequence


@dataclass(frozen=True)
class AppServerSession:
    session_id: str
    conversation_id: str
    workspace: str


@dataclass(frozen=True)
class AppServerResult:
    session_id: str
    text: str
    status: Literal["completed", "failed", "cancelled"]


@dataclass(frozen=True)
class AppServerEnqueueReceipt:
    session_id: str
    conversation_id: str
    request_id: str
    event_id: str
    status: Literal["queued"]


@dataclass(frozen=True)
class AppServerRetryRecovery:
    session_id: str
    conversation_id: str
    state: Literal[
        "none", "retry_scheduled_not_started", "outcome_unknown", "settled", "state_unknown",
    ]
    run_id: str | None
    attempt_id: str | None
    attempt: int | None
    retry_budget_attempts_remaining: int | None
    retry_budget_wait_s_remaining: float | None
    recommended_action: Literal[
        "none", "explicit_resume_required", "do_not_replay", "manual_review",
    ]


@dataclass(frozen=True)
class AppServerSessionEvent:
    seq: int
    event_type: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class AppServerEventPage:
    session_id: str
    conversation_id: str
    after_seq: int
    events: tuple[AppServerSessionEvent, ...]
    next_cursor: int | None


@dataclass(frozen=True)
class AppServerPendingRequest:
    request_id: str
    session_id: str
    kind: Literal["input", "approval", "unknown"]
    status: Literal["pending", "invalidated"]
    prompt: str | None = None
    options: tuple[str, ...] = ()
    tool_name: str | None = None
    arguments: dict[str, Any] | None = None


@dataclass(frozen=True)
class AppServerTaskStatus:
    request_id: str
    session_id: str
    status: Literal[
        "queued", "running", "cancelling", "completed", "failed", "cancelled",
        "outcome_unknown", "too_late",
    ]
    event_id: str | None = None
    run_id: str | None = None


class AppServerError(RuntimeError):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


class AppServer:
    """Launch and drive `atlas app-server` using newline-delimited JSON-RPC 2.0."""

    protocol_version = 1

    def __init__(self, executable: str | Sequence[str] = "atlas", *, workspace: str | os.PathLike[str] | None = None,
                 env: dict[str, str] | None = None, request_timeout: float | None = None):
        self.command = [executable] if isinstance(executable, str) else list(executable)
        if not self.command:
            raise ValueError("executable command must not be empty")
        self.workspace = str(Path(workspace).resolve()) if workspace is not None else str(Path.cwd())
        self.env = {**os.environ, **(env or {})}
        if request_timeout is not None and request_timeout <= 0:
            raise ValueError("request_timeout must be positive or None")
        self.request_timeout = request_timeout
        self._process: subprocess.Popen[str] | None = None
        self._next_id = 0
        self._session_ids: set[str] = set()
        self._state_lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._pending: dict[int, dict[str, Any]] = {}
        self._session_notifications: dict[str, queue.Queue[dict[str, Any]]] = {}
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._stderr_tail: deque[str] = deque(maxlen=200)
        self._reader_error: BaseException | None = None

    def start(self) -> "AppServer":
        if self._process is not None and self._process.poll() is None:
            return self
        self._process = subprocess.Popen(
            [*self.command, "app-server", "--workspace", self.workspace],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", env=self.env, bufsize=1,
        )
        self._reader_error = None
        self._reader_thread = threading.Thread(
            target=self._read_dispatch_loop, name="atlas-sdk-app-server-reader", daemon=True,
        )
        self._reader_thread.start()
        self._stderr_tail.clear()
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr, name="atlas-sdk-app-server-stderr", daemon=True,
        )
        self._stderr_thread.start()
        try:
            result = self._request("initialize", {"protocolVersion": self.protocol_version})
            version = result.get("protocolVersion")
            if version != self.protocol_version:
                raise AppServerError(-32002, f"Atlas app-server protocol mismatch: expected {self.protocol_version}, got {version!r}")
        except BaseException:
            self.close()
            raise
        return self

    def _drain_stderr(self) -> None:
        process = self._process
        stream = process.stderr if process is not None else None
        if stream is None:
            return
        try:
            for line in stream:
                self._stderr_tail.append(line.rstrip("\r\n"))
        except (OSError, ValueError):
            return

    def _write(self, message: dict[str, Any]) -> None:
        if not self._process or not self._process.stdin:
            raise RuntimeError("AppServer.start() must be called first")
        with self._write_lock:
            self._process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
            self._process.stdin.flush()

    def _next_request_id(self) -> int:
        with self._state_lock:
            self._next_id += 1
            return self._next_id

    def _read(self) -> dict[str, Any]:
        if not self._process or not self._process.stdout:
            raise RuntimeError("AppServer.start() must be called first")
        line = self._process.stdout.readline()
        if not line:
            error = "\n".join(self._stderr_tail)
            raise RuntimeError(f"Atlas app-server exited: {error.strip() or self._process.poll()}")
        value = json.loads(line)
        if not isinstance(value, dict) or value.get("jsonrpc") != "2.0":
            raise RuntimeError("Atlas app-server returned an invalid JSON-RPC message")
        return value

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id, pending = self._begin_request(method, params)
        if self._reader_thread is None:
            try:
                while True:
                    message = self._read()
                    if message.get("id") == request_id:
                        pending["message"] = message
                        pending["event"].set()
                        break
            except BaseException:
                with self._state_lock:
                    self._pending.pop(request_id, None)
                raise
        if not pending["event"].wait(timeout=self.request_timeout):
            with self._state_lock:
                self._pending.pop(request_id, None)
            raise TimeoutError(f"Atlas app-server {method} request timed out")
        with self._state_lock:
            self._pending.pop(request_id, None)
        if pending.get("error") is not None:
            raise RuntimeError(f"Atlas app-server reader failed: {pending['error']}")
        message = pending.get("message") or {}
        if isinstance(message.get("error"), dict):
            error = message["error"]
            raise AppServerError(int(error.get("code", -32603)), str(error.get("message", "JSON-RPC error")))
        result = message.get("result")
        return result if isinstance(result, dict) else {}

    def _begin_request(self, method: str, params: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        request_id = self._next_request_id()
        pending: dict[str, Any] = {"event": threading.Event(), "message": None, "error": None}
        with self._state_lock:
            self._pending[request_id] = pending
        try:
            self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        except BaseException:
            with self._state_lock:
                self._pending.pop(request_id, None)
            raise
        return request_id, pending

    def _read_dispatch_loop(self) -> None:
        error: BaseException | None = None
        try:
            while True:
                message = self._read()
                method = message.get("method")
                if isinstance(method, str):
                    params = message.get("params") if isinstance(message.get("params"), dict) else {}
                    session_id = str(params.get("session_id") or params.get("sessionId") or "")
                    with self._state_lock:
                        notifications = self._session_notifications.get(session_id)
                    if notifications is not None:
                        notifications.put(message)
                    continue
                request_id = message.get("id")
                if isinstance(request_id, int):
                    with self._state_lock:
                        pending = self._pending.get(request_id)
                    if pending is not None:
                        pending["message"] = message
                        pending["event"].set()
        except BaseException as exc:
            error = exc
        finally:
            with self._state_lock:
                self._reader_error = error or RuntimeError("app-server output closed")
                pending_requests = list(self._pending.values())
                for pending in pending_requests:
                    if not pending["event"].is_set():
                        pending["error"] = self._reader_error
                        pending["event"].set()

    def _send_request(self, method: str, params: dict[str, Any]) -> int:
        request_id = self._next_request_id()
        self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        return request_id

    def list_tools(self) -> list[dict[str, Any]]:
        return list(self._request("tools/list", {}).get("tools", []))

    def new_session(self, *, workspace: str | os.PathLike[str] | None = None,
                    conversation_id: str | None = None) -> AppServerSession:
        params: dict[str, Any] = {"workspace": str(Path(workspace).resolve()) if workspace else self.workspace}
        if conversation_id:
            params["conversation_id"] = conversation_id
        result = self._request("session/start", params)
        session_id = str(result["session_id"])
        self._session_ids.add(session_id)
        return AppServerSession(session_id, str(result["conversation_id"]), str(result["workspace"]))

    def get_working_directory(self, session_id: str) -> str:
        """Return the session's effective local execution directory."""
        value = str(session_id or "").strip()
        if not value:
            raise ValueError("session_id must not be empty")
        result = self._request("session/working-directory/get", {"session_id": value})
        directory = str(result.get("working_directory") or "")
        if not directory:
            raise RuntimeError("Atlas app-server returned an empty working directory")
        return directory

    def set_working_directory(
        self, session_id: str, working_directory: str | os.PathLike[str],
    ) -> str:
        """Set an existing directory within the session's trusted local workspace."""
        value = str(session_id or "").strip()
        if not value:
            raise ValueError("session_id must not be empty")
        result = self._request("session/working-directory/set", {
            "session_id": value,
            "working_directory": str(Path(working_directory).expanduser().resolve()),
        })
        directory = str(result.get("working_directory") or "")
        if not directory:
            raise RuntimeError("Atlas app-server returned an empty working directory")
        return directory

    def enqueue(self, session_id: str, prompt: str, *, request_id: str) -> AppServerEnqueueReceipt:
        """Persist a next-turn user prompt and return its idempotent receipt."""
        value = str(prompt or "").strip()
        key = str(request_id or "").strip()
        if not value:
            raise ValueError("prompt must not be empty")
        if not key or len(key) > 256:
            raise ValueError("request_id must be non-empty and at most 256 characters")
        result = self._request("session/enqueue", {
            "session_id": str(session_id), "prompt": value, "request_id": key,
        })
        if (str(result.get("session_id") or "") != str(session_id)
                or str(result.get("request_id") or "") != key
                or str(result.get("status") or "") != "queued"
                or not result.get("conversation_id") or not result.get("event_id")):
            raise RuntimeError("Atlas app-server returned an invalid enqueue receipt")
        return AppServerEnqueueReceipt(
            session_id=str(result["session_id"]),
            conversation_id=str(result["conversation_id"]),
            request_id=str(result["request_id"]),
            event_id=str(result["event_id"]),
            status="queued",
        )

    def wait(self, session_id: str) -> None:
        """Wait until the app-server reports this session's active worker settled."""
        value = str(session_id or "").strip()
        if not value:
            raise ValueError("session_id must not be empty")
        self._request("session/wait", {"session_id": value})

    def session_events(self, session_id: str, *, after_seq: int = 0,
                       limit: int = 100) -> AppServerEventPage:
        """Read a bounded, replayable page of this session's durable events."""
        value = str(session_id or "").strip()
        if not value:
            raise ValueError("session_id must not be empty")
        if type(after_seq) is not int or after_seq < 0:
            raise ValueError("after_seq must be a non-negative integer")
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        result = self._request("session/events", {
            "session_id": value, "after_seq": after_seq, "limit": limit,
        })
        if str(result.get("session_id") or "") != value:
            raise RuntimeError("Atlas app-server returned events for another session")
        conversation_id = str(result.get("conversation_id") or "")
        if not conversation_id:
            raise RuntimeError("Atlas app-server returned events without a conversation id")
        echoed_cursor = result.get("after_seq")
        if type(echoed_cursor) is not int or echoed_cursor != after_seq:
            raise RuntimeError("Atlas app-server returned an invalid event cursor")
        raw_events = result.get("events")
        if not isinstance(raw_events, list) or len(raw_events) > limit:
            raise RuntimeError("Atlas app-server returned an invalid event page")
        events: list[AppServerSessionEvent] = []
        previous_seq = after_seq
        for row in raw_events:
            if not isinstance(row, dict):
                raise RuntimeError("Atlas app-server returned a malformed session event")
            seq = row.get("seq")
            event_type = row.get("event_type")
            payload = row.get("payload")
            if (type(seq) is not int or seq <= previous_seq
                    or not isinstance(event_type, str) or not event_type
                    or not isinstance(payload, dict)):
                raise RuntimeError("Atlas app-server returned an invalid session event")
            events.append(AppServerSessionEvent(seq, event_type, dict(payload)))
            previous_seq = seq
        next_cursor = result.get("next_cursor")
        if next_cursor is not None:
            if (type(next_cursor) is not int or not events
                    or next_cursor != events[-1].seq or len(events) != limit):
                raise RuntimeError("Atlas app-server returned an invalid next event cursor")
        return AppServerEventPage(
            session_id=value, conversation_id=conversation_id,
            after_seq=after_seq, events=tuple(events), next_cursor=next_cursor,
        )

    def pending_requests(self, session_id: str) -> tuple[AppServerPendingRequest, ...]:
        """Discover live requests for this process and invalidated requests from prior processes."""
        value = str(session_id or "").strip()
        if not value:
            raise ValueError("session_id must not be empty")
        result = self._request("session/pending_requests", {"session_id": value})
        if str(result.get("session_id") or "") != value:
            raise RuntimeError("Atlas app-server returned pending requests for another session")
        raw = result.get("requests")
        if not isinstance(raw, list):
            raise RuntimeError("Atlas app-server returned an invalid pending request list")
        requests: list[AppServerPendingRequest] = []
        seen: set[str] = set()
        for row in raw:
            if not isinstance(row, dict):
                raise RuntimeError("Atlas app-server returned a malformed pending request")
            request_id = str(row.get("request_id") or "")
            row_session = str(row.get("session_id") or "")
            kind = str(row.get("kind") or "")
            status = str(row.get("status") or "")
            if (not request_id or request_id in seen
                    or (status == "pending" and row_session != value)
                    or kind not in {"input", "approval", "unknown"}
                    or status not in {"pending", "invalidated"}):
                raise RuntimeError("Atlas app-server returned an invalid pending request identity/state")
            seen.add(request_id)
            options = row.get("options", [])
            arguments = row.get("arguments")
            if not isinstance(options, list) or not all(isinstance(item, str) for item in options):
                raise RuntimeError("Atlas app-server returned invalid pending request options")
            if arguments is not None and not isinstance(arguments, dict):
                raise RuntimeError("Atlas app-server returned invalid pending approval arguments")
            prompt = row.get("prompt")
            tool_name = row.get("tool_name")
            if prompt is not None and not isinstance(prompt, str):
                raise RuntimeError("Atlas app-server returned an invalid pending input prompt")
            if tool_name is not None and not isinstance(tool_name, str):
                raise RuntimeError("Atlas app-server returned an invalid pending tool name")
            requests.append(AppServerPendingRequest(
                request_id=request_id, session_id=row_session,
                kind=kind, status=status, prompt=prompt,
                options=tuple(options), tool_name=tool_name,
                arguments=dict(arguments) if arguments is not None else None,
            ))
        return tuple(requests)

    def respond_approval(self, request_id: str, choice: Literal["allow", "deny"]) -> None:
        value = str(request_id or "").strip()
        if not value:
            raise ValueError("request_id must not be empty")
        if choice not in {"allow", "deny"}:
            raise ValueError("choice must be 'allow' or 'deny'")
        self._request("approval/response", {"request_id": value, "choice": choice})

    def respond_input(self, request_id: str, value: str) -> None:
        request_key = str(request_id or "").strip()
        if not request_key:
            raise ValueError("request_id must not be empty")
        if not isinstance(value, str):
            raise ValueError("input response value must be a string")
        self._request("input/response", {"request_id": request_key, "value": value})

    def task_status(self, session_id: str, request_id: str) -> AppServerTaskStatus:
        return self._task_request("session/task_status", session_id, request_id)

    def cancel_task(self, session_id: str, request_id: str) -> AppServerTaskStatus:
        """Cancel one enqueued task and wait for the worker's bounded cleanup response."""
        return self._task_request("session/task_cancel", session_id, request_id)

    def _task_request(self, method: str, session_id: str,
                      request_id: str) -> AppServerTaskStatus:
        session = str(session_id or "").strip()
        task = str(request_id or "").strip()
        if not session:
            raise ValueError("session_id must not be empty")
        if not task:
            raise ValueError("request_id must not be empty")
        result = self._request(method, {"session_id": session, "request_id": task})
        if (str(result.get("session_id") or "") != session
                or str(result.get("request_id") or "") != task):
            raise RuntimeError("Atlas app-server returned a task status for another request")
        status = str(result.get("status") or "")
        if status not in {
            "queued", "running", "cancelling", "completed", "failed", "cancelled",
            "outcome_unknown", "too_late",
        }:
            raise RuntimeError(f"Atlas app-server returned an unknown task status: {status}")
        event_id = str(result.get("event_id") or "")
        run_id = str(result.get("run_id") or "")
        return AppServerTaskStatus(
            request_id=task, session_id=session, status=status,  # type: ignore[arg-type]
            event_id=event_id or None, run_id=run_id or None,
        )

    def retry_recovery(self, session_id: str) -> AppServerRetryRecovery:
        """Read durable retry state without replaying a model request."""
        value = str(session_id)
        result = self._request("session/retry_recovery", {"session_id": value})
        if str(result.get("session_id") or "") != value:
            raise RuntimeError("Atlas app-server returned a retry recovery for another session")
        conversation_id = str(result.get("conversation_id") or "")
        if not conversation_id:
            raise RuntimeError("Atlas app-server returned retry recovery without a conversation id")
        state = str(result.get("state") or "")
        if state not in {
            "none", "retry_scheduled_not_started", "outcome_unknown", "settled", "state_unknown",
        }:
            raise RuntimeError(f"Atlas app-server returned an unknown retry recovery state: {state}")
        recommended_action = str(result.get("recommended_action") or "")
        if recommended_action not in {
            "none", "explicit_resume_required", "do_not_replay", "manual_review",
        }:
            raise RuntimeError("Atlas app-server returned an unknown retry recovery action")
        attempt = result.get("attempt")
        attempts_remaining = result.get("retry_budget_attempts_remaining")
        wait_remaining = result.get("retry_budget_wait_s_remaining")
        if attempt is not None and (type(attempt) is not int or attempt < 0):
            raise RuntimeError("Atlas app-server returned an invalid recovery attempt number")
        if attempts_remaining is not None and (
            type(attempts_remaining) is not int or attempts_remaining < 0
        ):
            raise RuntimeError("Atlas app-server returned an invalid retry budget remainder")
        if wait_remaining is not None and (
            type(wait_remaining) not in {int, float} or wait_remaining < 0
        ):
            raise RuntimeError("Atlas app-server returned an invalid retry wait remainder")
        run_id = str(result.get("run_id") or "")
        attempt_id = str(result.get("attempt_id") or "")
        return AppServerRetryRecovery(
            session_id=value,
            conversation_id=conversation_id,
            state=state,  # type: ignore[arg-type]
            run_id=run_id or None,
            attempt_id=attempt_id or None,
            attempt=attempt,
            retry_budget_attempts_remaining=attempts_remaining,
            retry_budget_wait_s_remaining=float(wait_remaining) if wait_remaining is not None else None,
            recommended_action=recommended_action,  # type: ignore[arg-type]
        )

    def prompt(self, session_id: str, prompt: str, *,
               on_event: Callable[[dict[str, Any]], None] | None = None,
               approve: Callable[[dict[str, Any]], bool] | None = None,
               answer: Callable[[dict[str, Any]], str] | None = None) -> AppServerResult:
        if not prompt.strip():
            raise ValueError("prompt must not be empty")
        notifications: queue.Queue[dict[str, Any]] = queue.Queue()
        with self._state_lock:
            if session_id in self._session_notifications:
                raise RuntimeError(f"Atlas app-server session already has a local prompt consumer: {session_id}")
            self._session_notifications[session_id] = notifications
        request_id: int | None = None
        deadline = time.monotonic() + self.request_timeout if self.request_timeout is not None else None
        callback_error: Exception | None = None

        def cancel_after_callback_failure(error: Exception) -> None:
            nonlocal callback_error
            if callback_error is not None:
                return
            callback_error = error
            # Keep consuming the original prompt request until the server has
            # completed its cooperative cleanup. Returning from this method
            # while ask_user/approval is still waiting would strand the run.
            self._request("session/cancel", {"session_id": session_id})

        try:
            request_id, pending = self._begin_request(
                "session/prompt", {"session_id": session_id, "prompt": prompt},
            )
            while True:
                try:
                    wait_for = 0.02
                    if deadline is not None:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0 and not pending["event"].is_set():
                            raise TimeoutError("Atlas app-server session/prompt request timed out")
                        wait_for = min(wait_for, max(remaining, 0.001))
                    message = notifications.get(timeout=wait_for)
                except queue.Empty:
                    message = None
                if message is not None:
                    method = message.get("method")
                    params = message.get("params") if isinstance(message.get("params"), dict) else {}
                    if method == "approval/request":
                        try:
                            allowed = bool(approve and approve(params)) if callback_error is None else False
                        except Exception as exc:
                            cancel_after_callback_failure(exc)
                            allowed = False
                        if callback_error is None:
                            self._send_request("approval/response", {
                                "request_id": params.get("request_id"),
                                "event_id": params.get("event_id"),
                                "choice": "allow" if allowed else "deny",
                            })
                    elif method == "input/request":
                        try:
                            value = answer(params) if answer and callback_error is None else ""
                        except Exception as exc:
                            cancel_after_callback_failure(exc)
                            value = ""
                        if callback_error is None:
                            self._send_request("input/response", {
                                "request_id": params.get("request_id"),
                                "call_id": params.get("call_id"),
                                "value": value,
                            })
                    elif method == "session/event":
                        item = params.get("event")
                        if isinstance(item, dict) and on_event:
                            try:
                                on_event(item)
                            except Exception as exc:
                                cancel_after_callback_failure(exc)
                if pending["event"].is_set() and notifications.empty():
                    break
            if pending.get("error") is not None:
                raise RuntimeError(f"Atlas app-server reader failed: {pending['error']}")
            message = pending.get("message") or {}
            result = message.get("result") if isinstance(message, dict) else None
            if isinstance(result, dict) and result.get("status") in {
                "completed", "failed", "cancelled",
            }:
                # session/prompt responds just before run_prompt's finally
                # clears its active-session entry. Use the server's settle
                # barrier before exposing a reusable session to the caller.
                self._request("session/wait", {"session_id": session_id})
            if callback_error is not None:
                raise callback_error
            if isinstance(message.get("error"), dict):
                error = message["error"]
                raise AppServerError(int(error.get("code", -32603)), str(error.get("message", "JSON-RPC error")))
            result = message.get("result") if isinstance(message.get("result"), dict) else {}
            status = str(result.get("status", "completed"))
            if status not in {"completed", "failed", "cancelled"}:
                raise RuntimeError(f"Atlas app-server returned an unknown prompt status: {status}")
            return AppServerResult(session_id, str(result.get("text", "")), status)  # type: ignore[arg-type]
        finally:
            with self._state_lock:
                self._session_notifications.pop(session_id, None)
                if request_id is not None:
                    self._pending.pop(request_id, None)

    def close_session(self, session_id: str) -> None:
        self._request("session/close", {"session_id": session_id})
        self._session_ids.discard(session_id)

    def close(self) -> None:
        process = self._process
        if process is None:
            return
        if process.poll() is None:
            try:
                for session_id in tuple(self._session_ids):
                    self._request("session/close", {"session_id": session_id})
                self._session_ids.clear()
                if process.stdin:
                    process.stdin.close()
                process.wait(timeout=5)
                reader = self._reader_thread
                if reader is not None:
                    reader.join(timeout=5)
                stderr_reader = self._stderr_thread
                if stderr_reader is not None:
                    stderr_reader.join(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            except (OSError, RuntimeError, AppServerError):
                process.terminate()
                process.wait(timeout=5)
            finally:
                reader = self._reader_thread
                if reader is not None and reader.is_alive():
                    reader.join(timeout=1)
                stderr_reader = self._stderr_thread
                if stderr_reader is not None and stderr_reader.is_alive():
                    stderr_reader.join(timeout=1)
                self._process = None
                self._session_ids.clear()
                self._reader_thread = None
                self._stderr_thread = None
                with self._state_lock:
                    self._session_notifications.clear()
                    self._pending.clear()
        else:
            reader = self._reader_thread
            if reader is not None:
                reader.join(timeout=5)
            stderr_reader = self._stderr_thread
            if stderr_reader is not None:
                stderr_reader.join(timeout=5)
            self._process = None
            self._session_ids.clear()
            self._reader_thread = None
            self._stderr_thread = None
            with self._state_lock:
                self._session_notifications.clear()
                self._pending.clear()

    def __enter__(self) -> "AppServer":
        return self.start()

    def __exit__(self, *_: object) -> None:
        self.close()
