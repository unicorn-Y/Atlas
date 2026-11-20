# T3-APPSERVER-DURABLE-ENQUEUE-WORKER-026

- Status: DONE_SCOPED.
- Capability atom: an accepted durable `session/enqueue` starts an app-server-owned worker that runs the persisted next-turn item without requiring a synchronous `session/prompt` request.
- Files: `core/atlas/tools/app_server.py`; `core/atlas/engine/kernel/inbox.py`; `core/tests/test_app_server_sdk_subprocess_attempts.py`; `core/tests/test_kernel_durable_inbox.py`; `sdk/python/atlas_sdk/app_server.py`; `sdk/python/tests/test_app_server.py`; atomic queue/capability/edge/progress records.
- Dependencies: T3-015 durable enqueue receipt and request-id idempotency; T3-024 persisted attempt start/recovery classifier; T3-025 app-server/SDK recovery query. The worker must preserve the existing Kernel inbox source role and must not re-inject the same item as a second model message.
- Acceptance (binary): an actual repository CLI app-server subprocess receives only `session/enqueue`, with no `session/prompt`; its FakeLLM observes the queued user content once, the public SDK `wait` returns only after the run settles, the matching inbox item is durably consumed only after successful completion, a duplicate enqueue with the same request id produces no second provider request, and the child app-server exits naturally with code 0. Inbox start ownership is persisted before execution; the same inbox instance is passed through the existing AgentOrchestrator/Kernel seam and suppresses only that current event ID from the next-turn projection. A pending item already marked started is fail-closed and must not be auto-replayed by a later worker wake.
- Explicit boundary: this batch proves an independent same-process worker and a no-duplicate guard for started items. It does not resume interrupted work; recovery/status resolution for started items, request-scoped stream cursors, cancellation, and approval/input reattachment require separate batches and remain open.

## Implementation

- `session/enqueue` now uses a stable receipt API that reports whether this call created a new item; only a new receipt wakes the per-session worker. Duplicate receipts do not wake old/consumed work.
- `DurableInbox` persists `inbox.started` with worker run ID before executing, restores started ownership, and provides a current-turn event marker. The same inbox instance is passed through the existing `AgentOrchestrator.run` → `RunRequest` → `AgentRunContext` → Kernel path; `peek("next-turn")` suppresses only that marked item because its payload is already the current user prompt. The worker appends `inbox.consumed` only after committed completion. A previously started FIFO head item emits a recovery-required notification and remains unconsumed; it blocks later items instead of being replayed or bypassed.
- Added public Python SDK `AppServer.wait(session_id)` using the existing app-server `session/wait` barrier. Worker owns active-task and session-idle cleanup until its queue drains.

## Evidence

- Red: actual CLI subprocess node `test_sdk_enqueue_starts_worker_without_sync_prompt_and_waits_for_commit` → `1 failed, 5 warnings in 4.58s`, exit 1; `session/wait` returned with zero FakeLLM requests because enqueue had no worker.
- Red after first worker wiring: combined worker + inbox nodes → `1 failed, 1 passed, 5 warnings in 6.54s`, exit 1; actual model request contained the queued prompt twice, once as the request user content and once as `[Durable next-turn injection]`. This drove the current-event-ID suppression through the existing inbox seam.
- Red for durable ownership: `test_inbox_persists_worker_start_identity_and_restores_quarantine` → `1 failed, 5 warnings in 3.04s`, exit 1 because the start-identity API did not exist.
- Green focused actual CLI + inbox → `2 passed, 5 warnings in 5.78s`, exit 0. SDK wait protocol node → `1 passed in 0.02s`, exit 0. Real CLI pre-started head quarantine node → `1 passed, 5 warnings in 5.58s`, exit 0.
- Final affected core/retry/inbox/app-server command from `D:\\Atlas\\core`: `python -m pytest -q -p no:cacheprovider -o addopts= tests/test_app_server_sdk_subprocess_attempts.py tests/test_kernel_durable_inbox.py tests/test_retry_decision_persistence.py tests/test_retry_recovery_state.py tests/test_retry_attempt_isolation.py --tb=short` → `15 passed, 5 warnings in 59.43s`, exit 0.
- Final SDK command from `D:\\Atlas\\sdk\\python`: `python -m pytest -q -p no:cacheprovider -c ../../core/pyproject.toml tests/test_app_server.py --tb=short` → `4 passed in 0.03s`, exit 0.
- Core/SDK py_compile commands both exit 0. Relevant `git diff --check` exit 0, with only Git LF-to-CRLF working-copy notices for two files. Atomic JSONL structure check → queue 31 rows, capability 36 rows, edge 25 rows, malformed=0.

## Remaining limits

- `session/wait` in this batch waits the in-memory per-session worker only. A previously started item is fail-closed but not resumed/terminalized; an enqueued item left unstarted through process shutdown is not auto-started merely by reopening a conversation. Cursor replay, cancellation/status API, and approval/input recovery remain open. These limits are routed to T3-027+; no live model or real user data was used.
