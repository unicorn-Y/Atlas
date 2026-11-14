"""Drive one real turn through a running Atlas backend over its WebSocket.

Prints every event it receives, so the output is evidence of the live path:
the client sends ``run.start``, the backend runs the real model and tools, and
the script reports the terminal event plus the reply text. No credentials are
read here; the backend owns them.
"""
from __future__ import annotations

import asyncio
import argparse
import json
import sys
import uuid

try:
    import websockets
except ImportError:  # pragma: no cover - dependency is part of the desktop extras
    print("websockets is not installed; install it to run this check", file=sys.stderr)
    raise SystemExit(2)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", nargs="?", type=int, default=8799)
    parser.add_argument("prompt", nargs="?", default="Reply with exactly the word: OK")
    parser.add_argument("--tool-mode", choices=("native", "ptc"))
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
            "conversation_id": f"dsh-live-{run_id[:8]}",
            "workspace": str(__import__("pathlib").Path.cwd()),
            "content": prompt,
        }
        if args.tool_mode:
            start_payload["tool_mode"] = args.tool_mode
        await ws.send(json.dumps(start_payload))
        deadline = asyncio.get_running_loop().time() + 150
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
                contract = data.get("output_contract")
                if isinstance(contract, dict):
                    schema = contract.get("schema")
                    schema_title = schema.get("title") if isinstance(schema, dict) else "registered"
                    print(
                        f"[event] tool.completed name={data.get('name')} "
                        f"output_contract={contract.get('render', 'text')}/{schema_title}"
                    )
                else:
                    print(f"[event] tool.completed name={data.get('name')} output_contract=missing")
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
    print(f"[reply] {reply[:400]!r}")
    print(f"[result] terminal={terminal} chars={len(reply)}")
    return 0 if terminal == "run.completed" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
