# T2-C1-RECOVERY-019

- Status: DONE_SCOPED; Task 2 remains IN_PROGRESS.
- Capability atom: treat a provider's empty completed response as an unsuccessful model attempt and validate partial-stream recovery against current rollback/commit events.
- Files: `core/atlas/engine/kernel/model_call.py`; `core/tests/test_c1_recovery.py`.
- Dependencies: T2 retry budget and stream compatibility atom 018.
- Acceptance (binary): an empty completion with no text, refusal, or tool call must not be committed as success; the actual next request must return the recovery answer. A dropped mid-stream response must publish a rollback and a later committed attempt while returning the recovered answer.
- Red command from `D:\Atlas\core`: `python -m pytest -q -p no:cacheprovider -o addopts= 'tests/test_c1_recovery.py::test_atlas_recovers_provider_fault_and_finishes[fault3]' 'tests/test_c1_recovery.py::test_atlas_recovers_provider_fault_and_finishes[fault5]' --tb=short` → `2 failed, 5 warnings in 10.41s`, exit 1. `fault3` returned an empty successful response; `fault5` recovered text but the test still required the obsolete `run.recovery.notice` event.
- Green focused command: same two node IDs after fix → `2 passed, 5 warnings in 9.87s`, exit 0. Whole recovery file command `python -m pytest -q -p no:cacheprovider -o addopts= tests/test_c1_recovery.py --tb=short` → `1 failed, 6 passed, 5 warnings in 16.06s`, exit 1. All six provider-fault recovery cases passed; the remaining failure is the separately queued resume-history assertion that the first request contains `read the fixture`.
- Combined final command across the focused rollback/budget/compatibility/auxiliary nodes plus all six provider-fault cases → `16 passed, 5 warnings in 33.98s`, exit 0. Resume-history remained excluded and open.
- The kernel classifies empty output as retryable `empty_response` before attempt commit. The test now requires current `message.rollback` and `model_attempt_committed` lifecycle events for the dropped stream, not the old generic recovery notice.
- Static validation and the earlier exact C1 fixture output are recorded in command logs; no real model or user data/config was used. This atom does not close whole recovery, Task 2, or the overall parity plan.
