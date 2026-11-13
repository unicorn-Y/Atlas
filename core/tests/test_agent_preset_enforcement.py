from types import SimpleNamespace

import pytest

from atlas.agent.run_phases import RunRequest, _apply_agent_preset_capabilities
from atlas.engine.kernel.loop import _mcp_tool_allowed, _plan_mode_denies


def _capabilities(**overrides):
    value = {
        "tools": {"allow": ["read_file"], "allow_all": False, "deny": ["local_shell"]},
        "skills": [], "mcp_servers": ["docs"], "model": "preset-model", "mode": "plan",
    }
    value.update(overrides)
    return value


@pytest.mark.unit
@pytest.mark.asyncio
async def test_preset_intersects_tool_scope_and_applies_non_explicit_model_and_mode():
    request = RunRequest(
        message="x", conversation_id="c", tool_allow=["read_file", "local_shell"],
        tool_deny=["write_file"], agent_preset_id="research",
        agent_preset_capabilities=_capabilities(),
    )
    runtime = SimpleNamespace(mode=request.mode, model=None, mcp_server_allow=None)

    error = await _apply_agent_preset_capabilities(SimpleNamespace(_skills=None), request, runtime)

    assert error is None
    assert request.tool_allow == ["read_file"]
    assert request.tool_deny == ["local_shell", "write_file"]
    assert request.mode == runtime.mode == "plan"
    assert request.model == "preset-model"
    assert runtime.mcp_server_allow == ["docs"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_explicit_user_model_and_mode_override_preset():
    request = RunRequest(
        message="x", conversation_id="c", model="user-model", mode="act", mode_explicit=True,
        agent_preset_id="research", agent_preset_capabilities=_capabilities(),
    )
    runtime = SimpleNamespace(mode="act", model=None, mcp_server_allow=None)

    error = await _apply_agent_preset_capabilities(SimpleNamespace(_skills=None), request, runtime)

    assert error is None
    assert request.model == "user-model"
    assert request.mode == runtime.mode == "act"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_preset_skills_are_activated_and_missing_skills_fail_closed():
    class Skills:
        async def activate_for_model(self, name):
            return "instructions" if name == "allowed" else None

    request = RunRequest(
        message="x", conversation_id="c", agent_preset_id="research",
        agent_preset_capabilities=_capabilities(skills=["allowed"]),
    )
    runtime = SimpleNamespace(mode="act", model=None, mcp_server_allow=None)
    agent = SimpleNamespace(_skills=Skills())

    error = await _apply_agent_preset_capabilities(agent, request, runtime)
    assert error is None
    assert request.active_skill_instructions == [{"name": "allowed", "content": "instructions"}]

    request.agent_preset_capabilities = _capabilities(skills=["missing"])
    error = await _apply_agent_preset_capabilities(agent, request, runtime)
    assert error and "missing" in error


@pytest.mark.unit
@pytest.mark.asyncio
async def test_non_default_preset_without_capabilities_fails_closed():
    request = RunRequest(message="x", conversation_id="c", agent_preset_id="research")
    runtime = SimpleNamespace(mode="act", model=None, mcp_server_allow=None)

    error = await _apply_agent_preset_capabilities(SimpleNamespace(_skills=None), request, runtime)

    assert error and "capabilities" in error


@pytest.mark.unit
def test_preset_scope_blocks_unlisted_mcp_servers_and_plan_mode_writes():
    runtime = SimpleNamespace(mcp_server_allow=["docs"], mode="plan", dynamic_plan_mode=False)

    assert _mcp_tool_allowed(runtime, "docs__search")
    assert not _mcp_tool_allowed(runtime, "calendar__create_event")
    assert _plan_mode_denies(runtime, "docs__search")
    assert not _plan_mode_denies(runtime, "read_file")
    assert _plan_mode_denies(runtime, "local_shell")
