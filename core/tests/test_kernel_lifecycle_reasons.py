import asyncio
import pytest

from atlas.engine.kernel.loop import AtlasKernel
from atlas.engine.kernel.state import (
    RunTerminalStatus, StepEndReason, TurnConclusion, TurnEndReason, TurnLifecycle,
)


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


@pytest.mark.unit
def test_turn_lifecycle_tracks_model_steps_and_typed_step_end():
    turn = TurnLifecycle("run-1")

    first = turn.begin_step()
    assert turn.end_step(first, StepEndReason.TOOL_CALLS) is True
    assert turn.end_step(first, StepEndReason.RESPONSE) is False

    second = turn.begin_step()
    assert second == 2
    assert turn.end_step(second, StepEndReason.RESPONSE) is True


@pytest.mark.unit
def test_turn_lifecycle_closes_with_typed_reason_and_rejects_new_steps():
    turn = TurnLifecycle("run-2")
    step = turn.begin_step()
    turn.end_step(step, StepEndReason.RESPONSE)

    assert turn.end_turn(TurnEndReason.COMPLETED) is True
    assert turn.end_reason is TurnEndReason.COMPLETED
    with pytest.raises(ValueError, match="turn has ended"):
        turn.begin_step()


@pytest.mark.unit
def test_tool_can_conclude_turn_with_typed_final_response():
    conclusion = TurnConclusion()

    conclusion.conclude("TURN_DONE")

    assert conclusion.requested is True
    assert conclusion.response == "TURN_DONE"


@pytest.mark.unit
def test_idle_maintenance_runs_without_changing_turn_state(tmp_path):
    kernel = AtlasKernel(data_dir=tmp_path)
    observed = []

    async def maintenance():
        observed.append(kernel._active_runs)

    assert asyncio.run(kernel.runMaintenance(maintenance)) is True
    assert observed == [0]
    assert kernel._active_runs == 0


@pytest.mark.unit
def test_idle_maintenance_is_skipped_while_a_turn_is_active(tmp_path):
    kernel = AtlasKernel(data_dir=tmp_path)
    kernel._active_runs = 1
    observed = []

    assert asyncio.run(kernel.runMaintenance(lambda: observed.append("ran"))) is False
    assert observed == []
