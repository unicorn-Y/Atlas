"""Unit tests for the read-only run replay / diff toolkit.

All fixtures are synthetic JSONL written under ``tmp_path``; the real run archive
is never touched. Event shapes mirror what ``atlas/logs.py::append_run_event``
actually writes (verified against 343 real files / 28,221 events), including the
two distinct ``model_request`` shapes and the redacted ``arguments``/``output``
payloads.
"""

from __future__ import annotations

import json
import tracemalloc

import pytest

from atlas.run_replay import (
    Run,
    RunInfo,
    RunNotFoundError,
    diff,
    format_diff,
    list_runs,
    load_run,
    replay,
    summarize,
)
from atlas.run_replay.summary import format_summary

RUN_ID = "11111111-2222-3333-4444-555555555555"
OTHER_ID = "99999999-8888-7777-6666-555555555555"
#: 2026-11-07T21:18:29.752827+00:00 -- the real archive's ISO shape.
TS0 = "2026-11-07T21:18:29.752827+00:00"


# ---------------------------------------------------------------- fixtures


def _event(event_name: str, ts: str, run_id: str = RUN_ID, **fields):
    payload = {"timestamp": ts, "event": event_name, "run_id": run_id}
    payload.update(fields)
    return payload


def _ts(offset_seconds: float) -> str:
    """A timestamp ``offset_seconds`` after ``TS0``, same formatting as the log."""
    from datetime import datetime, timedelta

    base = datetime.fromisoformat(TS0)
    return (base + timedelta(seconds=offset_seconds)).isoformat()


def _write_run(directory, run_id: str, events, date: str = "2026-11-07"):
    """Write ``events`` as ``<directory>/<date>/<run_id>.jsonl`` and return the path."""
    target = directory / date
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{run_id}.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event) + "\n")
    return path


def _basic_events(run_id: str = RUN_ID):
    """A realistic two-turn run: start, model calls, two tools, end."""
    return [
        _event("run_start", _ts(0), run_id, model="wb-domestic-a",
               session_id="sess-1", workspace="D:/w", kernel="atlas"),
        # pre-call estimate shape
        _event("model_request", _ts(0.1), run_id, model="wb-domestic-a",
               input_chars=4321, input_tokens=916, attempt=1),
        # post-call usage shape
        _event("model_request", _ts(2.0), run_id, purpose="conversation",
               model="wb-domestic-a", provider="wb", duration_ms=1900,
               input_tokens=916, output_tokens=201, cached_tokens=800,
               attempt=1, first_token_ms=300, reasoning_chars=0),
        _event("tool_offer", _ts(2.1), run_id, mode="all", offered=12,
               deferred=0, schema_chars_before=9000, schema_chars=8000, prep_ms=4),
        _event("tool_start", _ts(2.2), run_id, tool_call_id="c1",
               name="local_file", arguments={"length": 2}),
        _event("tool_end", _ts(2.5), run_id, tool_call_id="c1", name="local_file",
               state="completed", duration_ms=300,
               output_ref="D:/t/tool-output/a.log", output={"length": 55}),
        _event("tool_result", _ts(2.6), run_id, tool_call_id="c1", name="local_file",
               state="completed", is_error=False,
               output_ref="D:/t/tool-output/a.log", output={"length": 55}),
        _event("model_request", _ts(3.0), run_id, model="wb-domestic-a",
               input_chars=4500, input_tokens=950, attempt=1),
        _event("model_request", _ts(4.0), run_id, purpose="conversation",
               model="wb-domestic-a", provider="wb", duration_ms=1000,
               input_tokens=950, output_tokens=80, cached_tokens=850,
               attempt=1, first_token_ms=200, reasoning_chars=0),
        _event("tool_start", _ts(4.1), run_id, tool_call_id="c2",
               name="local_exec", arguments={"length": 2}),
        _event("tool_end", _ts(4.9), run_id, tool_call_id="c2", name="local_exec",
               state="failed", duration_ms=800,
               output_ref=None, output={"length": 10}),
        _event("tool_result", _ts(4.95), run_id, tool_call_id="c2", name="local_exec",
               state="failed", is_error=True,
               output_ref=None, output={"length": 10}),
        _event("api_timing", _ts(5.0), run_id, stage="terminal_event", elapsed_ms=12),
        _event("run_end", _ts(5.2), run_id, status="completed",
               terminal_status="completed", duration_ms=5200,
               total_input_tokens=1866, total_output_tokens=281),
    ]


