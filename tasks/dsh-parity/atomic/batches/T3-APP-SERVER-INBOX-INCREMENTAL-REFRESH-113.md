# T3-APP-SERVER-INBOX-INCREMENTAL-REFRESH-113

## Scope

Dependencies: T3-112's two-process FIFO reproducer, T3-107 atomic cross-process start ownership, and T3-108 cancellation serialization.

Files changed:

- `core/atlas/engine/kernel/inbox.py`
- `core/atlas/engine/session_sync.py`
- `core/atlas/engine/state/atlas_state_portability.py`
- `core/tests/test_durable_enqueue_retry.py`
- this report
- `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`
- `tasks/dsh-parity/atomic/atomic-capabilities.jsonl`
- `tasks/dsh-parity/atomic/interaction-edges.jsonl`
- `tasks/dsh-parity/atomic/batch-queue.jsonl`

## Root cause and correction

Each app-server worker had a `DurableInbox` snapshot that stopped refreshing after initial restore. When process B saw the first item already durably started by process A, it left the second request queued and ended its local worker. Process A acknowledged the head but never saw the externally appended second item, so no worker drained it.

`SessionDB.list_inbox_events()` now returns only inbox lifecycle events after a sequence cursor and a transaction-consistent high-water cursor. `session_sync.read_session_inbox_events()` exposes this path without invoking the generic turn-repair scan. `DurableInbox.restore()` retains its local queue/receipt state and incrementally applies new enqueue/start/consume/cancel markers; event-ID application is idempotent, so an event locally appended after the previous cursor can safely be replayed once. Paging remains bounded at 1,000 inbox events.

## Verification

The direct refresh test proves one inbox instance sees a second instance's enqueue after acknowledging its own head. The page test inserts non-inbox history around inbox markers, confirms returned event types are only inbox lifecycle events, and confirms the cursor advances through unrelated history. The dual-app-server integration proves first-before-second provider order, no second start while the first is held, a complete lifecycle for both requests, one provider request per request, and both processes exit naturally with code 0.

```text
python -m pytest -q -p no:cacheprovider tests/test_durable_enqueue_retry.py::test_inbox_refresh_after_ack_observes_another_process_enqueue tests/test_durable_enqueue_retry.py::test_inbox_event_page_filters_history_and_advances_cursor_across_other_events tests/test_app_server_sdk_subprocess_attempts.py::test_two_app_server_processes_drain_distinct_same_session_requests_in_fifo_order
3 passed, 5 warnings in 9.16s
exit code: 0

python -m pytest -q -p no:cacheprovider tests/test_durable_enqueue_retry.py tests/test_app_server_sdk_subprocess_attempts.py
37 passed, 5 warnings in 189.30s
exit code: 0

python -m py_compile atlas/engine/kernel/inbox.py atlas/engine/session_sync.py atlas/engine/state/atlas_state_portability.py atlas/engine/state/atlas_state_repair.py atlas/tools/app_server.py tests/test_durable_enqueue_retry.py tests/test_atlas_state_repair_preflight.py tests/test_app_server_sdk_subprocess_attempts.py
exit code: 0

git diff --check -- core/atlas/engine/kernel/inbox.py core/atlas/engine/session_sync.py core/atlas/engine/state/atlas_state_portability.py core/atlas/engine/state/atlas_state_repair.py core/atlas/tools/app_server.py
exit code: 0
```

The atomic JSONL files parse as JSON; historical duplicate IDs exist in unrelated legacy rows, while these appended IDs are unique. No existing legacy rows were rewritten.

After simplifying the refresh loop's redundant empty-page condition, the three direct refresh/cursor/FIFO nodes were rerun:

```text
3 passed, 5 warnings in 9.08s
exit code: 0
```

## Limits

This is local fake-provider evidence for cross-process next-turn queueing only. Approval/input recovery, restart retry-budget behavior, cross-process wait/subscription delivery, live model, full desktop, Task 3 completion, the full Task 1 inventory, and all superiority comparisons remain open.
