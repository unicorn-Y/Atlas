# WAVE 2 V1 Result

Rows: E2, E19, E25  
Worktree baseline: `fa578c482d08b270b6b1b7a2bc3276108a42f956`  
Verification backend: port `8831`, model `deepseek-v4.1-flash`, base URL `https://d1api.xin/v1`, proxy `http://127.0.0.1:7897`; config and runtime data were isolated under `.run-wave2`.

## E2 — turn and step lifecycle

**Live PASS.** A real WebSocket turn completed with reply `OK`. Its isolated run journal recorded `turn_start`, `step_start(step=1)`, `step_end(reason=response)`, `turn_end(reason=completed)`, and `turn_close(steps=1)`. A tool-using turn also recorded `step_end(reason=tool_calls)` and `turn_end(reason=completed)`. The terminal result exposes the typed `turn_end_reason`.

## E19 — concludeTurn

**Live PASS.** Prompted the real model to call `concludeTurn` with `TOOL_DONE`. Observed `tool.started name=concludeTurn`, `tool.completed`, then `run.completed`; reply was exactly `TOOL_DONE`. The run reported `request_count=1`, so the tool conclusion ended the user turn without a follow-up model request.

## E25 — idle maintenance slot

Added a post-kernel-turn call to `AtlasKernel.runMaintenance` in `AtlasRuntime`. The kernel's active-run count is released in the kernel generator's `finally` before the host finishes consuming that generator, so this call reaches the idle-only slot after the turn closes. It invokes a runtime-context `maintenance_callback` when supplied and uses an empty callback when none is configured. Successful invocation emits `atlas_runtime.idle_maintenance_completed`.

**Live PASS for the slot invocation.** A further real turn completed with `MAINT_OK`; the backend log emitted `atlas_runtime.idle_maintenance_completed`. No business-specific maintenance callback was configured in this isolated live run, so this proves the production idle slot is reached, not a particular maintenance job's effects.

## Checks

- `python -m pytest -q -p no:cacheprovider tests/test_kernel_lifecycle_reasons.py` — **9 passed**, 5 existing deprecation warnings.
- `git diff --check` — passed.
- Live backend start and WebSocket runs used the requested model, base URL, proxy, and port.

