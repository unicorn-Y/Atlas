# T3-APPSERVER-PENDING-REQUEST-RECOVERY-028

Status: DONE_SCOPED

## Scope and dependencies

Dependencies: T3-025 retry recovery query, T3-026 app-server durable enqueue worker, and T3-027 durable session event cursor.

Files in this atomic batch:

- `core/atlas/tools/app_server.py`
- `sdk/python/atlas_sdk/app_server.py`
- `sdk/python/atlas_sdk/__init__.py`
- `core/tests/test_app_server_sdk_subprocess_attempts.py`
- `sdk/python/tests/test_app_server.py`
- this batch record, `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`, and the atomic queue/capability/interaction-edge ledgers

## Binary acceptance

1. A real CLI app-server run can pause on an actual model-issued input request and an actual approval-gated tool. After the SDK prompt notification consumer detaches on timeout, a same-process reconnect query discovers the pending request and the matching SDK response API completes that exact request. The run settles naturally; no duplicate model request or repeated prompt is introduced.
2. After an app-server process exits with a request unresolved, a new process reopening the same conversation reports the prior request as `invalidated`; it cannot accept the old request ID, grant approval, or answer input, and it issues no new model request. Request persistence contains identifiers/status only, never prompt text, options, or tool arguments.
3. New tests first fail on the missing discovery/invalidation behavior. Focused tests, affected retry/inbox/cursor integration tests, SDK tests, syntax/static checks, and ledger JSONL validation pass. No live model, user config/credentials, `data/memory/**`, port 8765, or Git history write is used.

## Implementation and evidence

- The app-server issues a random request ID alongside existing approval/input wire IDs. The typed SDK exposes `pending_requests`, `respond_approval`, and `respond_input`; legacy `event_id`/`call_id` response fields remain accepted for existing SDK callers.
- `appserver.request` SessionDB events persist only request ID, source session, kind, lifecycle state, and process-instance ID. Prompt text, input options, tool arguments, and other request detail stay in current-process memory. A bounded 10-page scan (1,000 events per page) fails closed if older history exceeds the scan window.
- A same-process app-server query returns active request details. A reopened process seeing a prior process's `pending` request appends `invalidated` and returns only its minimal identity/state. It never rebuilds an old Future. An old response ID is rejected; no model request is replayed.
- The real CLI subprocess tests use `session/enqueue` only—no synchronous `session/prompt` call—for both `ask_user` input and `request_permissions` approval. Same-process reconnect completes the original worker and observes `pending → resolved`; restart cases deliberately terminate the first test-owned process, reject stale input/approval, preserve one provider request, and let the second process exit naturally 0.

### Commands and outputs

- RED: `cd D:\Atlas\core; python -m pytest -q -p no:cacheprovider -o addopts= tests/test_app_server_sdk_subprocess_attempts.py::test_app_server_pending_request_reconnects_in_same_process[input] --tb=short` → `1 failed, 5 warnings in 7.91s`, exit 1: missing `AppServer.pending_requests` API.
- Restart regression found an implementation defect during development: an invalidation path referenced `append_session_event` without importing it; the import was added. The SDK also initially rejected an invalidated record carrying its original session ID; validation now permits that only for `invalidated`, while active `pending` records still must match the queried session.
- Bounded new-case verification: `cd D:\Atlas\core; python -m pytest -q -p no:cacheprovider -o addopts= tests/test_app_server_sdk_subprocess_attempts.py::test_app_server_pending_request_reconnects_in_same_process tests/test_app_server_sdk_subprocess_attempts.py::test_app_server_invalidates_old_pending_request_after_process_restart --tb=short` → `4 passed, 5 warnings in 21.61s`, exit 0. A preliminary 15-second readiness window expired before one worker started; it was replaced with a 30-second event-based deadline, not a fixed sleep. The final run passed.
- SDK tests: `cd D:\Atlas\sdk\python; python -m pytest -q -p no:cacheprovider -o addopts= tests/test_app_server.py --tb=short` → `6 passed, 1 warning in 0.04s`, exit 0. Warning: the SDK test package does not register the repo's `unit` marker.
- Final affected core combination: `cd D:\Atlas\core; python -m pytest -q -p no:cacheprovider -o addopts= tests/test_app_server_sdk_subprocess_attempts.py tests/test_kernel_durable_inbox.py tests/test_retry_decision_persistence.py tests/test_retry_recovery_state.py tests/test_retry_attempt_isolation.py --tb=short` → `20 passed, 5 warnings in 84.77s`, exit 0.
- `py_compile` for app-server and SDK modules, `git diff --check` for scoped files, and AST checks confirming the nested route remains under `serve_stdio` and `list_pending_requests` is a direct `serve_stdio` helper all exited 0. Atomic JSONL validation: queue 33 rows, capability 38 rows, interaction edges 27 rows; malformed 0 before this batch's final ledger updates.

### Evidence boundary

This is an isolated CLI app-server + Python SDK proof using `FakeLLMServer`, not a real-model or desktop/browser run. It proves no synchronous prompt is required for enqueued input/approval and that prior-process pending IDs are invalidated. It does not prove Electron notification UI wiring, ACP pending-request reconnect, worker recovery/resume after process restart, live event push, or completion of Task 3/Tasks 1–9. The prior app-server process in restart cases is intentionally killed by the test; only the reopened second process exits naturally.