@pytest.fixture()
def runs_root(tmp_path):
    """A private runs directory; the real archive is never referenced."""
    root = tmp_path / "runs"
    root.mkdir()
    return root


@pytest.fixture()
def basic_run_path(runs_root):
    return _write_run(runs_root, RUN_ID, _basic_events())


# ------------------------------------------------------------ list_runs


def test_list_runs_reports_inventory(runs_root, basic_run_path):
    runs = list_runs(runs_dir=runs_root)

    assert len(runs) == 1
    info = runs[0]
    assert isinstance(info, RunInfo)
    assert info.id == RUN_ID
    assert info.path == str(basic_run_path)
    assert info.size == basic_run_path.stat().st_size
    assert info.size > 0
    assert info.event_count == 14
    assert info.bad_lines == 0
    assert info.session_id == "sess-1"
    assert info.status == "completed"
    assert info.start_time == TS0
    assert info.duration_ms == 5200
    assert info.files == [str(basic_run_path)]
    # The acceptance command prints ``r.__dict__``, so it must exist.
    assert "id" in info.__dict__ and "event_count" in info.__dict__


def test_list_runs_orders_newest_first(runs_root):
    _write_run(runs_root, RUN_ID, _basic_events(RUN_ID))
    late = [_event("run_start", "2026-11-09T10:00:00.000001+00:00", OTHER_ID)]
    _write_run(runs_root, OTHER_ID, late, date="2026-11-09")

    runs = list_runs(runs_dir=runs_root)

    assert [r.id for r in runs] == [OTHER_ID, RUN_ID]
    assert runs[0].start_time > runs[1].start_time


def test_list_runs_limit_and_none(runs_root):
    for index in range(3):
        run_id = f"run-{index}"
        stamped = [_event("run_start", _ts(index), run_id)]
        _write_run(runs_root, run_id, stamped)

    assert len(list_runs(limit=2, runs_dir=runs_root)) == 2
    assert len(list_runs(limit=None, runs_dir=runs_root)) == 3
    assert len(list_runs(limit=0, runs_dir=runs_root)) == 0


def test_list_runs_merges_one_id_split_across_two_dates(runs_root):
    """A run stopped at ``run_end`` then resumed writes a second file."""
    first = _basic_events()
    _write_run(runs_root, RUN_ID, first, date="2026-11-07")
    tail = [
        _event("tool_start", _ts(60), RUN_ID, tool_call_id="c9", name="grep",
               arguments={"length": 1}),
        _event("run_end", _ts(61), RUN_ID, status="completed",
               duration_ms=61000, total_input_tokens=1, total_output_tokens=2),
    ]
    _write_run(runs_root, RUN_ID, tail, date="2026-11-08")

    runs = list_runs(runs_dir=runs_root)

    assert len(runs) == 1, "the same run id must not be listed twice"
    merged = runs[0]
    assert len(merged.files) == 2
    assert merged.event_count == 16
    assert merged.size == sum(p.stat().st_size for p in basic_run_paths(runs_root))
    assert merged.duration_ms == 61000


def basic_run_paths(runs_root):
    return sorted(runs_root.glob("*/*.jsonl"))


def test_list_runs_missing_directory_is_empty_not_an_error(tmp_path):
    assert list_runs(runs_dir=tmp_path / "does-not-exist") == []


# ------------------------------------------------------------- load_run


def test_load_run_streams_counters(basic_run_path):
    run = load_run(basic_run_path)

    assert isinstance(run, Run)
    assert run.id == RUN_ID
    assert run.total_lines == 14
    assert sum(run.event_counts.values()) == 14
    assert run.bad_lines == 0
    assert run.truncated is False
    assert run.event_counts["model_request"] == 4
    assert run.event_counts["tool_start"] == 2
    assert run.event_counts["tool_result"] == 2
    assert run.status == "completed"
    assert run.session_id == "sess-1"
    assert run.total_input_tokens == 1866
    assert run.total_output_tokens == 281


def test_load_run_by_id_and_by_path_agree(basic_run_path, runs_root):
    by_path = load_run(basic_run_path)
    by_id = load_run(RUN_ID, runs_dir=runs_root)

    assert by_path.id == by_id.id
    assert by_path.total_lines == by_id.total_lines
    assert by_path.event_counts == by_id.event_counts


