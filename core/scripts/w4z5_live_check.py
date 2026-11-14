"""W4-Z5 evidence driver: one real model turn over the Atlas WebSocket.

Extended from ``dsh_live_ws_check.py`` with ``--workspace`` so live turns run
against a scratch directory instead of the repo. Prints every event it
receives; the output is the evidence of the live path. Write actions reach the
model only after an ``approval.required`` event, which this driver answers
with ``allow_once`` — so per-call approval gating stays on the wire and in the
event log.
"""
from __future__ import annotations

import asyncio
import argparse
import json
import sys
import uuid

try:
    import websockets
except ImportError:  # pragma: no cover
    print("websockets is not installed; install it to run this check", file=sys.stderr)
    raise SystemExit(2)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", nargs="?", type=int, default=8885)
    parser.add_argument("prompt", nargs="?", default="Reply with exactly the word: OK")
    parser.add_argument("--workspace", default=None)
    parser.add_argument("--permission-preset", default=None)
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()
    port = args.port
    prompt = args.prompt
    url = f"ws://127.0.0.1:{port}/ws/chat"
    run_id = str(uuid.uuid4())
    text_parts: list[str] = []
    terminal: str | None = None

    async with websockets.connect(url, max_size=8 * 1024 * 1024) as ws:
        start_payload = {
            "type": "run.start",
            "run_id": run_id,
            "conversation_id": f"dsh-z5-{run_id[:8]}",
            "workspace": args.workspace or str(__import__("pathlib").Path.cwd()),
            "content": prompt,
        }
        if args.permission_preset:
            start_payload["permission_preset"] = args.permission_preset
        await ws.send(json.dumps(start_payload))
        deadline = asyncio.get_running_loop().time() + args.timeout
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
                print(f"[event] {event} name={data.get('name')}")
            elif event == "tool.completed":
                print(f"[event] tool.completed name={data.get('name')} "
                      f"output={json.dumps(data.get('output') or data.get('content') or '', ensure_ascii=False)[:600]}")
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
                print(f"[event] {event}")

    reply = "".join(text_parts).strip()
    print(f"[reply] {reply[:1200]!r}")
    print(f"[result] terminal={terminal} chars={len(reply)}")
    return 0 if terminal == "run.completed" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
