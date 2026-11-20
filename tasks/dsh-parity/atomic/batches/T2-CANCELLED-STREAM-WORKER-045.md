# T2-CANCELLED-STREAM-WORKER-045 — abort blocked stream workers and deliver rollback

- Status: `DONE_SCOPED`; Task 2 remains `IN_PROGRESS`.
- Capability atom: `ENG-MODEL-ATTEMPT-CANCEL-DISCARD` (still `PARTIAL`).
- Dependencies: `T2-CANCELLED-ATTEMPT-043`; `T2-ACP-KERNEL-ATTEMPT-STREAM-021`.

## Files

- `core/atlas/models/router.py`
- `core/atlas/engine/kernel/model_call.py`
- `core/atlas/engine/kernel/loop.py`
- `core/atlas/agent/run_phases.py`
- `core/tests/test_app_server_sdk_subprocess_attempts.py`
- Task 2 atomic capability, interaction-edge, batch-queue ledgers, and `BEYOND-DSH-PROGRESS.md`.

## Binary acceptance

1. A real SDK `AppServer` subprocess receives OLD from a loopback provider, is cancelled, returns `status=cancelled` with empty result text, and exits naturally with code 0; a five-second forced-kill close is not accepted.
2. The SDK callback sees the same attempt's `message.rollback` after its OLD chunk and before terminal `cancelled`.
3. Reopened private `SessionDB` contains the discarded/cancelled OLD attempt audit, while canonical assistant history contains no OLD.
4. Exactly one model request is made. Normal retry, fallback, partial tool-call isolation, retry budget, stream-option compatibility and max-output continuation remain intact.

## Red evidence and root cause

- The first real SDK subprocess cancellation probe failed at shutdown: close lasted `5.016s` and the child exited 1. A temporary, private-root thread dump showed the model worker blocked in `httpcore` synchronous socket read through `httpx.Response.iter_lines()` and `model_call._stream_next`; the app-server main thread was in `asyncio.run()` shutdown. Calling `close()` on the currently executing Python generator could not close the active response.
- A response-aware stream abort removed the shutdown failure, but the SDK callback then reported `chunk` followed by terminal `cancelled`, with no `message.rollback`. Reopened DB already contained `model/attempt` statuses `started` and `discarded/cancelled`, showing that attempt audit completed while rollback delivery was lost.
- Removing the run-phase tail drain reproduced the missing rollback. The final fix therefore retains both the kernel model-queue drain and run-phase cleanup-queue drain.
- Temporary `sitecustomize` thread-dump instrumentation was removed; the final test uses only its isolated test root and pre-existing public tokenizer cache. No external fetch, live model, credential, proxy or user config was used.

## Implementation

- `ModelRouter.stream()` now returns a managed blocking iterator. Its thread-safe `abort()` closes the active HTTP response without calling `generator.close()` while another thread is executing `next()`; ordinary close still closes an idle generator. `complete_stream` prefers this optional abort handle and preserves legacy custom-router `close()` support.
- When cancellation unwinds the kernel model task, `kernel/loop.py` first settles the worker and yields any queued rollback events before propagating cancellation. `run_phases._pump_events` then drains cleanup events produced while the engine task was settling before emitting its terminal cancelled event.
- The integration test verifies SDK-visible order, exactly one provider request, final cancelled result, natural subprocess exit 0, and reopened database audit/transcript separation.

## Verification

- Final SDK cancellation node from `D:\Atlas\core`:
  `python -m pytest -q -p no:cacheprovider -o addopts= tests/test_app_server_sdk_subprocess_attempts.py::test_real_sdk_app_server_cancel_rolls_back_partial_attempt_and_persists_only_audit --tb=short`
  -> `1 passed, 5 warnings in 6.00s`, exit 0. The assertion `process.wait(timeout=0) == 0` passed after SDK close.
- Related OLD/NEW, kernel cancellation, fallback, max-output, retry-budget and app-server task cleanup nodes (explicit list):
  `python -m pytest -q -p no:cacheprovider -o addopts= tests/test_retry_attempt_isolation.py tests/test_atlas_runtime_e2e.py::test_retry_attempt_rollback_is_emitted_by_kernel_before_new_answer tests/test_atlas_runtime_e2e.py::test_kernel_cancelled_stream_rolls_back_old_attempt_before_persisting_interrupt tests/test_atlas_runtime_e2e.py::test_kernel_discards_partial_failed_tool_call_before_retry_and_persists_only_new tests/test_atlas_runtime_e2e.py::test_stream_fault_budget_disables_hidden_retry_only_when_opted_in tests/test_atlas_runtime_e2e.py::test_stream_options_compat_retry_is_budgeted_only_when_opted_in tests/test_atlas_runtime_e2e.py::test_stream_options_unrelated_bad_request_does_not_retry tests/test_atlas_runtime_e2e.py::test_real_atlas_turn_stops_when_atlas_cancel_is_set tests/test_app_server_sdk_subprocess_attempts.py::test_real_sdk_app_server_subprocess_commits_only_new_attempt_and_reopens_audit tests/test_app_server_sdk_subprocess_attempts.py::test_sdk_app_server_fallback_attempt_isolated_across_process_restart tests/test_app_server_sdk_subprocess_attempts.py::test_sdk_app_server_retry_keeps_max_output_continuation_across_restart tests/test_app_server_sdk_subprocess_attempts.py::test_app_server_task_cancel_waits_for_worker_cleanup_and_cancels_queued_item --tb=short`
  -> `15 passed, 5 warnings in 58.16s`, exit 0.
- Repeat final SDK cancellation node after restoring the run-phase drain: `1 passed, 5 warnings in 6.00s`, exit 0.
- `python -m py_compile atlas/models/router.py atlas/engine/kernel/model_call.py atlas/engine/kernel/loop.py atlas/agent/run_phases.py tests/test_app_server_sdk_subprocess_attempts.py`: exit 0.
- `git diff --check -- core/atlas/models/router.py core/atlas/engine/kernel/model_call.py core/atlas/engine/kernel/loop.py core/atlas/agent/run_phases.py core/tests/test_app_server_sdk_subprocess_attempts.py`: exit 0; only existing LF-to-CRLF notice for `model_call.py`.
- AST check found the cleanup queue-yields in the kernel stream loop and `run_phases._pump_events`; the final integration node executes both paths and asserts event order.

## Remaining obligations

This closes a local loopback FakeLLM path through AtlasKernel, Python SDK, actual app-server subprocess, and reopened SessionDB. It does not establish ACP cancellation/wait parity, the packaged Electron renderer's visible rollback, real-model behavior, broad timeout/approval/tool-error interactions, complete Task 1 semantics, or any superiority result. The pinned source ledger remains incomplete and unresolved.