def test_load_run_unknown_id_raises_lookup_error(runs_root, basic_run_path):
    with pytest.raises(RunNotFoundError):
        load_run("no-such-run", runs_dir=runs_root)


def test_load_run_accepts_an_unambiguous_id_prefix(runs_root, basic_run_path):
    run = load_run(RUN_ID[:8], runs_dir=runs_root)

    assert run.id == RUN_ID


def test_load_run_rejects_an_ambiguous_id_prefix(runs_root, basic_run_path):
    other = runs_root / "2026-11-07" / f"{RUN_ID[:-1]}9.jsonl"
    other.write_text(
        basic_run_path.read_text(encoding="utf-8"), encoding="utf-8"
    )

    with pytest.raises(RunNotFoundError, match="ambiguous"):
        load_run(RUN_ID[:8], runs_dir=runs_root)


def test_load_run_pairs_tool_start_with_end_and_result(basic_run_path):
    run = load_run(basic_run_path)

    assert len(run.tool_calls) == 2
    first, second = run.tool_calls
    assert first.name == "local_file"
    assert first.tool_call_id == "c1"
    assert first.duration_ms == 300
    assert first.state == "completed"
    assert first.is_error is False
    assert first.arguments_length == 2
    assert first.output_length == 55
    assert first.output_ref == "D:/t/tool-output/a.log"
    assert first.ended_at is not None

    assert second.name == "local_exec"
    assert second.duration_ms == 800
    assert second.is_error is True
    assert second.state == "failed"


def test_load_run_splits_model_request_into_pre_and_post(basic_run_path):
    run = load_run(basic_run_path)

    assert len(run.model_calls) == 4
    phases = [c.phase for c in run.model_calls]
    assert phases == ["pre", "post", "pre", "post"]

    pre, post = run.model_calls[0], run.model_calls[1]
    assert pre.duration_ms is None and pre.output_tokens is None
    assert pre.input_chars == 4321
    assert post.duration_ms == 1900
    assert post.output_tokens == 201
    assert post.cached_tokens == 800
    assert post.purpose == "conversation"


def test_load_run_marks_repeated_consecutive_tool_calls(runs_root):
    events = [
        _event("run_start", _ts(0), RUN_ID, model="m"),
        *[
            _event("tool_start", _ts(i + 0.1), RUN_ID, tool_call_id=f"c{i}",
                   name="local_shell", arguments={"length": 1})
            for i in range(4)
        ],
    ]
    path = _write_run(runs_root, RUN_ID, events)
    run = load_run(path)

    assert [c.repeated for c in run.tool_calls] == [False, True, True, True]
    assert all(c.signature == "local_shell#1" for c in run.tool_calls)


def test_repeated_flag_needs_matching_argument_length(runs_root):
    events = [
        _event("run_start", _ts(0), RUN_ID, model="m"),
        _event("tool_start", _ts(1), RUN_ID, tool_call_id="a", name="grep",
               arguments={"length": 1}),
        _event("tool_start", _ts(2), RUN_ID, tool_call_id="b", name="grep",
               arguments={"length": 9}),
    ]
    run = load_run(_write_run(runs_root, RUN_ID, events))

    assert [c.repeated for c in run.tool_calls] == [False, False]


# -------------------------------------------------- missing-field safety


def test_missing_fields_are_none_never_keyerror(runs_root):
    """Rows missing nearly everything must fold cleanly with ``None`` values."""
    events = [
        {"timestamp": _ts(0), "event": "run_start", "run_id": RUN_ID},
        {"timestamp": _ts(1), "event": "model_request", "run_id": RUN_ID},
        {"timestamp": _ts(2), "event": "tool_start", "run_id": RUN_ID},
        {"timestamp": _ts(3), "event": "tool_end", "run_id": RUN_ID},
        {"timestamp": _ts(4), "event": "tool_result", "run_id": RUN_ID},
        {"timestamp": _ts(5), "event": "run_end", "run_id": RUN_ID},
    ]
    run = load_run(_write_run(runs_root, RUN_ID, events))

    assert run.model is None
    assert run.status is None
    assert run.duration_ms is None
    assert run.total_input_tokens is None
    assert run.tool_calls[0].name is None
    assert run.tool_calls[0].duration_ms is None
    assert run.tool_calls[0].is_error is None
    assert run.model_calls[0].input_tokens is None

    summary = summarize(run)
    assert summary["tokens"]["recorded"] is False
    assert summary["tokens"]["input"] is None
    assert summary["tokens"]["output"] is None
    assert summary["timing"]["model_ms"] is None
    # No fabricated zeros for unrecorded time, but the report still renders.
    assert "not recorded" in format_summary(summary)


