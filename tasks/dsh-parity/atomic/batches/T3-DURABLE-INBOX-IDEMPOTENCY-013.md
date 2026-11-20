# T3-DURABLE-INBOX-IDEMPOTENCY-013

- Status: DONE_SCOPED
- Capability atom: stable per-session enqueue receipt and payload-conflict rejection across DurableInbox reconstruction.
- Files: `core/atlas/engine/kernel/inbox.py`; `core/tests/test_kernel_durable_inbox.py`; this batch record; capability/interaction/queue ledgers and progress. `session_sync.py` and app-server/SDK consumers are dependencies/next atoms and are not changed in this atom unless the underlying event append contract proves insufficient.
- Dependencies: existing append-only SessionDB `inbox.enqueued` / `inbox.consumed` persistence.
- Acceptance (binary): with client request key K, duplicate injection before and after reconstructing DurableInbox returns the original event ID and creates exactly one `inbox.enqueued`; reusing K for different normalized content or lane is rejected; queue consumption does not erase the durable idempotency receipt.
- Rollback boundary: temporary SessionDB only; no user data/config, external provider, installed CLI, or live port.
- Red command from `D:\Atlas\core`: `python -m pytest -q -p no:cacheprovider -o addopts= tests/test_kernel_durable_inbox.py::test_inbox_enqueue_request_key_is_durable_idempotent_and_rejects_payload_reuse --tb=line`; output `1 failed, 5 warnings in 2.28s`, exit `1`; exact failure `TypeError: DurableInbox.inject() got an unexpected keyword argument 'request_id'`.
- Green command: `python -m pytest -q -p no:cacheprovider -o addopts= tests/test_kernel_durable_inbox.py tests/test_agent_inbox_wiring.py --tb=short`; output `3 passed, 5 warnings in 3.03s`, exit `0`. A final identical focused run after `py_compile` reported `3 passed, 5 warnings in 2.98s`, exit `0`.
- `inbox.enqueued` now optionally stores a normalized per-conversation request key and reconstructs a durable receipt map after restart; same key/lane/content returns the same event ID even after consumption, while different payload reuse fails. Legacy callers that omit request ID keep their prior behavior. `python -m py_compile atlas/engine/kernel/inbox.py tests/test_kernel_durable_inbox.py` and `git diff --check` exited `0` (only LF→CRLF notices).
- This scoped primitive does not yet establish cross-process concurrent uniqueness, app-server/SDK receipt API wiring, wake/subscription, run execution, or source-role mapping. Those remain separate Task 3 atoms; not complete.
