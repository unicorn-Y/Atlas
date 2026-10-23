"""Small executable proof of addressed mailbox ordering, wakeup, and reply flow."""

from __future__ import annotations

import asyncio

from atlas.agent.mailbox import AgentMailbox


async def main() -> None:
    mailbox = AgentMailbox()
    parent, child = "parent@atlas", "child-1@atlas"
    waiter = asyncio.create_task(mailbox.receive(child, wait=True))
    for _ in range(100):
        if mailbox.waiting_receivers(child):
            break
        await asyncio.sleep(0)
    assert mailbox.waiting_receivers(child) == 1
    await mailbox.send(parent, child, "please report the result")
    first = await asyncio.wait_for(waiter, timeout=1)
    assert first[0].content == "please report the result"

    sends = [mailbox.send(parent, child, f"message-{index}") for index in range(6)]
    await asyncio.gather(*sends)
    queued = await mailbox.receive(child, limit=10)
    assert [message.revision for message in queued] == list(range(2, 8))
    assert [message.content for message in queued] == [f"message-{i}" for i in range(6)]

    await mailbox.send(child, parent, "done: result received and task completed")
    reply = await mailbox.receive(parent)
    assert reply[0].sender == child and "task completed" in reply[0].content
    print("W3-8 MAILBOX PROBE PASS: addressed FIFO delivery, waiter wakeup, and parent-child reply")


if __name__ == "__main__":
    asyncio.run(main())
