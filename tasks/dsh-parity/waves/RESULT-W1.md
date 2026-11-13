# W1 — Kernel lifecycle

## Rows

- **E2 — PARTIAL.** `TurnLifecycle` now enforces turn/step ordering and typed terminal reasons. The loop records `turn_start`, `step_start`, `step_end`, `turn_end`, and `turn_close` to the run journal. Unit coverage passes. The required real model run did not complete, so this row is not CLOSED.
- **E19 — PARTIAL.** The kernel offers `concludeTurn(response)` and ends the current loop after the tool batch, persisting and returning the supplied final response. Unit coverage verifies the typed conclusion state, but there is no successful end-to-end model evidence because model routing failed before a turn could reach the tool.
- **E25 — PARTIAL.** `AtlasKernel.runMaintenance(callback)` runs only with zero active turns; an active maintenance callback blocks new turns, and concurrent maintenance requests are rejected. Unit coverage passes. The production runtime creates a kernel per run and has no maintenance scheduling call site, so the idle slot is not yet wired into a persistent production lifecycle.

## Changed files

- `core/atlas/engine/kernel/loop.py`
- `core/atlas/engine/kernel/state.py`
- `core/tests/test_kernel_lifecycle_reasons.py`
- `docs/parity/DSH-GAP-LEDGER.md` (E2, E19, E25 only)

## Tests and static checks

Command, run from `core`:

```text
python -m pytest -q -p no:cacheprovider tests/test_kernel_lifecycle_reasons.py tests/test_kernel_tool_timeout.py tests/test_tool_scheduler_concurrency.py
```

Actual output:

```text
32 passed, 5 warnings in 3.28s
```

The five warnings are existing FastAPI/Pydantic deprecations during test collection. Also ran `python -m py_compile atlas/engine/kernel/loop.py atlas/engine/kernel/state.py`; it passed. `git diff --check` was clean after removing the trailing blank line.

The lifecycle test was first run before implementing `TurnLifecycle.end_turn`; it failed as expected with `AttributeError: 'TurnLifecycle' object has no attribute 'end_turn'`. After implementation, the focused suite above passed.

## Real model validation on port 8821

**Not passed.** The standard live check reached the real backend but failed before any model response:

```text
[terminal] run.failed data={"category": "runtime", "detail": "TypeError: int() argument must be a string, a bytes-like object or a real number, not 'NoneType' ..."}
[reply] ''
[result] terminal=run.failed chars=0
```

The worktree's active config selects `claude-sonnet-4`; a retry reached `https://api.anthropic.com/v1/messages` and returned `401 invalid x-api-key`. Explicitly selecting the plan's `deepseek-v4.1-flash` on the same backend returned `Model selection failed: Unknown model: deepseek-v4.1-flash`. The worktree config does not register the specified DeepSeek route, so there is no valid successful run to report. No credentials were printed or changed.

## Commit status

Committed to the current branch `zcode/dsh-w1`; see the commit reported with this result. Rows remain PARTIAL until their missing runtime evidence and E25 production call site are supplied.
