"""WAVE5-A E34 live proof: cancel a real model run mid-tool-call and observe
the synthetic cancelled tool/result receipts.

Flow: start a run whose prompt makes the model call a long-running local_exec
command; once the tool has started, send ``run.cancel``; record every frame and
the terminal event. The run journal (ATLAS_DATA_DIR/data/logs/runs/<date>/<run_id>.jsonl)
is the replay evidence: the interrupted call must carry a ``cancelled`` receipt /
synthetic result instead of a dangling call.

Usage: python scripts/w5a_cancel_check.py <port> "<prompt>"
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid

try:
    import websockets
except ImportError:  # pragma: no cover
    print("websockets is not installed", file=sys.stderr)
    raise SystemExit(2)


async def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8890
    prompt = sys.argv[2] if len(sys.argv) > 2 else (
        "Use the local_exec tool to run exactly this command and wait for it to finish: "
        "ping -n 30 127.0.0.1 . Do not use any other tool. After it returns, say DONE."
    )
    url = f"ws://127.0.0.1:{port}/ws/chat"
    run_id = str(uuid.uuid4())
    cancelled_sent = False
    saw_tool_start = False
    terminal: str | None = None
    events: list[str] = []
    reply_parts: list[str] = []

    async with websockets.connect(url, max_size=8 * 1024 * 1024) as ws:
        await ws.send(json.dumps({
            "type": "run.start", "run_id": run_id,
            "conversation_id": f"w5a-cancel-{run_id[:8]}",
            "workspace": str(__import__("pathlib").Path.cwd()),
            "content": prompt,
        }))
        print(f"[run] {run_id}")
        deadline = asyncio.get_running_loop().time() + 90
        while asyncio.get_running_loop().time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
            except asyncio.TimeoutError:
                if saw_tool_start and not cancelled_sent:
                    await ws.send(json.dumps({"type": "run.cancel", "run_id": run_id}))
                    cancelled_sent = True
                    print("[cancel] run.cancel sent")
                continue
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", "replace")
            try:
                frame = json.loads(raw)
            except ValueError:
                continue
            event = frame.get("event") or frame.get("type")
            data = frame.get("data") or {}
            if event:
                events.append(event)
            if event in {"tool.started", "tool.preparing"}:
                saw_tool_start = True
                print(f"[event] {event} name={data.get('name')}")
            elif event == "tool.completed":
                print(f"[event] tool.completed name={data.get('name')} "
                      f"status={data.get('status') or data.get('outcome')}")
            elif event in {"approval.required", "input.required"}:
                print(f"[event] {event} tool={data.get('tool')} -> allow_once")
                await ws.send(json.dumps({
                    "type": "approval.response",
                    "event_id": data.get("approval_id") or data.get("event_id"),
                    "choice": "allow_once",
                }))
            elif event == "message.delta":
                reply_parts.append(str(data.get("content") or ""))
            elif event in {"run.completed", "run.failed", "run.cancelled"}:
                terminal = event
                print(f"[terminal] {event} data={json.dumps(data, ensure_ascii=False)[:300]}")
                break
        else:
            print("[terminal] timeout")
            return 1

    print(f"[events] {' '.join(events[:60])}")
    print(f"[reply] {''.join(reply_parts).strip()[:300]!r}")
    ok = terminal == "run.cancelled" and saw_tool_start and cancelled_sent
    print(f"[result] terminal={terminal} tool_started={saw_tool_start} cancel_sent={cancelled_sent}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
