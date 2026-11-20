# T3-CROSS-PROCESS-WORKER-CLAIM-107

## Scope

Dependencies: T3-103 durable enqueue receipt transaction and T3-106 separate-process enqueue race harness.

Files changed:

- `core/atlas/engine/state/atlas_state_portability.py`
- `core/atlas/engine/session_sync.py`
- `core/atlas/engine/kernel/inbox.py`
- `core/tests/test_durable_enqueue_retry.py`
- `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`
- `tasks/dsh-parity/atomic/atomic-capabilities.jsonl`
- `tasks/dsh-parity/atomic/interaction-edges.jsonl`
- `tasks/dsh-parity/atomic/batch-queue.jsonl`
- this report

## Reproducer and change

Two Python worker processes independently restored the same pending enqueue before a synchronized barrier. Both then called `DurableInbox.mark_started` with different run IDs. The red test observed `[True, True]` and two durable starts, so both processes could believe they owned the item.

Added a `SessionDB` transaction that reads the enqueue/start/consume/cancel lifecycle and appends `inbox.started` only when no worker has claimed the still-pending event. Existing same-run identity remains idempotent; a competing run receives the stored owner identity and returns false. `DurableInbox.mark_started` updates its local snapshot to that durable owner, or refreshes after a consumed/cancelled event.

## Verification

Red cross-process reproduction before the transaction:

```text
python -m pytest -q -p no:cacheprovider tests/test_durable_enqueue_retry.py::test_separate_process_workers_atomically_claim_one_pending_item
1 failed, 5 warnings in 3.99s
exit code: 1
assert [True, True] == [False, True]
```

Green after the transaction:

```text
python -m pytest -q -p no:cacheprovider tests/test_durable_enqueue_retry.py::test_separate_process_workers_atomically_claim_one_pending_item
1 passed, 5 warnings in 3.18s
exit code: 0

python -m pytest -q -p no:cacheprovider tests/test_durable_enqueue_retry.py tests/test_kernel_durable_inbox.py tests/test_app_server_sdk_subprocess_attempts.py::test_app_server_worker_does_not_replay_started_head_item
10 passed, 5 warnings in 8.67s
exit code: 0

python -m py_compile atlas/engine/state/atlas_state_portability.py atlas/engine/session_sync.py atlas/engine/kernel/inbox.py tests/test_durable_enqueue_retry.py
exit code: 0

git diff --check -- atlas/engine/state/atlas_state_portability.py atlas/engine/session_sync.py atlas/engine/kernel/inbox.py tests/test_durable_enqueue_retry.py
exit code: 0
```

## Boundary

The competing claim was exercised by two real Python processes and independent SQLite connections, not by two complete app-server processes. Cancel-versus-start contention is not covered by this claim atom; neither are multiple active app-server workers, cross-process FIFO execution, live provider behavior, pending approval/input restart recovery, full subscriptions, or Task 3 completion.