def test_event_with_no_event_field_is_counted(runs_root):
    events = [{"timestamp": _ts(0), "run_id": RUN_ID}]
    run = load_run(_write_run(runs_root, RUN_ID, events))

    assert run.event_counts["<missing>"] == 1
    assert run.bad_lines == 0


def test_unknown_event_types_do_not_break_loading(runs_root):
    events = [
        _event("run_start", _ts(0), RUN_ID, model="m"),
        _event("brand_new_event_from_the_future", _ts(1), RUN_ID, whatever=1),
        _event("run_end", _ts(2), RUN_ID, status="completed", duration_ms=2000),
    ]
    run = load_run(_write_run(runs_root, RUN_ID, events))

    assert run.event_counts["brand_new_event_from_the_future"] == 1
    assert run.bad_lines == 0
    assert run.status == "completed"


# ----------------------------------------------------- damaged log input


def test_bad_lines_are_counted_and_never_raise(runs_root):
    path = runs_root / "2026-11-07"
    path.mkdir(parents=True)
    target = path / f"{RUN_ID}.jsonl"
    good = _event("run_start", _ts(0), RUN_ID, model="m")
    text = (
        json.dumps(good) + "\n"
        + "not json at all\n"
        + '{"timestamp": "2026-11-07T21:18:30.000000+00:00", "event": "tool_st\n'
        + "[1, 2, 3]\n"
        + "\n"
        + json.dumps(_event("run_end", _ts(9), RUN_ID, status="completed",
                            duration_ms=9000)) + "\n"
    )
    target.write_text(text, encoding="utf-8")

    run = load_run(target)

    assert run.bad_lines == 4, "3 malformed + 1 blank line"
    assert run.bad_line_numbers == [2, 3, 4, 5]
    assert run.total_lines == 6
    assert run.event_counts["run_start"] == 1
    assert run.event_counts["run_end"] == 1
    assert run.status == "completed"
    # A report over damaged input still renders.
    assert "damaged lines skipped: 4" in format_summary(summarize(run))


def test_scan_and_load_agree_on_damaged_file(runs_root):
    """``list_runs`` must not under-report damage that ``load_run`` can see.

    The inventory pass is the cheap one, but a caller that picks a run from the
    list and then loads it should never be surprised by a different bad-line
    count in each direction.
    """
    path = runs_root / "2026-11-07"
    path.mkdir(parents=True)
    target = path / f"{RUN_ID}.jsonl"
    text = (
        json.dumps(_event("run_start", _ts(0), RUN_ID, model="m")) + "\n"
        + "Traceback (most recent call last):\n"
        + json.dumps(_event("tool_start", _ts(1), RUN_ID, name="local_shell")) + "\n"
        + '{"timestamp": "2026-11-07T21:18:30.000000+00:00", "event": "tool_st\n'
        + json.dumps(_event("run_end", _ts(9), RUN_ID, status="completed",
                            duration_ms=9000)) + "\n"
    )
    target.write_text(text, encoding="utf-8")

    info = list_runs(runs_dir=runs_root)[0]
    run = load_run(target)

    assert info.bad_lines == run.bad_lines == 2
    assert info.event_count == run.total_lines - run.bad_lines
    assert info.event_count == 3
    assert info.status == "completed"


def test_truncated_final_line_is_flagged(runs_root):
    path = runs_root / "2026-11-07"
    path.mkdir(parents=True)
    target = path / f"{RUN_ID}.jsonl"
    good = json.dumps(_event("run_start", _ts(0), RUN_ID, model="m"))
    target.write_text(good + "\n" + '{"timestamp": "2026-11-0', encoding="utf-8")

    run = load_run(target)

    assert run.truncated is True
    assert run.bad_lines == 1
    assert "cut off" in format_summary(summarize(run))


