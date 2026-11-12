# P4 — In-place compaction and phase awareness

## Changes

- core/atlas/kernel/context.py:145–183 adds compact_in_place, replacing older messages with a work-state summary while retaining recent turns; it rejects a result that still exceeds budget.
- core/atlas/kernel/context.py:186–195 adds one-time phase-boundary evaluation by boundary ID.
- core/atlas/agent/tool_catalog.py:361–372 exposes compact_context with its distinction from new_context_window.
- core/tests/test_context_compact_in_place.py:10–47 covers 40-turn compaction, summary fields, recent-turn retention, one-time phase evaluation, and tool schema visibility.

## Why

Preserve the active context window and task while summarizing older history, and evaluate compaction only at planning/subtask boundaries when token budget is reached.

## Verification

    $env:PYTHONPATH='D:\Atlas\core'; & 'D:\Atlas\core\.venv\Scripts\python.exe' -m pytest core/tests/test_context_compact_in_place.py --basetemp=core/.pytest-basetemp-compact-audit -q
    2 passed, 6 warnings in 3.07s

## W2 dispatch completion

- `core/atlas/kernel/loop.py:982–994` defines `compact_context_callback` beside `new_context_window_callback`. It computes the current context budget, counts tokens before compaction, calls the existing `ContextManager.compact_in_place(..., keep_recent_turns=2)`, and replaces the shared `messages` list with slice assignment.
- `core/atlas/kernel/loop.py:2814–2827` dispatches `compact_context`, reports unavailable callbacks and compaction errors, emits `context.compacted.in_place`, and returns the same `data`/`outcome` result shape used by `new_context_window`.
- `core/tests/test_context_compact_in_place.py` now exercises the real `_dispatch` path with a mocked runtime callback and a 40-turn history containing tool calls and results. It verifies ≥50% token reduction, shared-list identity, the newest two turns verbatim, goal/open-items in the summary, and the emitted event.

## Verification

Command (pytest `--basetemp` was outside the repository):

    cd /d/Atlas && PYTHONPATH=D:/Atlas/core core/.venv/Scripts/python.exe -m pytest core/tests/test_context_compact_in_place.py -q --basetemp=C:/Users/25011/AppData/Local/Temp/atlas-w2-p4-20261108-r2

    3 passed, 6 warnings in 3.77s

Dispatch search output:

    loop.py:982: async def compact_context_callback() -> dict[str, Any]:
    loop.py:994: proxy_runtime.compact_in_place_callback = compact_context_callback
    loop.py:2814: if name == "compact_context":

The warnings are pre-existing Pydantic/FastAPI deprecations and pytest cache-path warnings. The compaction acceptance test passed.

## W2 phase-boundary wiring (taskbook item 3)

The taskbook requires the boundary check to run once when a plan phase completes, not only to exist as a helper. The helper was previously unreachable from production code, so this is now wired:

- `core/atlas/kernel/loop.py` installs `phase_boundary_callback` next to `compact_in_place_callback`. It reads the live `messages` list and `context_manager`, calls `should_compact_at_phase_boundary(boundary_id, token_count=..., budget_tokens=context_manager.budget(...))`, and only then invokes `compact_context_callback()`. A boundary that is already evaluated or under budget returns `None` and compacts nothing.
- When compaction does run at a boundary it emits `context.compacted.phase_boundary` with the same `data` shape plus a `boundary` field.
- `ExitPlanMode` invokes the callback after approval with a monotonic id (`plan:1`, `plan:2`, ...), which is the plan-phase completion boundary the taskbook names. `subtask_close` lives outside `loop.py`, so no subtask call site was added.
- `new_context_window` behavior is unchanged.

Verification after wiring:

    cd /d/Atlas && PYTHONPATH=D:/Atlas/core core/.venv/Scripts/python.exe -m pytest core/tests/test_context_compact_in_place.py -v -p no:cacheprovider

    4 passed, 5 warnings in 3.44s

The added test `test_exit_plan_mode_triggers_phase_boundary_evaluation_once` dispatches `ExitPlanMode` twice through the real `_dispatch` and asserts the callback receives `plan:1` then `plan:2`, that plan mode turns off, and that `plan_mode_changed` is still emitted once per call.

`python -m py_compile core/atlas/kernel/loop.py` exits clean.

`git diff --stat core/atlas/kernel/loop.py` reports **48 insertions, 0 deletions** across three hunks (callback install, `ExitPlanMode` trigger, `compact_context` dispatch), so no existing behavior was rewritten or removed. A final re-run on 2026-11-08 gave `4 passed, 6 warnings in 3.23s` with `--basetemp` outside the repository.
