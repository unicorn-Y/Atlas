import pytest

from atlas.engine.kernel.state import RunTerminalStatus, TurnEndReason


@pytest.mark.unit
@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (RunTerminalStatus.COMPLETED, TurnEndReason.COMPLETED),
        (RunTerminalStatus.USER_INTERRUPTED, TurnEndReason.USER_INTERRUPTED),
        (RunTerminalStatus.BUDGET_EXCEEDED, TurnEndReason.BUDGET_EXCEEDED),
        (RunTerminalStatus.ERROR, TurnEndReason.FAILED),
    ],
)
def test_terminal_run_status_has_typed_turn_end_reason(status, reason):
    assert TurnEndReason.from_terminal_status(status) is reason
