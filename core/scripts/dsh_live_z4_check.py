"""Drive one real turn through a running Atlas backend over its WebSocket (Z4 evidence).

Extends dsh_live_ws_check.py with the Z4 batch needs:

* ``--context-conversations`` — host-admitted referenced-conversation snapshots (S29);
* ``--attach-image`` — inline PNG/JPEG data-URL attachment (S25 route-aware image pricing);
* ``--model`` / ``--workspace`` / ``--conversation-id`` selection for repeatable evidence.

Prints every event it receives; the output is the live evidence itself.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
import uuid
from pathlib import Path

try:
    import websockets
except ImportError:  # pragma: no cover - dependency is part of the desktop extras
    print("websockets is not installed; install it to run this check", file=sys.stderr)
    raise SystemExit(2)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", nargs="?", type=int, default=8765)
    parser.add_argument("prompt", nargs="?", default="Reply with exactly the word: OK")
    parser.add_argument("--tool-mode", choices=("native", "ptc"))
    parser.add_argument("--conversation-id")
    parser.add_argument("--workspace")
    parser.add_argument("--model")
    parser.add_argument("--context-conversations", default="")
    parser.add_argument("--context-files", default="")
    parser.add_argument("--attach-image")
    args = parser.parse_args()

    url = f"ws://127.0.0.1:{args.port}/ws/chat"
    run_id = str(uuid.uuid4())
    text_parts: list[str] = []
    terminal: str | None = None

    start_payload: dict = {
        "type": "run.start",
        "run_id": run_id,
        "conversation_id": args.conversation_id or f"dsh-live-{run_id[:8]}",
        "workspace": args.workspace or str(Path.cwd()),
        "content": args.prompt,
    }
    if args.model:
        start_payload["model"] = args.model
    if args.tool_mode:
        start_payload["tool_mode"] = args.tool_mode
    if args.context_conversations:
        start_payload["context_conversations"] = [
            item.strip() for item in args.context_conversations.split(",") if item.strip()
        ]
    if args.context_files:
        start_payload["context_files"] = [
            item.strip() for item in args.context_files.split(",") if item.strip()
        ]
    if args.attach_image:
        raw = Path(args.attach_image).read_bytes()
        suffix = Path(args.attach_image).suffix.lower().lstrip(".")
        mime = {"jpg": "jpeg"}.get(suffix, suffix or "png")
        start_payload["attachments"] = [
            f"data:image/{mime};base64," + base64.b64encode(raw).decode("ascii")
        ]

    print(f"=== run.start run_id={run_id} conversation={start_payload['conversation_id']}")
    async with websockets.connect(url, max_size=8 * 1024 * 1024) as ws:
        await ws.send(json.dumps(start_payload))
        deadline = asyncio.get_running_loop().time() + 240
        while asyncio.get_running_loop().time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
            except asyncio.TimeoutError:
                if terminal:
                    break
                continue
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", "replace")
            try:
                frame = json.loads(raw)
            except ValueError:
                continue
            event = frame.get("event") or frame.get("type")
            data = frame.get("data") or {}
            print(f"[{event}] {json.dumps(data, ensure_ascii=False)[:400]}")
            if event == "chunk":
                text_parts.append(str(data.get("content") or ""))
            if event in {"run.completed", "run.failed", "run.cancelled"}:
                terminal = event
                break
    print(f"=== terminal={terminal}")
    print("=== reply:", "".join(text_parts)[:2000])
    print(f"=== conversation_id={start_payload['conversation_id']}")
    return 0 if terminal == "run.completed" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
