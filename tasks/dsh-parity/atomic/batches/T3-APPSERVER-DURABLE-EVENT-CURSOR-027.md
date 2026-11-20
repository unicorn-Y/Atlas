# T3-APPSERVER-DURABLE-EVENT-CURSOR-027

- Status: DONE_SCOPED.
- Capability atom: app-server and Python SDK expose bounded durable SessionDB event pages keyed by the canonical session/conversation and monotonic SessionDB sequence cursor.
- Files: `core/atlas/tools/app_server.py`; `sdk/python/atlas_sdk/app_server.py`; `sdk/python/atlas_sdk/__init__.py`; `core/tests/test_app_server_sdk_subprocess_attempts.py`; `sdk/python/tests/test_app_server.py`; atomic queue/capability/edge/progress records.
- Dependencies: T3-026 persisted inbox enqueue/start/consume lifecycle and the attempt commit sequence; T3-025 real CLI reopen and typed SDK session recovery; existing `read_session_events(after_seq, limit)`.
- Acceptance (binary): an actual repository CLI app-server enqueues and completes one FakeLLM task; SDK reads a deliberately small first page and obtains a cursor; first CLI exits naturally; second CLI opens the same conversation and reads after the cursor. Returned `seq` values must be strictly increasing, pages must not repeat an event, and concatenated pages must contain the item's `inbox.enqueued`, `inbox.started`, committed model attempt and `inbox.consumed` records with no event missing at the page boundary. FakeLLM request count must not increase during replay. Unknown session and invalid cursor/limit are rejected. SDK result objects must validate identities/types rather than returning untyped JSON.
- Explicit boundary: durable page replay is not itself a live push subscription, request-scoped cancel/status, pending approval/input reattachment, automatic recovery of a started item, or real-model evidence; those remain separate obligations.

## Implementation

- Added app-server-only JSON-RPC method `session/events`. It validates the current process's session ownership, requires a non-bool nonnegative integer `after_seq` and `limit` in 1–1000, reads at most `limit+1` durable SessionDB events, and returns a bounded page plus `next_cursor` only when another page exists.
- Added public SDK types `AppServerSessionEvent` and `AppServerEventPage`, exported from `atlas_sdk`; `AppServer.session_events()` validates identities, event payload shapes, strict sequence order and cursor consistency before returning typed rows.

## Evidence

- Red: actual CLI subprocess event replay node returned JSON-RPC `method not found: session/events` → `1 failed, 5 warnings in 7.02s`, exit 1.
- First routed run failed the test's page-boundary expectation: `1 failed, 5 warnings in 8.93s`, exit 1 because `inbox.started` correctly fell in page 1 at limit=2. The test was corrected to assert full lifecycle coverage over the concatenated pages; no product behavior or acceptance was weakened.
- Focused actual two-process cursor replay → `1 passed, 5 warnings in 9.60s`, exit 0; after adding backend bool-cursor/zero-limit rejection assertions, rerun → `1 passed, 5 warnings in 9.18s`, exit 0. The first CLI completed the enqueue worker and exited naturally; the second CLI opened the same conversation, replayed after page-1 cursor, observed the committed attempt and inbox consumption, provider count remained one, and second CLI exited naturally.
- SDK typed page/cursor validation node → `1 passed in 0.03s`, exit 0. Full SDK app-server file → `5 passed in 0.04s`, exit 0.
- Final affected core/retry/inbox/app-server command from `D:\\Atlas\\core`: `python -m pytest -q -p no:cacheprovider -o addopts= tests/test_app_server_sdk_subprocess_attempts.py tests/test_kernel_durable_inbox.py tests/test_retry_decision_persistence.py tests/test_retry_recovery_state.py tests/test_retry_attempt_isolation.py --tb=short` → `16 passed, 5 warnings in 69.53s`, exit 0.
- Core app-server and integration test py_compile, SDK module/export/test py_compile, relevant `git diff --check` exit 0. Atomic JSONL parse → queue 32 rows, capability 37 rows, edge 26 rows, malformed=0.

## Remaining limits

- This is bounded durable polling/replay, not a live subscription API or task-specific status/cancel. It does not reconnect approvals/input, restart pending worker execution, or automatically resolve started queue items. No real model/user data was used.
