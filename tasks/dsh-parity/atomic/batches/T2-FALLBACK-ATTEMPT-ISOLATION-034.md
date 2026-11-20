# T2-FALLBACK-ATTEMPT-ISOLATION-034

Status: DONE_SCOPED

## Scope and dependencies

Dependencies: T2-ATTEMPT-LIFECYCLE-001, T2-RETRY-BUDGET-AND-STREAM-COMPAT-018, T2-ACP-KERNEL-ATTEMPT-STREAM-021, T2-ELECTRON-ATTEMPT-ROLLBACK-022, and T1-METHOD-CONFIG-CONTRACTS-033 audit schema artifacts.

Files:

- `core/tests/test_atlas_runtime_e2e.py`
- `core/atlas/engine/kernel/model_call.py` and/or `core/atlas/engine/kernel/loop.py` only if the new production-path assertion exposes a defect
- this batch record, `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`, and atomic capability/interaction-edge/batch-queue ledgers
- loopback FakeLLM and temporary model config only

## Binary acceptance

1. Actual AtlasRuntime → AgentOrchestrator → Kernel → ModelRouter selects the configured fallback after the primary attempt is filtered.
2. Observed request model order is primary then fallback; only NEW fallback text reaches final result and canonical SessionDB assistant transcript.
3. OLD primary attempt remains available as discarded attempt audit and does not appear in the canonical transcript.
4. Retry count is bounded by the isolated test config; no live model route, user credentials/config, or user data is used.

## Implementation and evidence

- Added `test_configured_fallback_commits_new_attempt_and_audits_filtered_primary` to the actual `AtlasRuntime.run_turn` path. It supplies `AgentRunContext.fallback_models`, so the test exercises the Kernel's runtime fallback contract rather than inferring fallback from an isolated `ModelRouter` call.
- The test observes loopback request order `primary-model`, then `fallback-model`; the result event and canonical SessionDB assistant transcript contain `NEW fallback answer`; the persisted attempt audit records `OLD filtered answer` as discarded and canonical history contains no OLD text.
- Existing `test_retry_attempt_rollback_is_emitted_by_kernel_before_new_answer` was structurally repaired after the new test had been inserted before its remaining assertions. Both tests are now separate functions and the original assertions remain active.
- Final command (`D:\Atlas\core`): `python -m pytest -q -p no:cacheprovider -o addopts= tests/test_atlas_runtime_e2e.py::test_retry_attempt_rollback_is_emitted_by_kernel_before_new_answer tests/test_atlas_runtime_e2e.py::test_configured_fallback_commits_new_attempt_and_audits_filtered_primary --tb=short` → **2 passed, 5 warnings in 11.24s**, exit 0. Pytest collected and ran exactly 2 tests. The warnings are existing FastAPI `on_event` and Pydantic class-config deprecations.
- `python -m py_compile tests/test_atlas_runtime_e2e.py` and `git diff --check -- tests/test_atlas_runtime_e2e.py` both exited 0.
- Initial fixture attempts without `AgentRunContext.fallback_models` produced a primary-only failure; that did not establish a production defect because the direct runtime test bypasses run-phase config assembly. The final test uses the production context field and sees the actual fallback request.
- This is an isolated FakeLLM/temporary-home integration result, not live model, packaged desktop, full retry/fallback matrix, ACP reconnect, or overall Task 2 completion. No production code changed in this batch; broader attempt isolation and superiority obligations remain open.
