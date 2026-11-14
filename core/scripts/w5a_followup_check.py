"""WAVE5-A E36 live proof: a background process completion reaches a later model
request as a followup notification.

Turn 1: the model starts a DETACHED background process (short ping) and ends the
turn without waiting. The process finishes after the run closes and its
completion is published into the durable notification inbox
(``atlas.engine.notifications.publish_notification``).
Turn 2 (same conversation): ``run_turn`` consumes the inbox at start and rides
the notices into the system message ("Background process notifications ..."),
so the model can report the completion.

Usage: python scripts/w5a_followup_check.py <port>
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

URL = "ws://127.0.0.1:{port}/ws/chat"

TURN1 = (
    "Do exactly two tool calls, nothing else. "
    "First: the local_shell tool with command 'ping -n 3 127.0.0.1', background=true, "
    "notify=true, yield_time_ms=500, so it starts detached and returns at once. "
    "Note the returned execution id. "
    "Second: the local_process tool with action=wait, that execution_id, and timeout 20, "
    "so this run stays open until the process exits. Then reply with exactly: BG_STARTED"
)
TURN2 = (
    "Check your context for background process notifications. If a background process "
    "completion notification is present, reply with exactly BG_FOLLOWUP_SEEN and quote "
    "the process state text. Otherwise reply BG_FOLLOWUP_MISSING."
)


async def one_turn(port: int, conversation_id: str, content: str, timeout_s: float) -> tuple[str, str, str]:
    run_id = str(uuid.uuid4())
    text_parts: list[str] = []
    terminal = ""
    system_hints: list[str] = []
    async with websockets.connect(URL.format(port=port), max_size=8 * 1024 * 1024) as ws:
        await ws.send(json.dumps({
            "type": "run.start", "run_id": run_id, "conversation_id": conversation_id,
            "workspace": str(__import__("pathlib").Path.cwd()), "content": content,
        }))
        deadline = asyncio.get_running_loop().time() + timeout_s
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
            if event in {"approval.required", "input.required"}:
                await ws.send(json.dumps({
                    "type": "approval.response",
                    "event_id": data.get("approval_id") or data.get("event_id"),
                    "choice": "allow_once",
                }))
            elif event in {"run.completed", "run.failed", "run.cancelled"}:
                terminal = event
                break
            elif event == "message.delta":
                text_parts.append(str(data.get("content") or ""))
    reply = "".join(text_parts).strip()
    return terminal, reply, run_id


async def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8890
    conversation_id = f"w5a-bg-{uuid.uuid4().hex[:8]}"

    terminal1, reply1, run1 = await one_turn(port, conversation_id, TURN1, 150)
    print(f"[turn1] terminal={terminal1} run={run1} reply={reply1[:200]!r}")
    if terminal1 != "run.completed" or "BG_STARTED" not in reply1:
        print("[result] turn1 did not start a background job cleanly")
        return 1

    # Give the detached process time to finish and its notification to persist.
    await asyncio.sleep(10)

    terminal2, reply2, run2 = await one_turn(port, conversation_id, TURN2, 150)
    print(f"[turn2] terminal={terminal2} run={run2} reply={reply2[:400]!r}")
    seen = "BG_FOLLOWUP_SEEN" in reply2
    print(f"[result] followup_seen={seen}")
    return 0 if seen else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
