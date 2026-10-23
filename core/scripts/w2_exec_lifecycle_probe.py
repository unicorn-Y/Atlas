"""Probe long process progress, auto background, and cleanup semantics."""
import asyncio
import tempfile
import time

from atlas.kernel.exec import ExecManager


async def main() -> None:
    started = time.monotonic()
    events: asyncio.Queue = asyncio.Queue()

    async def dispatch(name, args):
        action = args.get("action")
        if action == "start":
            return {"data": {"execution_id": "fixture"}}
        if action == "status":
            return {"data": {"state": "running" if time.monotonic() - started < 2 else "completed",
                              "exit_code": 0 if time.monotonic() - started >= 2 else None}}
        if action == "read":
            return {"data": {"text": "done", "next_offset": 4}}
        if action == "cancel":
            return {"data": {"state": "cancelled", "exit_code": -1}}
        return {"data": {}}

    with tempfile.TemporaryDirectory() as directory:
        manager = ExecManager(dispatch, output_dir=directory, event_queue=events)
        manager.PROGRESS_AFTER_SECONDS = 0.01
        manager.AUTO_BACKGROUND_AFTER_SECONDS = 0.03
        result = await manager.execute("terminal", {"command": "slow fixture"})
        assert result["data"]["backgrounded"] and result["data"]["state"] == "running"
        assert { (await events.get())["type"], (await events.get())["type"] } == {
            "process.progress", "process.backgrounded",
        }
        await manager.shutdown()
    print("W2-5 progress, auto-background, and session cleanup: PASS")


if __name__ == "__main__":
    asyncio.run(main())
