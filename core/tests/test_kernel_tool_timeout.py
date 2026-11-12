# SPDX-License-Identifier: Apache-2.0
"""Per-call tool deadlines, non-cancelling fan-out, and structured tool errors.

These tests exercise :class:`atlas.engine.kernel.tools.ToolScheduler` only. The
scheduler dispatch callback is a fake, so nothing here crosses a process or
service boundary and the module stays in the default ``unit`` lane.
"""
from __future__ import annotations

import asyncio

import pytest

from atlas.engine.kernel import tools as tools_module
from atlas.engine.kernel.state import ToolReceipt
from atlas.engine.kernel.tool_errors import (
    ToolTimeoutError,
    error_from_exception,
    error_output,
    tail_text,
)
from atlas.engine.kernel.tools import ToolScheduler, resolve_tool_timeout


def _call(call_id: str, name: str, **arguments) -> dict:
    return {
        "id": call_id,
        "function": {"name": name, "arguments": arguments or {"path": "x"}},
    }


def _read_only(_name: str, _args: dict) -> bool:
    return True


class CommandFailedError(RuntimeError):
    """A handler exception carrying process evidence, like a real exec failure."""

    def __init__(self, message: str, *, exit_code: int, stderr: str) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.stderr = stderr


# --------------------------------------------------------------------------- #
# deadline policy
# --------------------------------------------------------------------------- #
def test_timeout_families_are_long_for_build_shell_and_short_for_reads():
    assert resolve_tool_timeout("terminal") == 600.0
    assert resolve_tool_timeout("exec_command") == 900.0
    assert resolve_tool_timeout("web_search") == 120.0
    assert resolve_tool_timeout("apply_patch") == 180.0
    assert resolve_tool_timeout("read_file") == 60.0
    # Unknown tools fall back to the documented global default, never to "no limit".
    assert resolve_tool_timeout("totally_unknown_tool") == 300.0


def test_env_overrides_beat_family_defaults(monkeypatch):
    monkeypatch.setenv("ATLAS_TOOL_TIMEOUT_SECONDS", "45")
    assert resolve_tool_timeout("read_file") == 45.0
    assert resolve_tool_timeout("terminal") == 45.0

    monkeypatch.setenv("ATLAS_TOOL_TIMEOUT_TERMINAL", "7.5")
    assert resolve_tool_timeout("terminal") == 7.5
    # The per-tool override does not leak into other tools.
    assert resolve_tool_timeout("read_file") == 45.0

    # Dotted names also accept their bare suffix.
    monkeypatch.setenv("ATLAS_TOOL_TIMEOUT_AST_GREP_RUN", "11")
    assert resolve_tool_timeout("coding.ast_grep.run") == 11.0


def test_invalid_or_non_positive_overrides_are_ignored(monkeypatch):
    monkeypatch.setenv("ATLAS_TOOL_TIMEOUT_READ_FILE", "not-a-number")
    assert resolve_tool_timeout("read_file") == 60.0
    monkeypatch.setenv("ATLAS_TOOL_TIMEOUT_READ_FILE", "0")
    assert resolve_tool_timeout("read_file") == 60.0
    monkeypatch.setenv("ATLAS_TOOL_TIMEOUT_READ_FILE", "-3")
    assert resolve_tool_timeout("read_file") == 60.0


# --------------------------------------------------------------------------- #
# one hung call must not hang the run
# --------------------------------------------------------------------------- #
async def test_single_call_times_out_with_structured_result(monkeypatch):
    monkeypatch.setenv("ATLAS_TOOL_TIMEOUT_READ_FILE", "0.05")

    async def dispatch(call_id, name, args):
        await asyncio.sleep(5)
        return {"data": "never"}

    scheduler = ToolScheduler(dispatch, read_only=_read_only)
    result = await asyncio.wait_for(scheduler.execute(_call("c1", "read_file")), timeout=3)

    assert result.receipt.state == "failed"
    assert result.receipt.error_code == "timeout"
    assert result.receipt.retryable is True
    assert result.receipt.output_ref is None
    assert result.timed_out is True
    assert result.output["error_code"] == "timeout"
    assert result.output["timed_out"] is True
    assert result.output["retryable"] is True
    assert result.output["outcome"] == "failed"
    assert result.output["error_info"]["code"] == "timeout"
    assert result.output["error_info"]["timeout_seconds"] == pytest.approx(0.05)
    # The model-visible text is prose with facts, not str(dict()).
    text = result.output["error"]
    assert isinstance(text, str)
    assert "code=timeout" in text
    assert "retryable=yes" in text
    assert "hint:" in text
    assert "ATLAS_TOOL_TIMEOUT" in text


