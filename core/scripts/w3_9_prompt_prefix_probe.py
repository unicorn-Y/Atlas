"""Focused probe for child-run stable prompt-prefix reuse."""
import asyncio
from types import SimpleNamespace
from atlas.agent.prompt_cache_boundary import find_stable_prefix, register_stable_prefix
from atlas.agent.run_phases import RunCallbacks, RunRequest, _RunState, _build_messages

async def main():
    prefix = "Atlas stable parent prefix\nTask verification and tool guidance."
    register_stable_prefix(prefix)
    request = RunRequest(message="child task", conversation_id="child", worker=True,
                         stable_system_prefix=prefix)
    state = _RunState(request=request, callbacks=RunCallbacks(), message=request.message)
    messages = await _build_messages(SimpleNamespace(_skills=None, _projects=None), state)
    assert messages[0].content == prefix
    provider_system = "\n\n".join(str(m.content) for m in messages if getattr(m, "type", "") == "system")
    assert provider_system.startswith(prefix)
    assert find_stable_prefix(provider_system) == prefix
    print("W3-9 child prompt prefix PASS")

asyncio.run(main())
