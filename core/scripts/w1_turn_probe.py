"""Focused proof for explicit turn terminals and interruption call repair."""

from atlas.kernel.repair import repair_unpaired_tool_calls
from atlas.kernel.state import RunPhase, RunState, RunTerminalStatus


def main() -> None:
    state = RunState("probe-run", "probe-session")
    state.transition(RunPhase.INTERRUPTED)
    state.terminal_status = RunTerminalStatus.USER_INTERRUPTED
    assert state.phase is RunPhase.INTERRUPTED
    assert state.terminal_status.value == "user_interrupted"

    recovered, repairs = repair_unpaired_tool_calls([{
        "role": "assistant", "content": "",
        "tool_calls": [{"id": "pending-1", "function": {
            "name": "write_file", "arguments": "{}",
        }}],
    }], started_ids={"pending-1"}, run_id="probe-run")
    assert len(repairs) == 1 and repairs[0]["state"] == "unknown"
    assert recovered[-1]["tool_call_id"] == "pending-1"
    assert recovered[-1]["is_error"] is True
    assert "outcome is unknown" in recovered[-1]["content"]
    print("terminal state: interrupted -> user_interrupted")
    print("pending tool: paired with durable unknown-outcome placeholder")
    print("W1-8 TURN PROBE PASS")


if __name__ == "__main__":
    main()