async def test_timeout_carries_partial_output_from_the_host(monkeypatch):
    monkeypatch.setenv("ATLAS_TOOL_TIMEOUT_LOCAL_SHELL", "0.05")
    seen: list[str] = []

    async def dispatch(call_id, name, args):
        seen.append(f"{call_id}:{name}")
        await asyncio.sleep(5)
        return {"stdout": "never"}

    scheduler = ToolScheduler(
        dispatch,
        read_only=_read_only,
        partial_snapshot=lambda call_id, name: "line 1\nline 2\npartial tail",
    )
    result = await scheduler.execute(_call("c1", "local_shell"))

    assert seen == ["c1:local_shell"]
    assert result.timed_out is True
    assert result.output["partial_output"] == "line 1\nline 2\npartial tail"
    assert "partial output before the timeout" in result.output["error"]


async def test_a_timeout_does_not_cancel_the_rest_of_the_batch(monkeypatch):
    monkeypatch.setenv("ATLAS_TOOL_TIMEOUT_READ_FILE", "0.2")

    async def dispatch(call_id, name, args):
        if call_id == "slow":
            await asyncio.sleep(5)
        return {"data": call_id}

    scheduler = ToolScheduler(dispatch, max_concurrency=4, read_only=_read_only)
    calls = [_call("a", "read_file"), _call("slow", "read_file"), _call("b", "read_file")]
    results = await asyncio.wait_for(scheduler.run(calls), timeout=5)

    by_id = {result.call_id: result for result in results}
    assert by_id["a"].receipt.state == "completed"
    assert by_id["b"].receipt.state == "completed"
    assert by_id["slow"].receipt.state == "failed"
    assert by_id["slow"].receipt.error_code == "timeout"
    assert all(result.batch_state == "partial" for result in results)
    assert by_id["a"].receipt.batch_state == "partial"
    assert by_id["a"].receipt.timed_out_calls == ("slow",)
    assert set(by_id["a"].receipt.failed_calls) == {"slow"}
    # The siblings were told about the timeout; they were not cancelled.
    assert "cancelled" not in {result.receipt.state for result in results}


# --------------------------------------------------------------------------- #
# failure semantics: one bad sibling no longer kills the batch
# --------------------------------------------------------------------------- #
async def test_one_failing_sibling_lets_the_other_four_finish():
    finished: list[str] = []

    async def dispatch(call_id, name, args):
        try:
            await asyncio.sleep(0)
            if call_id == "c2":
                raise RuntimeError("synthetic sibling failure")
            return {"data": call_id}
        finally:
            finished.append(call_id)

    scheduler = ToolScheduler(dispatch, max_concurrency=5, read_only=_read_only)
    calls = [_call(f"c{index}", "read_file") for index in range(1, 6)]
    results = await asyncio.wait_for(scheduler.run(calls), timeout=5)

    # All five ran to a terminal receipt; the failure did not truncate the batch.
    assert sorted(finished) == ["c1", "c2", "c3", "c4", "c5"]
    assert [result.call_id for result in results] == ["c1", "c2", "c3", "c4", "c5"]
    states = {result.call_id: result.receipt.state for result in results}
    assert states == {
        "c1": "completed", "c2": "failed", "c3": "completed",
        "c4": "completed", "c5": "completed",
    }
    assert "cancelled" not in set(states.values())
    assert all(result.batch_state == "partial" for result in results)
    assert all(result.receipt.batch_state == "partial" for result in results)
    assert all(result.receipt.failed_calls == ("c2",) for result in results)
    # Real output survives for the successful siblings.
    assert results[0].output == {"data": "c1"}