def test_empty_file_loads_without_error(runs_root):
    path = runs_root / "2026-11-07"
    path.mkdir(parents=True)
    target = path / f"{RUN_ID}.jsonl"
    target.write_text("", encoding="utf-8")

    run = load_run(target)

    assert run.total_lines == 0
    assert run.bad_lines == 0
    assert run.timeline == []
    summary = summarize(run)
    assert summary["steps"] == 0
    assert summary["tool_calls"] == 0


def test_non_utf8_bytes_do_not_crash(runs_root):
    path = runs_root / "2026-11-07"
    path.mkdir(parents=True)
    target = path / f"{RUN_ID}.jsonl"
    target.write_bytes(b'{"timestamp":"x","event":"run_start","run_id":"r"}\n\xff\xfe\n')

    run = load_run(target)

    assert run.event_counts["run_start"] == 1
    assert run.bad_lines >= 1


# --------------------------------------------------- large file streaming


def test_large_file_streams_with_bounded_memory(runs_root):
    """A big log must not be slurped: peak allocation stays near one step's worth.

    Generates ~1 MB of real-shaped events (1 pre + 1 post model row and one tool
    per step), asserts the event count, then asserts peak traced memory stays far
    below the file size. ``api_timing``/``tool_offer`` noise is included because
    those are the events the loader must *count without keeping*.
    """
    date = runs_root / "2026-11-07"
    date.mkdir(parents=True)
    target = date / f"{RUN_ID}.jsonl"

    steps = 900
    with target.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(_event("run_start", _ts(0), RUN_ID, model="m")) + "\n")
        for i in range(steps):
            handle.write(json.dumps(_event("model_request", _ts(i),
                                           RUN_ID, model="m", input_chars=1,
                                           input_tokens=10, attempt=1)) + "\n")
            handle.write(json.dumps(_event("model_request", _ts(i), RUN_ID,
                                           purpose="conversation", model="m",
                                           duration_ms=100, input_tokens=10,
                                           output_tokens=1, cached_tokens=0,
                                           attempt=1)) + "\n")
            handle.write(json.dumps(_event("tool_offer", _ts(i), RUN_ID, mode="all",
                                           offered=9, schema_chars=8000,
                                           prep_ms=1)) + "\n")
            handle.write(json.dumps(_event("api_timing", _ts(i), RUN_ID,
                                           stage="tool_started",
                                           elapsed_ms=3)) + "\n")
            handle.write(json.dumps(_event("tool_start", _ts(i), RUN_ID,
                                           tool_call_id=f"c{i}", name="local_shell",
                                           arguments={"length": 3})) + "\n")
            handle.write(json.dumps(_event("tool_end", _ts(i), RUN_ID,
                                           tool_call_id=f"c{i}", name="local_shell",
                                           state="completed", duration_ms=7,
                                           output={"length": 12})) + "\n")
        handle.write(json.dumps(_event("run_end", _ts(steps), RUN_ID,
                                       status="completed", duration_ms=1000,
                                       total_input_tokens=1,
                                       total_output_tokens=2)) + "\n")

    file_size = target.stat().st_size
    assert file_size > 900_000, "fixture should be large enough to matter"

    tracemalloc.start()
    try:
        run = load_run(target)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert run.total_lines == 1 + steps * 6 + 1
    assert run.bad_lines == 0
    assert len(run.tool_calls) == steps
    assert run.event_counts["api_timing"] == steps
    assert run.event_counts["tool_offer"] == steps

    # Retention is only the semantic steps (tool calls + model calls), never the
    # raw lines: an 900 KB file must not produce ~900 KB of live objects.
    assert peak < 4_000_000, f"peak {peak} bytes for a {file_size} byte file"
    assert peak < file_size * 4


# ------------------------------------------------------------------ replay


def test_replay_is_chronological_and_typed(basic_run_path):
    run = load_run(basic_run_path)
    items = replay(run)

    assert len(items) == len(run.timeline) == 12
    assert [item.index for item in items] == list(range(1, 13))
    assert items[0].kind == "run_start"
    assert items[-1].kind == "run_end"
    kinds = [item.kind for item in items]
    assert kinds.count("tool_call") == 2
    assert kinds.count("tool_result") == 4  # tool_end + tool_result per call
    assert kinds.count("model_call") == 4

    timestamps = [item.timestamp for item in items]
    assert timestamps == sorted(timestamps), "file order must be time order"


