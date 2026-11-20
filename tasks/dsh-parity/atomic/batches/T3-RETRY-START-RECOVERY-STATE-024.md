# T3-RETRY-START-RECOVERY-STATE-024

- Status: DONE_SCOPED; Task 3 remains IN_PROGRESS.
- Capability atom: persist every Kernel provider-attempt start before the network request, then classify a reopened SessionDB trail as settled, scheduled-but-not-started, or outcome-unknown without replaying it.
- Files: core/atlas/engine/kernel/loop.py; core/atlas/engine/session_sync.py; core/tests/test_retry_recovery_state.py; Task 3 capability/edge/queue/progress records.
- Dependencies: durable retry decision/budget records from T3-RETRY-DECISION-DURABILITY-023; existing attempt isolation and SessionDB event ordering.
- Acceptance (binary): a real Kernel/FakeLLM OLD→NEW turn reopens SessionDB and yields started → discarded(retry) → started → committed, classified settled; a run cancelled after FakeLLM accepts request 2 reopens SessionDB with request 2 still started, classifies outcome_unknown, preserves one remaining retry attempt, and produces no third request.

## Implementation

- Kernel now awaits a durable model/attempt row with status started from its attempt_started callback, before the provider stream is opened.
- classify_retry_recovery reads only persisted model/attempt events for the requested run. It returns retry_scheduled_not_started when a retry decision has no following start row, outcome_unknown when a started request lacks a committed/discarded terminal row, and settled for terminal attempt records. It carries the retry budget remainder forward from the preceding decision.
- The classifier is read-only and does not reissue model calls. It is a recovery-state primitive, not yet wired into an app-server or SDK process restart route.

## Evidence

- Corrected red from D:\Atlas\core: python -m pytest -q -p no:cacheprovider -o addopts= tests/test_retry_recovery_state.py --tb=short → 2 failed, 5 warnings in 18.78s, exit 1. The actual turn audit was discarded, committed (missing both start markers); the interrupted request audit was discarded (missing started rows and classifier).
- Unknown-status red: python -m pytest -q -p no:cacheprovider -o addopts= tests/test_retry_recovery_state.py::test_retry_recovery_classifier_keeps_unknown_status_unsettled --tb=short → 1 failed, 6 warnings in 2.95s, exit 1; future-status had incorrectly returned settled.
- An earlier version of the interruption fixture used a context cancel event that did not reach the actual Kernel cancellation path and hit its 5s deadline. The fixture was changed to cancel its own run task after FakeLLM observed request 2; that corrected red above reaches the intended assertions.
- Final focused command from D:\Atlas\core: same command → 2 passed, 5 warnings in 18.14s, exit 0.
- Final three-node classifier command after the unknown-status guard → 3 passed, 5 warnings in 18.64s, exit 0.
- Combined command from D:\Atlas\core:

  python -m pytest -q -p no:cacheprovider -o addopts= tests/test_retry_decision_persistence.py tests/test_retry_recovery_state.py tests/test_retry_attempt_isolation.py tests/test_app_server_sdk_subprocess_attempts.py tests/test_atlas_runtime_e2e.py::test_retry_attempt_rollback_is_emitted_by_kernel_before_new_answer tests/test_atlas_runtime_e2e.py::test_kernel_discards_partial_failed_tool_call_before_retry_and_persists_only_new tests/test_atlas_runtime_e2e.py::test_stream_fault_budget_disables_hidden_retry_only_when_opted_in tests/test_atlas_runtime_e2e.py::test_stream_options_compat_retry_is_budgeted_only_when_opted_in tests/test_atlas_runtime_e2e.py::test_stream_options_unrelated_bad_request_does_not_retry tests/test_atlas_runtime_e2e.py::test_auxiliary_complete_transport_retry_obeys_run_budget --tb=short

  Before the unknown-status guard: 17 passed, 5 warnings in 60.93s, exit 0. The final rerun after all 024 changes returned 18 passed, 5 warnings in 60.70s, exit 0. This includes durable enqueue subprocess tests; it does not simulate a crash/restart during a model attempt.
- python -m py_compile atlas/engine/kernel/model_call.py atlas/engine/kernel/loop.py atlas/engine/session_sync.py tests/test_retry_decision_persistence.py tests/test_retry_recovery_state.py → exit 0. git diff --check on production/tests/atomic ledger paths → exit 0. The earlier static check ran from the wrong working directory and failed to locate files; the corrected command was rerun successfully.

## Limits / next

- No actual app-server process restart has consumed this classifier yet. The next batch wires it into the SDK/app-server reopen path and verifies recovery across two independent CLI processes.
- FakeLLM is loopback test infrastructure, not a real model. No user config/credentials, data/memory/**, production port, or real model used. No commit/push/reset/stash/clean.
