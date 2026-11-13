import pytest

from atlas.agent import AgentOrchestrator
from atlas.engine.kernel.inbox import DurableInbox


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_forwards_shared_inbox_to_run_request(tmp_path):
    agent = object.__new__(AgentOrchestrator)
    inbox = DurableInbox(tmp_path / "engine", "inbox-wiring")
    captured = []

    async def execute(request, _callbacks):
        captured.append(request.inbox)
        if False:
            yield {}

    agent.execute = execute
    async for _event in agent.run("hello", conversation_id="inbox-wiring", inbox=inbox):
        pass

    assert captured == [inbox]