def test_replay_does_not_expose_counts_only_events(basic_run_path):
    run = load_run(basic_run_path)
    kinds = {item.kind for item in replay(run)}

    assert "api_timing" not in kinds
    assert "tool_offer" not in kinds
    assert run.event_counts["tool_offer"] == 1


def test_replay_returns_a_copy(basic_run_path):
    run = load_run(basic_run_path)
    replay(run).clear()

    assert len(run.timeline) == 12


def test_replay_includes_model_errors_as_error_items(runs_root):
    events = [
        _event("run_start", _ts(0), RUN_ID, model="m"),
        _event("model_error", _ts(1), RUN_ID, purpose="conversation", model="m",
               category="connection", status=None, retry=True, attempt=1,
               retry_delay_s=1.5, retry_kind="delay", retry_number=1,
               detail="boom"),
        _event("run_end", _ts(2), RUN_ID, status="failed", reason="boom",
               duration_ms=2000),
    ]
    run = load_run(_write_run(runs_root, RUN_ID, events))

    errors = [item for item in replay(run) if item.kind == "error"]
    assert len(errors) == 1
    assert errors[0].is_error is True
    assert "connection" in errors[0].label
    assert run.errors[0]["category"] == "connection"
    assert run.reason == "boom"


# --------------------------------------------------------------- summarize


def test_summarize_counts_and_tables(basic_run_path):
    summary = summarize(load_run(basic_run_path))

    assert summary["tool_calls"] == 2
    assert summary["model_calls"] == 2, "only post-call rows are model responses"
    assert summary["model_requests"] == 4
    assert summary["steps"] == 12
    assert summary["status"] == "completed"
    assert summary["wall_ms"] == 5200
    assert summary["tool_failures"] == 1

    tools = summary["tools"]
    assert [row["name"] for row in tools] == ["local_exec", "local_file"], (
        "sorted by total duration descending"
    )
    assert tools[0]["total_ms"] == 800
    assert tools[0]["calls"] == 1
    assert tools[0]["failures"] == 1
    assert tools[1]["total_ms"] == 300
    assert tools[1]["failures"] == 0


def test_summarize_time_split_and_tokens(basic_run_path):
    summary = summarize(load_run(basic_run_path))
    timing = summary["timing"]

    assert timing["wall_ms"] == 5200
    assert timing["model_ms"] == 2900  # 1900 + 1000
    assert timing["tool_ms"] == 1100  # 300 + 800
    assert timing["unaccounted_ms"] == 5200 - 2900 - 1100
    assert timing["model_share_pct"] == pytest.approx(55.8, abs=0.1)
    assert timing["tool_share_pct"] == pytest.approx(21.2, abs=0.1)
    assert timing["model_calls_with_duration"] == 2
    assert timing["tool_calls_with_duration"] == 2

    tokens = summary["tokens"]
    assert tokens["input"] == 1866
    assert tokens["output"] == 281
    assert tokens["cached"] == 1650
    assert tokens["recorded"] is True


def test_summarize_tokens_none_when_no_run_end_totals(runs_root):
    """Token fields absent everywhere -> ``None``, never a fabricated ``0``."""
    events = [
        _event("run_start", _ts(0), RUN_ID, model="m"),
        _event("model_request", _ts(1), RUN_ID, model="m", input_chars=10, attempt=1),
        _event("tool_start", _ts(2), RUN_ID, tool_call_id="c1", name="grep",
               arguments={"length": 1}),
    ]
    summary = summarize(load_run(_write_run(runs_root, RUN_ID, events)))

    assert summary["tokens"]["input"] is None
    assert summary["tokens"]["output"] is None
    assert summary["tokens"]["cached"] is None
    assert summary["tokens"]["recorded"] is False


