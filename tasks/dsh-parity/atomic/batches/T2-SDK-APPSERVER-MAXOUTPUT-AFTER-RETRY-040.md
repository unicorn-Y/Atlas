# T2-SDK-APPSERVER-MAXOUTPUT-AFTER-RETRY-040

Status: DONE_SCOPED

## Scope and dependencies

Dependencies: T2-SDK-APPSERVER-FALLBACK-REPLAY-035, T2-API-WS-MAXOUTPUT-AFTER-RETRY-039, real repository CLI subprocess fixture.

Files:

- core/tests/test_app_server_sdk_subprocess_attempts.py
- this batch record, progress, batch queue, atomic capability and interaction-edge ledgers
- temporary SDK/app-server data root and FakeLLM only

## Binary acceptance

1. Actual SDK->CLI app-server run receives OLD partial failure, NEW with finish_reason=length and a continuation response.
2. SDK attempt events retain OLD/rollback identity; SDK result and accepted stream contain NEW plus continuation and no OLD.
3. Continuation request history contains NEW and Output token limit hit.
4. Both CLI processes exit naturally; restart/replay history and reopened SessionDB retain successful content and exclude OLD while preserving discarded OLD audit.

## Implementation and evidence

- Added test_sdk_app_server_retry_keeps_max_output_continuation_across_restart. It invokes the repository CLI via the Python SDK, completes the continuation, closes that CLI, opens a second CLI for the same conversation, and submits a follow-up.
- Exact command from D:\Atlas\core: python -m pytest -q -p no:cacheprovider -o addopts= tests/test_app_server_sdk_subprocess_attempts.py::test_sdk_app_server_retry_keeps_max_output_continuation_across_restart --basetemp C:\Users\25011\AppData\Local\Temp\atlas-t2-040-sdk-maxoutput-20261117 --tb=short → 1 passed, 5 warnings in 17.18s, exit 0. Warnings are existing FastAPI/Pydantic deprecations.
- Observed SDK result NEW answercontinuation completed; accepted stream had NEW and continuation after rollback; request 3 included NEW plus Output token limit hit; after restart request 4 history included NEW and continuation but excluded OLD. Reopened temporary SessionDB contained NEW, continuation and follow-up, no OLD assistant text, and preserved the failed attempt as discarded audit. Both CLI subprocesses were asserted exit 0.
- No production code change was needed for this consumer path. This uses FakeLLM and temporary roots; it is not live-model, packaged SDK, Electron, or graceful Uvicorn shutdown proof.

## Remaining obligations

Electron max-output UI, real-model behavior, timeout/budget/tool-error/wait/cancel/approval matrices, source-wide semantics and superiority remain open.
