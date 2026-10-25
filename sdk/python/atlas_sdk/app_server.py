"""Typed client for Atlas' versioned JSON-RPC app-server stdio protocol."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
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


class AppServerError(RuntimeError):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


class AppServer:
    """Launch and drive `atlas app-server` using newline-delimited JSON-RPC 2.0."""

    protocol_version = 1

    def __init__(self, executable: str | Sequence[str] = "atlas", *, workspace: str | os.PathLike[str] | None = None,
                 env: dict[str, str] | None = None):
        self.command = [executable] if isinstance(executable, str) else list(executable)
        if not self.command:
            raise ValueError("executable command must not be empty")
        self.workspace = str(Path(workspace).resolve()) if workspace is not None else str(Path.cwd())
        self.env = {**os.environ, **(env or {})}
        self._process: subprocess.Popen[str] | None = None
        self._next_id = 0
        self._session_ids: set[str] = set()

    def start(self) -> "AppServer":
        if self._process is not None and self._process.poll() is None:
            return self
        self._process = subprocess.Popen(
            [*self.command, "app-server", "--workspace", self.workspace],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", env=self.env, bufsize=1,
        )
        result = self._request("initialize", {"protocolVersion": self.protocol_version})
        version = result.get("protocolVersion")
        if version != self.protocol_version:
            self.close()
            raise AppServerError(-32002, f"Atlas app-server protocol mismatch: expected {self.protocol_version}, got {version!r}")
        return self

    def _write(self, message: dict[str, Any]) -> None:
        if not self._process or not self._process.stdin:
            raise RuntimeError("AppServer.start() must be called first")
        self._process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        self._process.stdin.flush()

    def _read(self) -> dict[str, Any]:
        if not self._process or not self._process.stdout:
            raise RuntimeError("AppServer.start() must be called first")
        line = self._process.stdout.readline()
        if not line:
            error = self._process.stderr.read() if self._process.stderr else ""
            raise RuntimeError(f"Atlas app-server exited: {error.strip() or self._process.poll()}")
        value = json.loads(line)
        if not isinstance(value, dict) or value.get("jsonrpc") != "2.0":
            raise RuntimeError("Atlas app-server returned an invalid JSON-RPC message")
        return value

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._next_id += 1
        request_id = self._next_id
        self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        while True:
            message = self._read()
            if message.get("id") != request_id:
                continue
            if isinstance(message.get("error"), dict):
                error = message["error"]
                raise AppServerError(int(error.get("code", -32603)), str(error.get("message", "JSON-RPC error")))
            result = message.get("result")
            return result if isinstance(result, dict) else {}

    def _send_request(self, method: str, params: dict[str, Any]) -> int:
        self._next_id += 1
        request_id = self._next_id
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

    def prompt(self, session_id: str, prompt: str, *,
               on_event: Callable[[dict[str, Any]], None] | None = None,
               approve: Callable[[dict[str, Any]], bool] | None = None,
               answer: Callable[[dict[str, Any]], str] | None = None) -> AppServerResult:
        if not prompt.strip():
            raise ValueError("prompt must not be empty")
        self._next_id += 1
        request_id = self._next_id
        self._write({"jsonrpc": "2.0", "id": request_id, "method": "session/prompt",
                     "params": {"session_id": session_id, "prompt": prompt}})
        events: list[dict[str, Any]] = []
        while True:
            message = self._read()
            method = message.get("method")
            if isinstance(method, str):
                params = message.get("params") if isinstance(message.get("params"), dict) else {}
                if method == "approval/request":
                    self._send_request("approval/response", {"event_id": params.get("event_id"),
                                                               "choice": "allow" if approve and approve(params) else "deny"})
                elif method == "input/request":
                    self._send_request("input/response", {"call_id": params.get("call_id"),
                                                            "value": answer(params) if answer else ""})
                elif method == "session/event":
                    item = params.get("event")
                    if isinstance(item, dict):
                        events.append(item)
                        if on_event:
                            on_event(item)
                continue
            if message.get("id") != request_id:
                continue
            if isinstance(message.get("error"), dict):
                error = message["error"]
                raise AppServerError(int(error.get("code", -32603)), str(error.get("message", "JSON-RPC error")))
            result = message.get("result") if isinstance(message.get("result"), dict) else {}
            status = str(result.get("status", "completed"))
            if status not in {"completed", "failed", "cancelled"}:
                raise RuntimeError(f"Atlas app-server returned an unknown prompt status: {status}")
            return AppServerResult(session_id, str(result.get("text", "")), status)  # type: ignore[arg-type]

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
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            except (OSError, RuntimeError, AppServerError):
                process.terminate()
                process.wait(timeout=5)
            finally:
                self._process = None
                self._session_ids.clear()
        else:
            self._process = None
            self._session_ids.clear()

    def __enter__(self) -> "AppServer":
        return self.start()

    def __exit__(self, *_: object) -> None:
        self.close()