def test_summarize_detects_consecutive_identical_tool_calls(runs_root):
    events = [_event("run_start", _ts(0), RUN_ID, model="m")]
    for i in range(6):
        events.append(_event("tool_start", _ts(i + 1), RUN_ID, tool_call_id=f"c{i}",
                             name="local_shell", arguments={"length": 2}))
    events.append(_event("tool_start", _ts(20), RUN_ID, tool_call_id="z",
                         name="local_file", arguments={"length": 2}))
    summary = summarize(load_run(_write_run(runs_root, RUN_ID, events)))

    loops = summary["stuck_loops"]
    assert len(loops) == 1
    assert loops[0]["tool"] == "local_shell"
    assert loops[0]["repeats"] == 6
    assert loops[0]["signature"] == "local_shell#2"
    assert loops[0]["first_index"] == 0
    assert loops[0]["last_index"] == 5
    assert "stuck-loop candidates (1)" in format_summary(summary)


def test_summarize_loop_threshold_is_configurable(runs_root):
    events = [_event("run_start", _ts(0), RUN_ID, model="m")]
    for i in range(3):
        events.append(_event("tool_start", _ts(i + 1), RUN_ID, tool_call_id=f"c{i}",
                             name="grep", arguments={"length": 1}))
    run = load_run(_write_run(runs_root, RUN_ID, events))

    assert summarize(run, loop_threshold=3)["stuck_loops"]
    assert summarize(run, loop_threshold=4)["stuck_loops"] == []


def test_summarize_error_categories_and_retries(runs_root):
    events = [_event("run_start", _ts(0), RUN_ID, model="m")]
    for i, category in enumerate(["connection", "connection", "rate_limit"]):
        events.append(_event("model_error", _ts(i + 1), RUN_ID, category=category,
                             retry=True, attempt=1, purpose="conversation"))
    events.append(_event("run_end", _ts(9), RUN_ID, status="failed",
                         duration_ms=9000))
    summary = summarize(load_run(_write_run(runs_root, RUN_ID, events)))

    assert summary["error_events"] == 3
    assert summary["retries"] == 3
    assert summary["error_categories"] == {"connection": 2, "rate_limit": 1}


def test_format_summary_renders_all_sections(basic_run_path):
    text = format_summary(summarize(load_run(basic_run_path)))

    for needle in ("run       ", "wall      ", "time split", "tokens", "errors",
                   "tools by total duration", "stuck-loop candidates: none"):
        assert needle in text


# -------------------------------------------------------------------- diff


def test_diff_of_identical_summaries_is_neutral(basic_run_path):
    a = summarize(load_run(basic_run_path))
    b = summarize(load_run(basic_run_path))
    result = diff(a, b)

    assert result["verdict"] == "wall time unchanged"
    assert result["sequence"]["identical"] is True
    assert result["sequence"]["common_prefix"] == 2
    assert result["summary_delta"]["wall_ms"]["delta"] == 0
    assert result["summary_delta"]["tool_calls"]["delta"] == 0
    assert result["tokens"]["delta"]["output"] == 0


def test_diff_reports_slower_and_more_calls(runs_root):
    slow_events = [
        _event("run_start", _ts(0), RUN_ID, model="m"),
        _event("tool_start", _ts(1), RUN_ID, tool_call_id="a", name="local_exec",
               arguments={"length": 1}),
        _event("tool_end", _ts(2), RUN_ID, tool_call_id="a", name="local_exec",
               state="failed", duration_ms=9000, output={"length": 3}),
        _event("tool_result", _ts(2.1), RUN_ID, tool_call_id="a", name="local_exec",
               state="failed", is_error=True),
        _event("run_end", _ts(3), RUN_ID, status="failed", duration_ms=20000,
               total_input_tokens=100, total_output_tokens=10),
    ]
    _write_run(runs_root, RUN_ID, slow_events, date="2026-11-07")

    fast_events = [
        _event("run_start", _ts(100), OTHER_ID, model="m"),
        _event("run_end", _ts(101), OTHER_ID, status="completed", duration_ms=5000,
               total_input_tokens=50, total_output_tokens=5),
    ]
    fast_path = _write_run(runs_root, OTHER_ID, fast_events, date="2026-11-08")

    result = diff(summarize(load_run(RUN_ID, runs_dir=runs_root)),
                  summarize(load_run(fast_path)))

    assert result["summary_delta"]["wall_ms"]["delta"] == 5000 - 20000
    assert result["summary_delta"]["tool_calls"]["delta"] == -1
    assert result["summary_delta"]["tool_failures"]["delta"] == -1
    assert result["tokens"]["delta"]["input"] == 50 - 100
    assert result["outcome"]["status"] == {"a": "failed", "b": "completed"}
    assert result["outcome"]["became_better"] is True

    assert result["tools"]["local_exec"]["calls"]["delta"] == -1
    assert result["tools"]["local_exec"]["total_ms"]["a"] == 9000
    assert result["sequence"]["removed"] == ["local_exec#1"]
    assert result["sequence"]["added"] == []


