import pytest

from atlas.agent import AgentOrchestrator


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_forwards_agent_and_permission_preset_to_request():
    agent = object.__new__(AgentOrchestrator)
    captured = []
    capabilities = {
        "tools": {"allow": ["read_file"], "allow_all": False, "deny": []},
        "skills": [], "mcp_servers": [], "model": "inherit", "mode": "act",
    }

    async def execute(request, _callbacks):
        captured.append((request.agent_preset_id, request.permission_preset,
                         request.agent_preset_capabilities))
        if False:
            yield {}

    agent.execute = execute
    async for _event in agent.run(
        "hello", conversation_id="policy-context",
        agent_preset_id="researcher", permission_preset="workspace-write",
        agent_preset_capabilities=capabilities,
    ):
        pass

    assert captured == [("researcher", "workspace-write", capabilities)]
