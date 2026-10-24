"""U8 feature checks. Use --live for the provider-backed ACP, exec, SDK and plan checks."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from email.message import EmailMessage
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))


def check_pure() -> None:
    from atlas.background_tasks import EmailDeduplicator, email_summary, idle_ready, in_idle_window, match_email_rule
    from atlas.kanban import KanbanStore
    from atlas.notifications import busy
    from atlas.pr_automation import poll_once
    from atlas.sharing import export_html

    with tempfile.TemporaryDirectory(prefix="atlas-u8-") as directory:
        temp = Path(directory)
        assert in_idle_window(datetime(2026, 1, 1, 2, 0), "01:00", "07:00")
        assert not in_idle_window(datetime(2026, 1, 1, 8, 0), "01:00", "07:00")
        assert idle_ready(now=datetime(2026, 1, 1, 8, 0), start="01:00", end="07:00", idle_minutes=10, seconds_since_input=700)

        mail = EmailMessage()
        mail["From"] = "Atlas Tester <test@example.com>"; mail["Subject"] = "Build broke"; mail["Message-ID"] = "<u8-1@example.com>"
        mail.set_content("The build failed with a compiler error.")
        summary = email_summary(mail.as_bytes())
        assert match_email_rule(summary, {"sender": "test@example.com", "subject": "build", "keyword": "compiler"})
        dedupe = EmailDeduplicator(temp / "seen.db")
        assert dedupe.first_seen(summary["message_id"]) and not dedupe.first_seen(summary["message_id"])

        old_path = busy._path
        busy._path = lambda: temp / "busy.json"
        try:
            busy.set_busy(60)
            assert busy.defer("done", "message")
            assert "1 条更新" in busy.take_summary()
            busy.set_busy(None)
        finally:
            busy._path = old_path

        html_path = export_html(temp / "share.html", title="U8", model="test-model", messages=[
            {"role": "user", "content": "token=abcdef1234567890 C:\\Users\\tester\\repo"},
            {"role": "tool", "content": "tool details"},
            {"role": "assistant", "content": "![sample](data:image/png;base64,aGVsbG8=)"},
        ], include_tools=False)
        rendered = html_path.read_text(encoding="utf-8")
        assert "[REDACTED]" in rendered and "C:\\Users\\tester" not in rendered and "data:image/png;base64" in rendered
        assert "tool details" not in rendered

        board = KanbanStore(temp / "kanban.db")
        board.create_board("u8")
        first = board.create_task("u8", {"title": "first", "assignee": "architect"})
        second = board.create_task("u8", {"title": "second", "parent": first["id"], "dependencies": [first["id"]]})
        assert len(board.dispatch_ready("u8", concurrency=1)) == 1
        try:
            board.update_task("u8", second["id"], {"status": "running"})
        except ValueError:
            pass
        else:
            raise AssertionError("kanban dependencies did not gate dispatch")
        board.record_failure("u8", first["id"], "retry me")
        assert board.tasks("u8")[0]["status"] == "todo"
        assert board.run_history(first["id"])

        calls: list[tuple[str, str]] = []
        archive: list[str] = []
        link = {"conversation_id": "c1", "root": str(temp), "pr": "1", "auto_fix": True,
                "max_attempts": 1, "attempts": {}}
        import atlas.pr_automation as pr
        old_gh = pr._gh
        def fake_gh(root: str, *args: str, timeout: int = 60):
            from subprocess import CompletedProcess
            if args[:2] == ("pr", "view"):
                return CompletedProcess(args, 0, json.dumps({"number": 1, "state": "OPEN", "mergeable": "MERGEABLE"}), "")
            if args[:2] == ("pr", "checks"):
                return CompletedProcess(args, 0, json.dumps([{"name": "CI", "state": "FAILURE", "link": "run-1"}]), "")
            if args[:2] == ("run", "view"):
                return CompletedProcess(args, 0, "compiler error", "")
            return CompletedProcess(args, 0, "", "")
        pr._gh = fake_gh
        try:
            result = poll_once(link, run_fix=lambda cid, text: calls.append((cid, text)), archive=archive.append)
            assert result["failed"] and calls and "compiler error" in calls[0][1]
            poll_once(link, run_fix=lambda cid, text: calls.append((cid, text)), archive=archive.append)
            assert len(calls) == 1
        finally:
            pr._gh = old_gh

        asyncio.run(check_ide(temp))


async def check_ide(temp: Path) -> None:
    import websockets
    import atlas.tools.ide_bridge as ide

    lock = temp / "vscode.json"
    ide.lock_path = lambda: lock
    requests: list[str] = []
    async def handler(socket):
        async for raw in socket:
            value = json.loads(raw); requests.append(value["method"])
            result = {"file": "C:/repo/file.py", "selection": {"text": "x", "startLine": 4, "endLine": 4}} if value["method"] == "context" else (
                [{"severity": "error", "message": "bad"}] if value["method"] == "diagnostics" else {"opened": True})
            await socket.send(json.dumps({"id": value["id"], "result": result}))
    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        lock.write_text(json.dumps({"port": port, "token": "x" * 64}), encoding="utf-8")
        assert (await ide.request("context"))["selection"]["startLine"] == 4
        assert (await ide.request("diagnostics"))[0]["severity"] == "error"
        assert (await ide.request("open_diff", {"file": "file.py", "before": "a", "after": "b"}))["opened"]
    assert requests == ["context", "diagnostics", "open_diff"]


async def check_acp_live() -> None:
    workspace = ROOT
    process = await asyncio.create_subprocess_exec(sys.executable, "-m", "atlas.cli", "acp", "--workspace", str(workspace),
        cwd=ROOT, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    assert process.stdin and process.stdout
    def send(payload: dict[str, object]) -> None:
        process.stdin.write((json.dumps(payload) + "\n").encode());
    send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": 1}})
    send({"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": {"cwd": str(workspace)}})
    await process.stdin.drain()
    session_id = ""
    while not session_id:
        event = json.loads(await asyncio.wait_for(process.stdout.readline(), timeout=30))
        if event.get("id") == 2: session_id = str(event["result"]["sessionId"])
    send({"jsonrpc": "2.0", "id": 3, "method": "session/prompt", "params": {
        "sessionId": session_id,
        "prompt": "Use the available file reading tool to read README.md, then tell me its first heading.",
    }})
    await process.stdin.drain()
    got_text = False; got_tool = False; sent_cancel = False; got_response = False
    deadline = asyncio.get_running_loop().time() + 240
    while asyncio.get_running_loop().time() < deadline and not got_response:
        try: line = await asyncio.wait_for(process.stdout.readline(), timeout=30)
        except asyncio.TimeoutError: continue
        if not line: break
        event = json.loads(line)
        if event.get("id") == 3: got_response = True
        update = event.get("params", {}).get("update", {})
        got_text |= update.get("sessionUpdate") == "agent_message_chunk"
        got_tool |= update.get("sessionUpdate") in {"tool_call", "tool_call_update"}
        if got_tool and not sent_cancel:
            send({"jsonrpc": "2.0", "method": "session/cancel", "params": {"sessionId": session_id}})
            await process.stdin.drain(); sent_cancel = True
    process.stdin.close()
    try: await asyncio.wait_for(process.wait(), timeout=15)
    except asyncio.TimeoutError: process.kill(); await process.wait()
    assert got_text and got_tool and sent_cancel, "ACP live session missed text/tool/cancel updates"


def check_exec_and_sdk_live() -> None:
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}
    with tempfile.TemporaryDirectory(prefix="atlas-u8-live-") as directory:
        schema_path = Path(directory) / "schema.json"; schema_path.write_text(json.dumps(schema), encoding="utf-8")
        output_path = Path(directory) / "last.txt"
        import subprocess
        result = subprocess.run([sys.executable, "-m", "atlas.cli", "exec", "--json", "--cwd", str(ROOT),
            "--output-schema", str(schema_path), "--output-last-message", str(output_path),
            "Return exactly a JSON object with ok set to true."], cwd=ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=240)
        if result.returncode: raise RuntimeError("atlas exec live check failed")
        events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        assert any(item.get("type") == "start" for item in events) and any(item.get("type") == "end" for item in events)
        assert json.loads(output_path.read_text(encoding="utf-8"))["ok"] is True

        sys.path.insert(0, str(ROOT / "sdk" / "python"))
        from atlas_sdk import Atlas
        sdk = Atlas(executable=sys.executable)
        sdk.executable = sys.executable
        # Atlas SDK invokes `python exec`; use a tiny shim command to preserve the module entry point.
        from unittest.mock import patch
        real_popen = subprocess.Popen
        def module_popen(command, **kwargs):
            if command and command[0] == sys.executable:
                command = [sys.executable, "-m", "atlas.cli", *command[1:]]
            return real_popen(command, **kwargs)
        with patch("subprocess.Popen", side_effect=module_popen):
            sdk_result = sdk.run("Return JSON with ok true.", cwd=ROOT, output_schema=schema)
        assert sdk_result.structured == {"ok": True} and sdk_result.session_id

        plan = subprocess.run([sys.executable, "-m", "atlas.cli", "exec", "--cwd", str(ROOT),
            "Draft a detailed implementation plan for adding a greeting endpoint. Include goal, steps, files, verification and risks."],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=240)
        assert plan.returncode == 0 and all(word in plan.stdout.lower() for word in ("goal", "steps", "risk"))


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    check_pure()
    if args.live:
        asyncio.run(check_acp_live())
        check_exec_and_sdk_live()
    print("U8 CHECK PASS")


if __name__ == "__main__":
    main()
