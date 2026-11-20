# T2-SDK-APPSERVER-FALLBACK-REPLAY-035

Status: DONE_SCOPED

## Scope and dependencies

Dependencies: T2-FALLBACK-ATTEMPT-ISOLATION-034, T2-ATTEMPT-LIFECYCLE-001, the existing real Python SDK → repository CLI app-server subprocess fixture, and isolated SessionDB restart/replay behavior.

Files:

- `core/tests/test_app_server_sdk_subprocess_attempts.py`
- this batch record, progress, batch queue, atomic capability and interaction-edge ledgers
- isolated FakeLLM, CLI child, temporary Atlas/Hermes homes and SessionDB only

## Binary acceptance

1. Actual Python SDK launches the repository CLI app-server; primary `fake-model` is content-filtered and the configured `fallback-model` supplies the completed response.
2. SDK event stream carries OLD attempt chunks only before a rollback with the same attempt ID; NEW chunks follow rollback under another ID; final SDK result is NEW.
3. Both CLI children exit naturally with code 0. A restarted app-server replays NEW and not OLD from the same conversation; reopened SessionDB canonical transcript is OLD-free and durable audit keeps OLD as discarded with the rollback ID.

## Implementation and evidence

- Extended `_isolated_app_server_env` with an optional second model so the subprocess uses a real model fallback configuration while preserving existing single-model fixture behavior.
- Added `test_sdk_app_server_fallback_attempt_isolated_across_process_restart`. FakeLLM request model sequence is exactly `fake-model`, `fallback-model`, `fake-model`. The SDK stream contains OLD pieces before the corresponding rollback and NEW after; final SDK response is `NEW fallback answer`. After the first process exits 0 and the second exits 0, the next request history includes NEW and excludes OLD. Reopened SessionDB contains `NEW fallback answer` and `FOLLOW-UP answer`, never OLD; `model/attempt` audit retains OLD discarded with the rollback attempt ID.
- One early assertion incorrectly required a complete answer phrase in a single SDK chunk. It was replaced with concatenated stream-order assertions over actual chunk boundaries; no weaker test behavior or production change was used.
- Focused pair command (`D:\Atlas\core`): `python -m pytest -q -p no:cacheprovider -o addopts= tests/test_app_server_sdk_subprocess_attempts.py::test_real_sdk_app_server_subprocess_commits_only_new_attempt_and_reopens_audit tests/test_app_server_sdk_subprocess_attempts.py::test_sdk_app_server_fallback_attempt_isolated_across_process_restart --tb=short` → **2 passed, 5 warnings in 21.01s**, exit 0. Both child process natural exits were asserted inside the tests.
- Standalone new node earlier passed **1 passed, 5 warnings in 9.58s**, exit 0. Existing FastAPI/Pydantic deprecation warnings only.
- This is a loopback FakeLLM/real repository SDK and CLI subprocess/temporary SessionDB result. No live model, packaged SDK/Electron distribution, renderer, or all-attempt scenarios were tested. Task 2 and overall parity remain open.
