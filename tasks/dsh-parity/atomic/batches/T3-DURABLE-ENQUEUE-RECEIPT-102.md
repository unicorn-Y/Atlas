# T3-DURABLE-ENQUEUE-RECEIPT-102 — cancellation outcome classification

## Scope

This batch closes one recovery-classification slice in Task 3. The SDK durable enqueue receipt, inbox request-id deduplication, started-item quarantine, retry-event history and restart cursor behavior already existed in this working tree; this batch verified those contracts and fixed a separate cancellation ambiguity exposed by the recovery test. It does not close Task 3.

Changed files:

- `core/atlas/engine/session_sync.py`
- `core/tests/test_retry_recovery_state.py`
- `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`
- `tasks/dsh-parity/atomic/atomic-capabilities.jsonl`
- `tasks/dsh-parity/atomic/interaction-edges.jsonl`
- `tasks/dsh-parity/atomic/batch-queue.jsonl`
- this report

No app-server, SDK, or inbox production code changed in this batch. Inspection showed the existing inbox receipt path already persists before receipt, rejects conflicting request-id reuse, restores receipts after restart, and quarantines a started inbox item rather than replaying it.

## Reproducer and fix

The recovery test cancels a live provider request after it has started. Kernel attempt audit correctly persists `started` followed by `discarded` with `category=cancelled`. Before the fix, `classify_retry_recovery()` treated every non-retry `discarded` event as `settled`; this incorrectly turned local cancellation into evidence that the provider outcome was known.

The classifier now maps a discarded attempt with `category=cancelled` or `retry_denied_reason=cancelled` to `outcome_unknown`, records `outcome_reason=cancelled_locally`, and preserves the attempt identity and prior retry-budget fields. It does not schedule another request.

## Verification

Red reproduction before the production change:

```text
python -m pytest -q -p no:cacheprovider tests/test_retry_recovery_state.py::test_reopened_session_classifies_started_retry_as_unknown_without_replaying
1 failed, 5 warnings in 12.04s
AssertionError: 'settled' == 'outcome_unknown'
exit code: 1
```

Focused green after the fix:

```text
python -m pytest -q -p no:cacheprovider tests/test_retry_recovery_state.py::test_reopened_session_classifies_started_retry_as_unknown_without_replaying
1 passed, 5 warnings in 12.13s
exit code: 0
```

Inbox/retry/restart group, with actual collection:

```text
python -m pytest -q -p no:cacheprovider tests/test_kernel_durable_inbox.py tests/test_retry_recovery_state.py tests/test_retry_decision_persistence.py tests/test_app_server_sdk_subprocess_attempts.py::test_app_server_worker_does_not_replay_started_head_item tests/test_app_server_sdk_subprocess_attempts.py::test_sdk_replays_durable_session_events_by_cursor_after_cli_restart tests/test_app_server_sdk_subprocess_attempts.py::test_sdk_durable_enqueue_receipt_is_idempotent_across_app_server_restart
13 passed, 5 warnings in 38.06s
exit code: 0
```

Syntax check:

```text
python -m py_compile atlas/engine/session_sync.py tests/test_retry_recovery_state.py
PY_COMPILE_EXIT_CODE=0
```

Existing enqueue/subscription lifecycle coverage was also checked while selecting the next slice:

```text
python -m pytest -q -p no:cacheprovider tests/test_app_server_sdk_subprocess_attempts.py::test_sdk_enqueue_starts_worker_without_sync_prompt_and_waits_for_commit tests/test_app_server_sdk_subprocess_attempts.py::test_app_server_pending_request_reconnects_in_same_process tests/test_app_server_sdk_subprocess_attempts.py::test_app_server_invalidates_old_pending_request_after_process_restart tests/test_app_server_sdk_subprocess_attempts.py::test_app_server_task_cancel_waits_for_worker_cleanup_and_cancels_queued_item
6 passed, 5 warnings in 25.71s
exit code: 0
```

The pytest environment uses the repository's local FakeLLMServer and isolated temporary SessionDB roots. No live provider/model, desktop UI, or full Task 3 approval/input reconnection matrix was run here.

## Remaining Task 3 obligations

- Pending approval/input reconnect, invalidation, and enqueue-only subscription through a separately restarted app-server remain open.
- Cross-process concurrent deduplication and all failure points around durable append/receipt delivery remain open unless covered by later batches.
- Retry wait/resume/cancel/terminal recovery and budget consumption after worker restart remain open.
- Real-model and visible packaged desktop evidence remain open.

Scoped result: `DONE_SCOPED`; Task 3 and global parity/superiority remain `INCOMPLETE`.
