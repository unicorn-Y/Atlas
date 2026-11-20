# T3-CROSS-PROCESS-CANCEL-START-108

## Scope

Dependencies: the transactionally persisted worker claim from T3-107 and T3-106's separate-process SQLite barrier harness.

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

Two child processes first restored the same queued item into stale local snapshots. The test then released one operation to completion before releasing the other, covering both orderings. Before the fix, `start` followed by stale-snapshot `cancel` produced `start=True, cancel=True`, writing both lifecycle markers.

Added `SessionDB.cancel_inbox_if_unstarted()` inside the same `BEGIN IMMEDIATE` serialization used by worker claim. Cancellation now checks the persisted enqueue/start/terminal events and appends `inbox.cancelled` only if no worker owns the event. A stale loser refreshes its local pending snapshot. Start and cancel therefore share one durable boundary across processes.

## Verification

Red reproduction:

```text
python -m pytest -q -p no:cacheprovider tests/test_durable_enqueue_retry.py::test_separate_process_cancel_and_start_share_one_lifecycle_boundary
1 failed, 1 passed, 5 warnings in 4.73s
exit code: 1
The [start] ordering returned {'start': True, 'cancel': True}.
```

Green cross-process orderings:

```text
python -m pytest -q -p no:cacheprovider tests/test_durable_enqueue_retry.py::test_separate_process_cancel_and_start_share_one_lifecycle_boundary
2 passed, 5 warnings in 4.15s
exit code: 0
```

Related inbox/app-server regressions:

```text
python -m pytest -q -p no:cacheprovider tests/test_durable_enqueue_retry.py tests/test_kernel_durable_inbox.py tests/test_app_server_sdk_subprocess_attempts.py::test_app_server_task_cancel_waits_for_worker_cleanup_and_cancels_queued_item tests/test_app_server_sdk_subprocess_attempts.py::test_app_server_worker_does_not_replay_started_head_item
13 passed, 5 warnings in 14.10s
exit code: 0

python -m py_compile atlas/engine/state/atlas_state_portability.py atlas/engine/session_sync.py atlas/engine/kernel/inbox.py tests/test_durable_enqueue_retry.py
exit code: 0

git diff --check -- atlas/engine/state/atlas_state_portability.py atlas/engine/session_sync.py atlas/engine/kernel/inbox.py tests/test_durable_enqueue_retry.py
exit code: 0
```

Both child processes naturally exited with code 0 in both orderings. Each ordering left exactly one `inbox.started` or one `inbox.cancelled` marker, never both.

## Boundary

The race proof uses direct `DurableInbox` children rather than complete app-server processes. It does not establish a full two-server FIFO execution, provider-side cancellation, approval/input recovery after restart, full subscription behavior, real-provider evidence, packaged desktop behavior, or Task 3 completion.