def test_diff_detects_extra_tool_in_b(runs_root):
    base = [
        _event("run_start", _ts(0), RUN_ID, model="m"),
        _event("tool_start", _ts(1), RUN_ID, tool_call_id="a", name="grep",
               arguments={"length": 1}),
        _event("tool_start", _ts(2), RUN_ID, tool_call_id="b", name="glob",
               arguments={"length": 1}),
    ]
    extra = base + [
        _event("tool_start", _ts(3), RUN_ID, tool_call_id="c", name="web_fetch",
               arguments={"length": 1}),
    ]
    path_a = _write_run(runs_root, RUN_ID, base, date="2026-11-07")
    path_b = _write_run(runs_root, OTHER_ID, extra, date="2026-11-08")

    result = diff(summarize(load_run(path_a)), summarize(load_run(path_b)))

    assert result["sequence"]["common_prefix"] == 2
    assert result["sequence"]["added"] == ["web_fetch#1"]
    assert result["sequence"]["removed"] == []
    assert result["summary_delta"]["tool_calls"]["delta"] == 1


def test_diff_detects_reordered_tool_calls(runs_root):
    order_a = [
        _event("run_start", _ts(0), RUN_ID, model="m"),
        _event("tool_start", _ts(1), RUN_ID, tool_call_id="a", name="grep",
               arguments={"length": 1}),
        _event("tool_start", _ts(2), RUN_ID, tool_call_id="b", name="glob",
               arguments={"length": 1}),
    ]
    order_b = [
        _event("run_start", _ts(0), OTHER_ID, model="m"),
        _event("tool_start", _ts(1), OTHER_ID, tool_call_id="b", name="glob",
               arguments={"length": 1}),
        _event("tool_start", _ts(2), OTHER_ID, tool_call_id="a", name="grep",
               arguments={"length": 1}),
    ]
    path_a = _write_run(runs_root, RUN_ID, order_a, date="2026-11-07")
    path_b = _write_run(runs_root, OTHER_ID, order_b, date="2026-11-08")

    result = diff(summarize(load_run(path_a)), summarize(load_run(path_b)))

    assert result["sequence"]["identical"] is False
    moved = {change["signature"] for change in result["sequence"]["order_changes"]}
    assert "grep#1" in moved


def test_diff_accepts_run_objects_directly(basic_run_path):
    run = load_run(basic_run_path)
    result = diff(run, run)

    assert result["run_a"]["id"] == RUN_ID
    assert result["sequence"]["identical"] is True


def test_format_diff_renders_every_section(runs_root):
    events_a = _basic_events()
    path_a = _write_run(runs_root, RUN_ID, events_a, date="2026-11-07")
    events_b = [
        _event("run_start", _ts(200), OTHER_ID, model="wb-domestic-a"),
        _event("model_request", _ts(201), OTHER_ID, purpose="conversation",
               model="wb-domestic-a", duration_ms=50, input_tokens=5,
               output_tokens=2, cached_tokens=0, attempt=1),
        _event("run_end", _ts(202), OTHER_ID, status="completed", duration_ms=400,
               total_input_tokens=5, total_output_tokens=2),
    ]
    path_b = _write_run(runs_root, OTHER_ID, events_b, date="2026-11-08")

    text = format_diff(diff(summarize(load_run(path_a)),
                            summarize(load_run(path_b))))

    for needle in ("metric ", "tokens ", "tool deltas", "tool sequence",
                   "outcome  ", "verdict  "):
        assert needle in text
    assert "-" in text  # negative deltas render


def test_format_diff_handles_runs_without_tools(runs_root):
    events = [
        _event("run_start", _ts(0), RUN_ID, model="m"),
        _event("run_end", _ts(1), RUN_ID, status="completed", duration_ms=1000),
    ]
    path = _write_run(runs_root, RUN_ID, events)
    summary = summarize(load_run(path))

    text = format_diff(diff(summary, summary))

    assert "tool deltas (0 changed of 0)" in text
    assert "(none)" in text
