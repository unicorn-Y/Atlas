import pytest

from atlas.engine.kernel.loop import authorize_local_sandbox_request


@pytest.mark.unit
@pytest.mark.asyncio
async def test_non_docker_escalation_uses_one_call_approval_and_fails_closed():
    calls = []

    async def approve(call_id, tool_name, arguments):
        calls.append((call_id, tool_name, arguments))
        return "allow"

    result = await authorize_local_sandbox_request(
        {"sandbox_permissions": "workspace-write", "justification": "Build output"},
        approve, tool_name="local_exec", tool_call_id="tool-1",
        sandbox_executor_available=False,
    )

    assert len(calls) == 1
    assert calls[0][2]["_approval_no_always"] is True
    assert result["approved"] is True
    assert result["sandbox_enforced"] is False
    assert result["is_error"] is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unapproved_escalation_does_not_report_grant():
    async def deny(*_args):
        return "deny"

    result = await authorize_local_sandbox_request(
        {"sandbox_permissions": "danger-full-access", "justification": "Need access"},
        deny, tool_name="local_shell", tool_call_id="tool-2",
        sandbox_executor_available=False,
    )

    assert result["approved"] is False
    assert result["sandbox_enforced"] is False
