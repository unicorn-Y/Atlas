# T2-CANCELLED-ATTEMPT-043 — discard partial attempts on cancellation

- Status: DONE_SCOPED; Task 2 remains IN_PROGRESS.
- Capability atom: `ENG-MODEL-ATTEMPT-CANCEL-DISCARD`.
- Dependencies: `T2-ATTEMPT-LIFECYCLE-001`; `T2-ATTEMPT-ROLLBACK-002`.

## Files

- Modify `core/atlas/engine/kernel/model_call.py`.
- Modify `core/tests/test_retry_attempt_isolation.py`.
- Modify `core/tests/test_atlas_runtime_e2e.py`.
- Modify Task 2 atomic capability, interaction-edge and batch-queue ledgers.
- Modify `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`.

## Binary acceptance

1. If a stream is cancelled after emitting OLD, `complete_stream` emits matching `attempt_discarded(category=cancelled, retry=false)` with its partial text before propagating cancellation.
2. The real AtlasKernel event path emits matching `message.rollback`, persists a discarded attempt audit, and keeps OLD out of canonical assistant history.
3. Cancellation before the first token does not turn the stream-close transport error into an unknown provider fault or schedule another request.
4. Existing OLD→NEW retry, partial failed tool argument isolation, retry-budget accounting, recognized stream-options compatibility and normal max-output continuation remain unchanged.

## Red evidence

- Before production change, from `D:\Atlas\core`:
  `python -m pytest -q -p no:cacheprovider tests/test_retry_attempt_isolation.py::test_cancelled_stream_discards_partial_attempt_before_propagating --tb=short`
  returned `1 failed, 5 warnings in 5.42s`, exit 1. The lifecycle contained only `attempt_started`; no discard event was emitted.
- The new kernel scenario failed before production change because no `message.rollback` appeared after OLD had been delivered.
- The existing pre-token Hang test was updated to construct the required real `AgentOrchestrator`/`AgentRunContext` path. Before the cancellation classification fix, its actual rollback category was `unknown`: closing the in-flight stream surfaced a transport exception before the explicit cancellation branch.

## Implementation and final verification

- Both direct `CancelledError` and an exception raised while the caller's cancel event is already set now finish the request as cancelled, release its reserved usage, and publish a non-retryable discarded attempt containing only that attempt's partial text for audit. The kernel's existing consumer persists the audit and emits the matching rollback.
- Final targeted command from `D:\Atlas\core`, with pytest addopts explicitly cleared so the listed nodes are collected:

  ```text
  python -m pytest -q -p no:cacheprovider -o addopts= tests/test_retry_attempt_isolation.py tests/test_atlas_runtime_e2e.py::test_retry_attempt_rollback_is_emitted_by_kernel_before_new_answer tests/test_atlas_runtime_e2e.py::test_kernel_cancelled_stream_rolls_back_old_attempt_before_persisting_interrupt tests/test_atlas_runtime_e2e.py::test_real_atlas_turn_stops_when_atlas_cancel_is_set tests/test_atlas_runtime_e2e.py::test_kernel_discards_partial_failed_tool_call_before_retry_and_persists_only_new tests/test_atlas_runtime_e2e.py::test_stream_fault_budget_disables_hidden_retry_only_when_opted_in tests/test_atlas_runtime_e2e.py::test_stream_options_compat_retry_is_budgeted_only_when_opted_in tests/test_atlas_runtime_e2e.py::test_stream_options_unrelated_bad_request_does_not_retry tests/test_event_contract.py --tb=short
  ```

  Actual output: `24 passed, 5 warnings in 37.37s`, exit 0. The kernel cancellation test observed OLD in a streamed chunk, then the matching rollback; reopened private SessionDB had no OLD assistant content and retained a `model/attempt` discarded/cancelled audit row.
- `python -m py_compile atlas/engine/kernel/model_call.py tests/test_retry_attempt_isolation.py tests/test_atlas_runtime_e2e.py`: exit 0.
- AST check of `complete_stream` found discard publication in both its `CancelledError` and cancel-event-set `BaseException` paths; result `both_paths_discard=True`.
- `git diff --check -- atlas/engine/kernel/model_call.py tests/test_retry_attempt_isolation.py tests/test_atlas_runtime_e2e.py`: exit 0; Git emitted only its LF→CRLF working-copy notice.

## Remaining obligations

This is a scoped kernel cancellation closure using loopback FakeLLM. It does not close cancellation/wait/approval across app-server, Python SDK, ACP, Electron/packaged desktop, real model, or the remaining retry/error interactions. Task 1 still has 413,732 unresolved source obligations. No overall parity or superiority claim is made.
