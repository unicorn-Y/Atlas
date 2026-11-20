# T3-RETRY-DECISION-DURABILITY-023

- Status: DONE_SCOPED; Task 3 remains IN_PROGRESS.
- Capability atom: persist the Kernel's retry/deny decision and reserved task retry budget in SessionDB before any subsequent provider request; do not continue successfully when this decision audit cannot be written.
- Files: `core/atlas/engine/kernel/model_call.py`; `core/atlas/engine/kernel/loop.py`; `core/tests/test_retry_decision_persistence.py`; Task 3 capability/edge/queue/progress records.
- Dependencies: existing Kernel attempt events and durable SessionDB (`T2-RETRY-BUDGET-AND-STREAM-COMPAT-018`); durable request identity/inbox/app-server enqueue receipt (`T3-APPSERVER-ENQUEUE-RECEIPT-015`); prior attempt rollback consumers through Electron development shell (`T2-ELECTRON-ATTEMPT-ROLLBACK-022`).
- Acceptance (binary): an actual Kernel + loopback FakeLLM stream fails OLD then receives NEW, and the second HTTP responder can reopen SessionDB and read the first attempt's retry kind/delay/reserved and remaining attempt/wait budget before returning NEW; an exhausted attempt budget persists a denial reason and sends exactly one request; a forced discarded-attempt audit write error emits an error and sends no second request or successful result.

## Implementation

- `attempt_discarded` now carries retry kind/number/delay, a denial reason, retry attempt and wait limits, planned use after the decision, and remaining budget. The values are calculated at the retry reservation boundary before the event is published.
- Kernel persists those fields in the existing `model/attempt` SessionDB lifecycle record. It awaits that write before rollback publication and before `complete_stream` can sleep/send the next provider request.
- Attempt audit write errors now raise a non-retryable `ModelCallError` after queuing the recovery notice, so the caller cannot continue to a successful second request with an unrecorded retry decision.

## Evidence

- Initial corrected red command from `D:\Atlas\core`: `python -m pytest -q -p no:cacheprovider -o addopts= tests/test_retry_decision_persistence.py --tb=short` → `3 failed, 5 warnings in 16.43s`, exit 1. The two persistence assertions found missing `retry_kind` and `retry_denied_reason`; audit-failure case observed two provider requests instead of one.
- Final focused regression command from `D:\Atlas\core`:

  ```text
  python -m pytest -q -p no:cacheprovider -o addopts= tests/test_retry_decision_persistence.py --tb=short
  ```

  Exact output: `3 passed, 5 warnings in 10.50s`, exit 0. The second FakeLLM responder reopened SessionDB while handling request 2 and observed the discarded decision already stored.
- Combined retry boundary command from `D:\Atlas\core`:

  ```text
  python -m pytest -q -p no:cacheprovider -o addopts= tests/test_retry_decision_persistence.py tests/test_retry_attempt_isolation.py tests/test_atlas_runtime_e2e.py::test_retry_attempt_rollback_is_emitted_by_kernel_before_new_answer tests/test_atlas_runtime_e2e.py::test_kernel_discards_partial_failed_tool_call_before_retry_and_persists_only_new tests/test_atlas_runtime_e2e.py::test_stream_fault_budget_disables_hidden_retry_only_when_opted_in tests/test_atlas_runtime_e2e.py::test_stream_options_compat_retry_is_budgeted_only_when_opted_in tests/test_atlas_runtime_e2e.py::test_stream_options_unrelated_bad_request_does_not_retry tests/test_atlas_runtime_e2e.py::test_auxiliary_complete_transport_retry_obeys_run_budget --tb=short
  ```

  Exact output: `13 passed, 5 warnings in 30.39s`, exit 0. The subsequent focused rerun after a readability-only expression edit also returned `3 passed, 5 warnings in 10.50s`, exit 0.
- `python -m py_compile atlas/engine/kernel/model_call.py atlas/engine/kernel/loop.py tests/test_retry_decision_persistence.py` → exit 0. AST markers show `attempt_discarded` remains inside the provider-error `ExceptHandler`, and the audit failure `raise` remains inside the nested audit-write `ExceptHandler`. `git diff --check -- ...` → exit 0 (Git reported its existing LF-to-CRLF working-copy notice).

## Limits / next

- This atom persists retry decisions; it does not yet resume, wait on, or terminate a durable task after process restart. That recovery consumer is the next Task 3 atom.
- Validation uses private test roots and loopback FakeLLM, not a real model. No user configuration/credentials, `data/memory/**`, production port, Git history operation, or real model was used. No commit/push/reset/stash/clean.
