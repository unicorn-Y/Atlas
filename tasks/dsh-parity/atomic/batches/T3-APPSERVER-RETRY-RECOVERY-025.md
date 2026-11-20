# T3-APPSERVER-RETRY-RECOVERY-025

- Status: DONE_SCOPED; Task 3 remains IN_PROGRESS.
- Capability atom: expose the durable retry recovery classifier through the real app-server session protocol and typed Python SDK, preserving unknown outcomes and retry budget across an app-server process restart without replaying the request.
- Files: core/atlas/tools/app_server.py; sdk/python/atlas_sdk/app_server.py; sdk/python/atlas_sdk/__init__.py; core/tests/test_app_server_sdk_subprocess_attempts.py; sdk/python/tests/test_app_server.py; Task 3 capability/edge/queue/progress records.
- Dependencies: retry decision/start state in T3-RETRY-START-RECOVERY-STATE-024; durable app-server session and SDK receipt in T3-APPSERVER-ENQUEUE-RECEIPT-015.
- Acceptance (binary): a real first CLI process is interrupted after the loopback FakeLLM accepts request 2; a second CLI process opens the same conversation and calls SDK retry_recovery; it receives outcome_unknown, the stored remaining attempt budget, and do_not_replay; provider request count remains 2; second CLI exits naturally. An SDK protocol unit verifies request routing and typed result parsing.

## Implementation

- Added app-server-only JSON-RPC method session/retry_recovery. It validates that the session belongs to the current app-server process, reads SessionDB events in pages, selects the latest persisted model attempt run, and calls the recovery classifier. It returns state, attempt identity, retry budget remainder, and a conservative recommended action without returning prompt/partial model text.
- Added the Python SDK AppServer.retry_recovery method and frozen AppServerRetryRecovery result type, exported from atlas_sdk.
- Unknown started requests recommend do_not_replay. A retry decision with no following request-start marker recommends explicit_resume_required; settled/empty state recommends none. This endpoint does not start or resume a worker.

## Evidence

- First test draft had a missing Hang fixture import and failed before the product assertion; corrected before the meaningful red run.
- Corrected SDK red: the typed-result test returned AttributeError because AppServer.retry_recovery was absent; the actual subprocess test restarted the CLI and reached the same missing method after opening the existing conversation.
- Red command from D:\Atlas\core: python -m pytest -q -p no:cacheprovider -o addopts= tests/test_app_server_sdk_subprocess_attempts.py::test_sdk_app_server_recovery_classifies_inflight_retry_after_process_restart --tb=short → 1 failed, 5 warnings in 11.97s, exit 1; process restart and state setup reached the missing SDK method.
- SDK red from D:\Atlas\sdk\python: python -m pytest -q -p no:cacheprovider -c ../../core/pyproject.toml tests/test_app_server.py::test_sdk_reads_typed_retry_recovery_state --tb=short → 1 failed in 0.43s, exit 1.
- First product pass failed the fixture's remaining-budget assertion: actual 19 vs expected 1 because the isolated child inherited the default retry limit. The test now explicitly sets retry attempts=2 and wait budget=30s. No product behavior was weakened.
- Green real restart command from D:\Atlas\core: the same focused subprocess node → 1 passed, 5 warnings in 11.25s, exit 0. First CLI was intentionally killed only after request 2 entered; second CLI queried outcome_unknown, attempts remaining=1, do_not_replay, and request count=2; the second CLI exited naturally with code 0.
- SDK focused command → 1 passed in 0.04s, exit 0. Full affected app-server subprocess file → 3 passed, 5 warnings in 24.56s, exit 0. Full SDK app-server test file → 3 passed in 0.02s, exit 0.
- Python py_compile for the app-server and three SDK/source test files → exit 0; relevant git diff --check → exit 0; atomic JSONL validation → 30 queue rows, 34 capability rows, 24 edge rows, malformed=0.

## Limits / next

- This is a state query/recovery consumer, not an independent queue worker or automatic retry resumer. Unknown outcomes are surfaced and not replayed; a pending scheduled-but-not-started retry still requires explicit recovery policy.
- First CLI termination is a test-owned simulated crash, not a natural exit. The second CLI exited naturally. FakeLLM is local test infrastructure; no real model, user credentials/config, data/memory/**, production port, or Git history operation was used. No commit/push/reset/stash/clean.
