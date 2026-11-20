# T3-APPSERVER-WORKER-TERMINAL-STATE-029

Status: IN_PROGRESS

## Scope and dependencies

Dependencies: T3-026 durable enqueue worker and T3-028 pending request identity/invalidation.

Files in this atomic batch:

- `core/atlas/tools/app_server.py`
- `core/atlas/engine/kernel/inbox.py`
- `sdk/python/atlas_sdk/app_server.py`
- `sdk/python/atlas_sdk/__init__.py`
- `core/tests/test_app_server_sdk_subprocess_attempts.py`
- `core/tests/test_kernel_durable_inbox.py`
- `sdk/python/tests/test_app_server.py`
- this batch record, `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`, and the atomic queue/capability/interaction-edge ledgers

## Binary acceptance

1. The stable enqueue `request_id` is preserved through `DurableInbox` restore, start, terminal and cancel events. The public SDK can query task state without issuing a prompt.
2. A not-yet-started queued item can be atomically cancelled and will not execute. A started item records `cancelling`, and a cancel waiter receives `cancelled` only after worker cleanup and durable terminal state. A settled task returns `too_late` and remains unchanged.
3. Disconnecting a `wait` consumer does not cancel work. Reopening a conversation with a `started` task and no terminal record reports `outcome_unknown/recovery-required` and never calls the provider again.
4. Red tests first demonstrate absent request-scoped task state/cancel. Focused tests, app-server/inbox/retry integration, SDK tests, syntax/diff/AST checks, and atomic JSONL validation pass. Test-owned CLI process behavior is recorded separately from live model or desktop proof.

## Implementation and evidence

### Implementation

- `DurableInbox` now carries the stable app-server `request_id` through the in-memory receipt, `inbox.enqueued`, `inbox.started`, `inbox.consumed`, and `inbox.cancelled` events. Queued cancellation appends a durable cancellation event while holding the inbox lock and refuses an item after the start boundary.
- The CLI app-server shares one restored inbox per session between enqueue, worker, status, and cancel paths. It persists `queued`, `running`, `cancelling`, and terminal task events in SessionDB. A process-reopened started task with no terminal event is `outcome_unknown`; no provider replay is scheduled. Completed cancellation returns `too_late`.
- The Python SDK exposes typed `task_status` and `cancel_task`. The worker reports cancellation only after the worker settles and the terminal event is written. A cancellation waiter has a 30-second bound and reports `cancelling` if cleanup has not finished; it does not claim the worker is cancelled early.

### Red/green and commands

- Red: `core/tests/test_kernel_durable_inbox.py::test_inbox_restores_request_identity_and_cancels_only_unstarted_items` → `1 failed, 5 warnings, 4.39s`, exit 1; `InboxItem` did not preserve `request_id`.
- Red: SDK task state/cancel node → `1 failed, 1 warning, 0.66s`, exit 1; typed `AppServerTaskStatus` was not exported.
- Red: first real enqueue integration attempt reported `outcome_unknown` because the newly constructed in-memory inbox item omitted its request ID. Constructor was fixed; this was not treated as final evidence.
- A combined run initially found the pre-existing cursor test assumed the first two SessionDB rows were always `inbox.enqueued` and `inbox.started`; the new durable `appserver.task=queued` event legitimately sits between them. The test now resumes from the first-page cursor after reopening the CLI and asserts `inbox.started`, model attempt, and consumed on the continuation page. The queued event and state history remain durable.
- Final core command from `D:\Atlas\core`: `python -m pytest -q -p no:cacheprovider -o addopts= tests/test_app_server_sdk_subprocess_attempts.py tests/test_kernel_durable_inbox.py tests/test_retry_decision_persistence.py tests/test_retry_recovery_state.py tests/test_retry_attempt_isolation.py --tb=short` → `23 passed, 5 warnings in 97.08s`, exit 0.
- Final SDK command from `D:\Atlas\sdk\python`: `python -m pytest -q -p no:cacheprovider -o addopts= tests/test_app_server.py --tb=short` → `7 passed, 1 warning in 0.04s`, exit 0. The warning is SDK pytest's unregistered `unit` marker; all seven tests were collected and executed.
- Focused cursor/task-cancel/pending-reconnect subprocess nodes → `4 passed, 5 warnings in 24.93s`, exit 0. The CLI restart/cursor test naturally exited both app-server processes; the restart test intentionally terminates only its first test-owned process and confirms the reopened process does not replay the provider call.

### Scope boundary

`DONE_SCOPED`: request-scoped status and cancellation are wired through the CLI app-server and Python SDK, with durable event history and no replay for started unknown outcomes. This is not a live model, Electron UI, ACP permission recovery, external SDK, or packaged desktop result. Task 3 and the full parity plan remain open; multi-session FIFO/interleaving and other runtime consumers still need production-path coverage.
