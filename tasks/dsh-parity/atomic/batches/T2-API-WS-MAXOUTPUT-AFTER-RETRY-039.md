# T2-API-WS-MAXOUTPUT-AFTER-RETRY-039

Status: DONE_SCOPED

## Scope and dependencies

Dependencies: T2-API-WS-FALLBACK-ATTEMPT-036, T2-ELECTRON-RETRY-ATTEMPT-038, existing retry_backend isolated Uvicorn fixture and kernel length-recovery behavior.

Files:

- core/tests/test_c1_websocket_acceptance.py
- this batch record, progress, batch queue, atomic capability and interaction-edge ledgers
- private pytest data root and dynamic loopback port; FakeLLM only

## Binary acceptance

1. Three production API requests are observed: partial OLD attempt, NEW with finish_reason=length, and continuation.
2. API events keep OLD before its attempt rollback and successful NEW/continuation output after; final completion excludes OLD.
3. The continuation request includes the accepted NEW prefix and the output-limit continuation instruction.
4. Reopened SessionDB contains the successful NEW and continuation content only; audit retains the failed OLD attempt as discarded.

## Implementation and evidence

- Added test_websocket_retry_keeps_normal_max_output_continuation. It runs the existing production /ws/chat path against isolated Uvicorn and sequences DropMidStream(OLD), Text(NEW, finish_reason=length), and Text(continuation completed).
- Exact command from D:\Atlas\core: python -m pytest -q -p no:cacheprovider -o addopts= tests/test_c1_websocket_acceptance.py::test_websocket_retry_keeps_normal_max_output_continuation --basetemp C:\Users\25011\AppData\Local\Temp\atlas-t2-039-api-maxoutput-20261117 --tb=short → 1 passed, 5 warnings in 19.34s, exit 0. Warnings are existing FastAPI/Pydantic deprecations.
- Assertions verified 3 provider requests; OLD attempt deltas precede matching rollback; successful deltas after rollback include the NEW prefix and continuation; the continuation request history contains NEW and Output token limit hit; run.completed/message.completed exclude OLD; reopened SessionDB preserves both successful parts and discarded OLD audit.
- No production API change was required by this case. Evidence is a local FakeLLM API integration, not real-model or desktop UI evidence.

## Remaining obligations

No app-server/SDK/Electron max-output continuation proof is added here. Timeout/budget/tool-error/wait/cancel/approval interactions and cross-consumer combinations, real-model work, Task 1 source semantics, and superiority remain open.
