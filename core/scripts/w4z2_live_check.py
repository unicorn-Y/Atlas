"""WAVE4 Z2 live-evidence driver: one real model turn over the Atlas WebSocket.

Extends ``dsh_live_ws_check.py`` with the knobs this batch's rows need:

* ``--workspace`` / ``--conversation-id`` — pin the run's workspace and session,
  so session-query tools (E31) gate on the right cwd and worktree evidence (E32)
  lands in a scratch repo instead of the Atlas checkout.
* ``--cancel-on-tool SUBSTR`` — send ``run.cancel`` as soon as a tool whose name
  contains SUBSTR starts (E34 synthetic-cancelled receipts).
* ``--print-args`` — include tool arguments in tool events.

The script prints every event it receives plus the terminal state and reply;
that output is the evidence. It reads no credentials; the backend owns them.
"""
from __future__ import annotations

import asyncio
import argparse
import json
import sys
import uuid
from pathlib import Path

try:
    import websockets
except ImportError:  # pragma: no cover - dependency ships with the desktop extras
    print("websockets is not installed; install it to run this check", file=sys.stderr)
    raise SystemExit(2)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", nargs="?", type=int, default=8882)
    parser.add_argument("prompt", nargs="?", default="Reply with exactly the word: OK")
    parser.add_argument("--workspace", default="")
    parser.add_argument("--conversation-id", default="")
    parser.add_argument("--cancel-on-tool", default="",
                        help="send run.cancel when a started tool name contains this substring")
    parser.add_argument("--cancel-delay", type=float, default=1.5,
                        help="seconds to wait after the matching tool starts, before cancel")
    parser.add_argument("--timeout", type=float, default=240,
                        help="overall deadline in seconds")
    parser.add_argument("--tool-mode", choices=("native", "ptc"))
    parser.add_argument("--print-args", action="store_true")
    args = parser.parse_args()

    run_id = str(uuid.uuid4())
    conversation_id = args.conversation_id or f"dsh-z2-{run_id[:8]}"
    workspace = args.workspace or str(Path.cwd())
    text_parts: list[str] = []
    terminal: str | None = None
    cancel_sent = False
    cancelled_tool = ""
    seen_tools: list[str] = []

    async with websockets.connect(f"ws://127.0.0.1:{args.port}/ws/chat",
                                  max_size=8 * 1024 * 1024) as ws:
        start_payload = {
            "type": "run.start",
            "run_id": run_id,
            "conversation_id": conversation_id,
            "workspace": workspace,
            "content": args.prompt,
        }
        if args.tool_mode:
            start_payload["tool_mode"] = args.tool_mode
        await ws.send(json.dumps(start_payload))
        print(f"[start] run_id={run_id} conversation_id={conversation_id} workspace={workspace}")
        deadline = asyncio.get_running_loop().time() + args.timeout

        async def maybe_cancel(name: str) -> None:
            nonlocal cancel_sent
            if cancel_sent or not args.cancel_on_tool:
                return
            if args.cancel_on_tool.lower() in name.lower():
                cancel_sent = True
                await asyncio.sleep(args.cancel_delay)
                await ws.send(json.dumps({"type": "run.cancel", "run_id": run_id}))
                print(f"[action] run.cancel sent after tool {name!r} (+{args.cancel_delay}s)")

        while asyncio.get_running_loop().time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
            except asyncio.TimeoutError:
                continue
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", "replace")
            try:
                frame = json.loads(raw)
            except ValueError:
                continue
            event = frame.get("event") or frame.get("type")
            data = frame.get("data") or {}
            if event == "message.delta":
                text_parts.append(str(data.get("content") or ""))
            elif event in {"tool.started", "tool.preparing"}:
                name = str(data.get("name") or "")
                seen_tools.append(name)
                suffix = f" args={json.dumps(data.get('arguments') or {}, ensure_ascii=False)[:200]}" if args.print_args else ""
                print(f"[event] {event} name={name}{suffix}")
                if event == "tool.started":
                    await maybe_cancel(name)
            elif event == "tool.completed":
                contract = data.get("output_contract")
                contract_note = ""
                if isinstance(contract, dict):
                    schema = contract.get("schema")
                    title = schema.get("title") if isinstance(schema, dict) else "registered"
                    contract_note = f" output_contract={contract.get('render', 'text')}/{title}"
                outcome = ""
                if isinstance(data.get("output"), dict):
                    outcome = f" outcome={data['output'].get('outcome')}"
                elif isinstance(data.get("result"), dict):
                    outcome = f" outcome={data['result'].get('outcome')}"
                print(f"[event] tool.completed name={data.get('name')}{contract_note}{outcome}")
            elif event in {"approval.required", "input.required", "run.plan.proposed"}:
                print(f"[event] {event} tool={data.get('tool')} waiting")
                await ws.send(json.dumps({
                    "type": "approval.response",
                    "event_id": data.get("approval_id") or data.get("event_id"),
                    "choice": "allow_once",
                }))
            elif event in {"run.completed", "run.failed", "run.cancelled"}:
                terminal = event
                print(f"[terminal] {event} data={json.dumps(data, ensure_ascii=False)[:300]}")
                break
            elif event:
                note = ""
                if event in {"run_steered", "run.steered", "message.steered"}:
                    note = f" content={str(data.get('content') or '')[:160]!r}"
                print(f"[event] {event}{note}")

    reply = "".join(text_parts).strip()
    print(f"[reply] {reply[:400]!r}")
    print(f"[tools] {seen_tools}")
    print(f"[result] terminal={terminal} chars={len(reply)}")
    if args.cancel_on_tool:
        return 0 if terminal in {"run.cancelled", "run.completed"} else 1
    return 0 if terminal == "run.completed" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
