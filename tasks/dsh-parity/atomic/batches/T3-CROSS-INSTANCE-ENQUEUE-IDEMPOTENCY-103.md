# T3-CROSS-INSTANCE-ENQUEUE-IDEMPOTENCY-103

## Scope

This batch closes the durable enqueue idempotency race across independent `DurableInbox` instances sharing a real temporary SessionDB file.

Changed files:

- `core/atlas/engine/state/atlas_state_portability.py`
- `core/atlas/engine/session_sync.py`
- `core/atlas/engine/kernel/inbox.py`
- `core/tests/test_durable_enqueue_retry.py`
- `core/tests/test_app_server_sdk_subprocess_attempts.py` (fault injection now targets the enqueue transaction wrapper)
- `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`
- `tasks/dsh-parity/atomic/atomic-capabilities.jsonl`
- `tasks/dsh-parity/atomic/interaction-edges.jsonl`
- `tasks/dsh-parity/atomic/batch-queue.jsonl`
- this report

Dependencies: SessionDB's existing `BEGIN IMMEDIATE` write transaction, T2 stable request identity, and DurableInbox's existing payload normalization/receipt contract.

## Reproducer and change

Before the fix, two independent inbox instances both restored an empty receipt map and concurrently appended different `inbox.enqueued` event IDs for the same request id. With conflicting content, both succeeded instead of one receiving a clear conflict.

Added a SessionDB operation that checks an existing request receipt and appends the new event in one write transaction. A duplicate with identical lane/content returns the original event id; a conflict raises `ValueError`. A duplicate found by a stale local inbox invalidates and reloads that inbox's queue snapshot after releasing its local lock, so the duplicate caller sees the durable pending item rather than only receiving an id.

The event append failure subprocess test was updated to inject the failure at the new `append_inbox_enqueue_with_receipt` seam. Its original no-receipt/no-provider-before-persistence assertions remain unchanged.

## Verification

Red reproduction before the production change:

```text
python -m pytest -q -p no:cacheprovider tests/test_durable_enqueue_retry.py
2 failed, 5 warnings in 3.36s
exit code: 1
```

The two failures showed two different event IDs for the same request, and two successful writes for conflicting content.

Green real SQLite inbox tests:

```text
python -m pytest -q -p no:cacheprovider tests/test_durable_enqueue_retry.py tests/test_kernel_durable_inbox.py
6 passed, 5 warnings in 3.87s
exit code: 0
```

App-server receipt/worker integration:

```text
python -m pytest -q -p no:cacheprovider tests/test_durable_enqueue_retry.py tests/test_kernel_durable_inbox.py tests/test_app_server_sdk_subprocess_attempts.py::test_sdk_durable_enqueue_receipt_is_idempotent_across_app_server_restart tests/test_app_server_sdk_subprocess_attempts.py::test_sdk_enqueue_starts_worker_without_sync_prompt_and_waits_for_commit tests/test_app_server_sdk_subprocess_attempts.py::test_app_server_worker_does_not_replay_started_head_item
9 passed, 5 warnings in 12.72s
exit code: 0
```

Durable append-failure recovery:

```text
python -m pytest -q -p no:cacheprovider tests/test_app_server_sdk_subprocess_attempts.py::test_app_server_event_append_failure_returns_no_receipt_then_retries_once
2 passed, 5 warnings in 8.85s
exit code: 0
```

Syntax check:

```text
python -m py_compile tests/test_app_server_sdk_subprocess_attempts.py atlas/engine/state/atlas_state_portability.py atlas/engine/session_sync.py atlas/engine/kernel/inbox.py
PY_COMPILE_EXIT_CODE=0
```

The concurrency reproducer uses two independent inboxes and SessionDB connections to one temporary SQLite file, not two subprocesses. The CLI subprocess tests use the actual local app-server/SDK and FakeLLMServer. Separate-process simultaneous writers, multiple active workers on one session, live model, full approval/input matrix and packaged desktop remain open.

Scoped result: `DONE_SCOPED`; Task 3 and global parity/superiority remain `INCOMPLETE`.
