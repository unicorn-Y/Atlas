"""W4-Z5 ACP evidence driver: drive Atlas's ACP v1 stdio adapter end to end.

Spawns ``python -m atlas.cli acp --workspace <dir>`` and walks the real ACP
wire: initialize, session/new (with agent+permission presets), session/prompt
(real model), session/list, session/set_config_option, session/resume,
session/cancel, session/close. Also probes the negative contracts (unknown
presets, per-session MCP injection) that external-entry validation must
enforce. Every response is printed verbatim; that output is the evidence.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import queue
import uuid
from pathlib import Path


def _reader(pipe, lines: queue.Queue) -> None:
    for raw in iter(pipe.readline, ""):
        try:
            lines.put(json.loads(raw))
        except ValueError:
            lines.put({"_raw": raw})
    lines.put(None)


class AcpSession:
    def __init__(self, workspace: Path, python: str, env_home: str | None) -> None:
        self.proc = subprocess.Popen(
            [python, "-m", "atlas.cli", "acp", "--workspace", str(workspace)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            env={**__import__("os").environ, **({"USERPROFILE": env_home, "HOME": env_home} if env_home else {})},
            text=True, encoding="utf-8", bufsize=1,
        )
        self.lines: queue.Queue = queue.Queue()
        self.next_id = 0
        self.thread = threading.Thread(target=_reader, args=(self.proc.stdout, self.lines), daemon=True)
        self.thread.start()

    def request(self, method: str, params: dict, timeout: float = 30) -> dict:
        self.next_id += 1
        req_id = f"w4z5-{self.next_id}"
        payload = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        print(f"--> {method} id={req_id} params={json.dumps(params, ensure_ascii=False)[:220]}")
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()
        return self.wait_response(req_id, timeout)

    def wait_response(self, req_id: str, timeout: float) -> dict:
        got: dict = {}
        import time
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                message = self.lines.get(timeout=min(2, max(0.1, deadline - time.time())))
            except queue.Empty:
                continue
            if message is None:
                raise RuntimeError("ACP adapter stdout closed")
            if message.get("_raw"):
                print(f"<-- raw {message['_raw'][:200]}")
                continue
            if str(message.get("id")) == str(req_id) and ("result" in message or "error" in message):
                got = message
                print(f"<-- id={req_id} {json.dumps(message.get('result', message.get('error')), ensure_ascii=False)[:400]}")
                return got
            if message.get("id") is not None and "method" in message:
                # a request from the agent side (permission/fs) — deny politely
                print(f"<-- agent-request {message.get('method')} (auto-deny)")
                self.proc.stdin.write(json.dumps({
                    "jsonrpc": "2.0", "id": message.get("id"),
                    "result": {"outcome": {"outcome": "selected", "optionId": "reject_once"}},
                }) + "\n")
                self.proc.stdin.flush()
                continue
            if message.get("method"):
                print(f"<-- notify {message.get('method')} {json.dumps(message.get('params') or {}, ensure_ascii=False)[:220]}")
        raise TimeoutError(f"no response for id={req_id} within {timeout}s")

    def close(self) -> None:
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()


def expect_error(resp: dict, label: str) -> None:
    err = resp.get("error")
    assert err, f"{label}: expected JSON-RPC error, got {json.dumps(resp)[:200]}"
    print(f"    [{label}] error.code={err.get('code')} message={err.get('message')}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--home", default=None, help="isolated USERPROFILE for the adapter process")
    parser.add_argument("--first-prompt", default="Reply with exactly the word: OK")
    parser.add_argument("--second-prompt", default="Reply with exactly the word: RESUMED")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    assert workspace.is_dir(), f"workspace missing: {workspace}"
    acp = AcpSession(workspace, args.python, args.home)
    failures: list[str] = []
    session_id = ""
    try:
        init = acp.request("initialize", {"protocolVersion": 1}, timeout=120)
        if init.get("error"):
            failures.append(f"initialize failed: {init['error']}")
        print("== negative: unknown agent preset ==")
        resp = acp.request("session/new", {
            "cwd": str(workspace), "agentPresetId": "does-not-exist-w4z5",
            "permissionPreset": "ask",
        })
        try:
            expect_error(resp, "unknown-agent-preset")
        except AssertionError as exc:
            failures.append(str(exc))
        print("== negative: unknown permission preset ==")
        resp = acp.request("session/new", {
            "cwd": str(workspace), "agentPresetId": "default",
            "permissionPreset": "not-a-preset",
        })
        try:
            expect_error(resp, "unknown-permission-preset")
        except AssertionError as exc:
            failures.append(str(exc))
        print("== negative: per-session MCP injection is rejected ==")
        resp = acp.request("session/new", {
            "cwd": str(workspace), "agentPresetId": "default", "permissionPreset": "ask",
            "mcpServers": [{"name": "x", "command": "noop"}],
        })
        try:
            expect_error(resp, "mcp-injection-rejected")
        except AssertionError as exc:
            failures.append(str(exc))
        print("== session/new with valid presets ==")
        resp = acp.request("session/new", {
            "cwd": str(workspace), "agentPresetId": "w4z5-restricted",
            "permissionPreset": "ask",
        })
        result = resp.get("result") or {}
        session_id = str(result.get("sessionId") or "")
        if not session_id:
            failures.append(f"session/new failed: {json.dumps(resp)[:300]}")
        print(f"    sessionId={session_id}")
        print("== session/prompt (real model) ==")
        resp = acp.request("session/prompt", {
            "sessionId": session_id,
            "prompt": [{"type": "text", "text": args.first_prompt}],
        }, timeout=300)
        stop = str((resp.get("result") or {}).get("stopReason"))
        print(f"    stopReason={stop}")
        if stop != "end_turn":
            failures.append(f"first prompt stopReason={stop}")
        print("== session/list ==")
        resp = acp.request("session/list", {})
        sessions = (resp.get("result") or {}).get("sessions") or []
        print(f"    listed={len(sessions)} first={json.dumps(sessions[:1], ensure_ascii=False)[:200]}")
        if not any(str(s.get("sessionId")) == session_id for s in sessions):
            failures.append("session/list did not include the new session")
        print("== session/set_config_option ==")
        resp = acp.request("session/set_config_option", {
            "sessionId": session_id, "configId": "permissionPreset",
            "type": "id", "value": "observe",
        })
        opts = ((resp.get("result") or {}).get("configOptions") or [{}])[0]
        print(f"    currentValue={opts.get('currentValue')}")
        if opts.get("currentValue") != "observe":
            failures.append(f"set_config_option currentValue={opts.get('currentValue')}")
        print("== session/resume ==")
        resp = acp.request("session/resume", {"sessionId": session_id, "cwd": str(workspace)})
        opts = ((resp.get("result") or {}).get("configOptions") or [{}])[0]
        print(f"    resumed configOptions.currentValue={opts.get('currentValue')}")
        if resp.get("error") or not opts:
            failures.append(f"session/resume failed: {json.dumps(resp)[:200]}")
        print("== session/prompt after resume (real model) ==")
        resp = acp.request("session/prompt", {
            "sessionId": session_id,
            "prompt": [{"type": "text", "text": args.second_prompt}],
        }, timeout=300)
        stop = str((resp.get("result") or {}).get("stopReason"))
        print(f"    stopReason={stop}")
        if stop != "end_turn":
            failures.append(f"resumed prompt stopReason={stop}")
        print("== session/cancel (no active run) ==")
        resp = acp.request("session/cancel", {"sessionId": session_id})
        if resp.get("error") or not isinstance((resp.get("result") or {}).get("cancelled"), bool):
            failures.append(f"session/cancel failed: {json.dumps(resp)[:200]}")
        print("== session/close ==")
        resp = acp.request("session/close", {"sessionId": session_id})
        if resp.get("error"):
            failures.append(f"session/close failed: {json.dumps(resp)[:200]}")
    finally:
        acp.close()
    print(f"[result] failures={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
