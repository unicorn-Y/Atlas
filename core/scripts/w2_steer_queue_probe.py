"""Exercise the safe-point sequence used for in-flight tool steering."""
import asyncio

from atlas.kernel.tools import ToolScheduler


async def main() -> None:
    queue: asyncio.Queue[dict] = asyncio.Queue()
    visible: list[str] = []
    started = asyncio.Event()
    release = asyncio.Event()

    async def dispatch(call_id, name, args):
        started.set()
        await release.wait()
        return {"data": "tool done"}

    scheduler = ToolScheduler(dispatch)
    task = asyncio.create_task(scheduler.run([{
        "id": "slow", "function": {"name": "local_process", "arguments": "{}"},
    }]))
    await started.wait()
    await queue.put({"content": "please adjust the result", "event_id": "steer-1"})
    assert not queue.empty() and not visible
    release.set()
    results = await task
    assert results[0].receipt.state == "completed"
    # Kernel loop's safe point drains the steer queue only after result receipt.
    visible.append((await queue.get())['content'])
    assert visible == ["please adjust the result"]
    print("W2-4 queued steering is injected after the active tool result: PASS")


if __name__ == "__main__":
    asyncio.run(main())