async def test_all_failing_batch_reports_failed_not_partial():
    async def dispatch(call_id, name, args):
        raise RuntimeError(f"boom {call_id}")

    scheduler = ToolScheduler(dispatch, max_concurrency=3, read_only=_read_only)
    results = await scheduler.run([_call("c1", "read_file"), _call("c2", "read_file")])

    assert [result.receipt.state for result in results] == ["failed", "failed"]
    assert all(result.batch_state == "failed" for result in results)


async def test_batch_without_failures_reports_completed():
    async def dispatch(call_id, name, args):
        return {"data": call_id}

    scheduler = ToolScheduler(dispatch, max_concurrency=2, read_only=_read_only)
    results = await scheduler.run([_call("c1", "read_file"), _call("c2", "read_file")])

    assert [result.batch_state for result in results] == ["completed", "completed"]
    assert all(result.receipt.failed_calls == () for result in results)


async def test_external_cancellation_is_the_only_cancelled_batch():
    started = asyncio.Event()

    async def dispatch(call_id, name, args):
        started.set()
        await asyncio.sleep(5)
        return {"data": call_id}

    scheduler = ToolScheduler(dispatch, max_concurrency=3, read_only=_read_only)
    calls = [_call(f"c{index}", "read_file") for index in range(3)]
    task = asyncio.create_task(scheduler.run(calls))
    await started.wait()
    task.cancel()
    results = await asyncio.wait_for(task, timeout=5)

    assert [result.receipt.state for result in results] == ["cancelled"] * 3
    assert all(result.batch_state == "cancelled" for result in results)
    assert all(result.receipt.error_code == "cancelled" for result in results)
    # loop.py renders "Tool cancelled." for these; the text stays human-readable.
    assert "cancelled" in results[0].output["error"].lower()


async def test_serial_write_failure_does_not_stop_following_calls():
    ran: list[str] = []

    async def dispatch(call_id, name, args):
        ran.append(call_id)
        if call_id == "w1":
            raise RuntimeError("write failed")
        return {"data": call_id}

    scheduler = ToolScheduler(dispatch, read_only=_read_only)
    # apply_patch is never parallel: the loop serializes it.
    results = await scheduler.run([_call("w1", "apply_patch"), _call("w2", "apply_patch")])

    assert ran == ["w1", "w2"]
    assert [result.receipt.state for result in results] == ["failed", "completed"]
    assert [result.batch_state for result in results] == ["partial", "partial"]


# --------------------------------------------------------------------------- #
# structured errors
# --------------------------------------------------------------------------- #
async def test_handler_exception_yields_structured_error_and_readable_text():
    stderr = "\n".join(f"line {index}" for index in range(1, 21))

    async def dispatch(call_id, name, args):
        raise CommandFailedError("command failed", exit_code=2, stderr=stderr)

    scheduler = ToolScheduler(dispatch, read_only=_read_only)
    result = await scheduler.execute(_call("c1", "read_file"))
    output = result.output

    assert result.receipt.state == "failed"
    assert result.receipt.error_code == "nonzero_exit"
    assert result.receipt.retryable is False
    assert output["error_code"] == "nonzero_exit"
    assert output["exit_code"] == 2
    info = output["error_info"]
    assert info["error_type"] == "CommandFailedError"
    assert info["retryable"] is False
    assert info["exit_code"] == 2
    assert info["hint"]
    # Only the trailing lines are kept, bounded.
    assert info["stderr_tail"].splitlines() == [f"line {index}" for index in range(9, 21)]

    text = output["error"]
    assert text.startswith("CommandFailedError: command failed")
    assert "code=nonzero_exit" in text and "retryable=no" in text and "exit_code=2" in text
    assert "stderr tail (last 12 lines):" in text
    assert "line 20" in text and "line 1\n" not in text


async def test_tool_authored_error_text_is_preserved_verbatim():
    authored = "the file is locked by another program"

    async def dispatch(call_id, name, args):
        return {"is_error": True, "error": authored, "outcome": "failed"}

    scheduler = ToolScheduler(dispatch, read_only=_read_only)
    result = await scheduler.execute(_call("c1", "read_file"))

    # The tool's own sentence is never replaced by generated prose...
    assert result.output["error"] == authored
    # ...and the structured fields are added beside it, exactly once.
    assert result.output["error_code"] == "resource_busy"
    assert result.output["error_info"]["code"] == "resource_busy"
    assert result.receipt.error_code == "resource_busy"


async def test_policy_denial_is_structured_not_a_bare_string():
    async def dispatch(call_id, name, args):  # pragma: no cover - never reached
        raise AssertionError("denied calls must not dispatch")

    scheduler = ToolScheduler(dispatch, deny=["read_file"], read_only=_read_only)
    result = await scheduler.execute(_call("c1", "read_file"))

    assert result.receipt.state == "failed"
    assert result.receipt.error_code == "permission_denied"
    assert result.output["error_code"] == "permission_denied"
    assert result.output["error_info"]["error_type"] == "PermissionError"
    assert "code=permission_denied" in result.output["error"]


def test_tail_text_is_bounded_and_empty_safe():
    assert tail_text(None) is None
    assert tail_text("   ") is None
    assert tail_text("\n".join(str(index) for index in range(50))).splitlines() == [
        str(index) for index in range(38, 50)
    ]


def test_error_from_exception_classifies_common_failures():
    timeout = error_from_exception(ToolTimeoutError(1.5, name="terminal"), name="terminal")
    assert (timeout.code, timeout.retryable, timeout.timeout_seconds) == ("timeout", True, 1.5)

    not_found = error_from_exception(FileNotFoundError("missing.txt"))
    assert (not_found.code, not_found.retryable) == ("not_found", False)

    denied = error_from_exception(PermissionError("access is denied"))
    assert denied.code == "permission_denied"

    bad_args = error_from_exception(ValueError("bad arguments"))
    assert bad_args.code == "invalid_input"


def test_error_output_exposes_every_documented_field():
    error = error_from_exception(CommandFailedError("cmd failed", exit_code=7, stderr="err\n"))
    payload = error_output(error, outcome="failed")

    assert set(error.as_dict()) >= {
        "code", "message", "error_type", "retryable", "exit_code", "stderr_tail", "hint",
    }
    assert payload["is_error"] is True
    assert payload["outcome"] == "failed"
    assert isinstance(payload["error"], str)
    assert payload["error_info"] == error.as_dict()


# --------------------------------------------------------------------------- #
# receipt contract
# --------------------------------------------------------------------------- #
def test_tool_receipt_adds_cost_fields_without_changing_the_old_ones():
    receipt = ToolReceipt("c1", "read_file", "failed", 12, None)

    # Old fields keep their names, positions, and defaults.
    assert (receipt.id, receipt.name, receipt.state, receipt.duration_ms) == (
        "c1", "read_file", "failed", 12,
    )
    assert receipt.output_ref is None
    # New fields are defaults, so old positional construction still works.
    assert receipt.error_code is None
    assert receipt.retryable is False
    assert receipt.retry_count == 0
    assert receipt.prompt_tokens is None
    assert receipt.completion_tokens is None
    assert receipt.batch_state == "completed"
    assert receipt.failed_calls == ()
    assert receipt.timed_out_calls == ()

    payload = receipt.as_dict()
    assert payload["state"] == "failed" and payload["duration_ms"] == 12
    assert "output_ref" in payload
    assert payload["error_code"] is None and payload["retry_count"] == 0
    assert payload["prompt_tokens"] is None and payload["completion_tokens"] is None
    assert payload["batch_state"] == "completed"
    assert payload["failed_calls"] == [] and payload["timed_out_calls"] == []


async def test_receipt_surfaces_the_batch_through_as_dict_for_persistence():
    async def dispatch(call_id, name, args):
        if call_id == "bad":
            raise RuntimeError("nope")
        return {"data": call_id}

    scheduler = ToolScheduler(dispatch, max_concurrency=2, read_only=_read_only)
    results = await scheduler.run([_call("ok", "read_file"), _call("bad", "read_file")])

    for result in results:
        persisted = result.receipt.as_dict()
        assert persisted["batch_state"] == "partial"
        assert persisted["failed_calls"] == ["bad"]
        assert persisted["timed_out_calls"] == []
        # loop.py branches on these two values exactly as before.
        assert persisted["state"] in {"completed", "failed", "cancelled"}
        assert isinstance(persisted["duration_ms"], int)


def test_scheduler_exposes_the_public_deadline_helper():
    scheduler = ToolScheduler(lambda *_: None)
    assert scheduler.timeout_for("read_file") == tools_module.resolve_tool_timeout("read_file")
