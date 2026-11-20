# T2-SDK-PARTIAL-TOOL-ROLLBACK-056 — partial tool arguments through SDK subprocess and replay

Status: DONE_SCOPED

## Files and dependencies

- `core/tests/test_app_server_sdk_subprocess_attempts.py`: actual repository CLI app-server processes driven by the Python SDK and local FakeLLM; the module has `pytest.mark.unit`.
- This batch record, progress, batch queue, atomic capability and interaction-edge ledgers.
- Dependencies: T2 attempt rollback/commit events, existing SDK CLI attempt replay, and normal max-output continuation behavior.
- No production change was needed: the new real subprocess regression passed on the current production path.

## Binary acceptance

1. A dropped OLD response includes incomplete `write_file` JSON arguments; the target file is never created.
2. SDK events contain OLD only before the matching attempt rollback; accepted stream/result contains NEW and its normal max-output continuation.
3. The retry and continuation provider histories omit OLD and the failed tool-call ID; continuation includes NEW and the output-limit continuation instruction.
4. After both app-server children exit 0, a second child reopens the same conversation; request history and SessionDB contain NEW/continuation/follow-up but no OLD, while SessionDB retains the discarded OLD attempt audit.

## Verification

Exact command from `D:\Atlas\core`:

```text
python -m pytest -q -s -p no:cacheprovider -o addopts= tests/test_app_server_sdk_subprocess_attempts.py::test_sdk_app_server_discards_partial_tool_arguments_before_retry_and_replay --basetemp C:\Users\25011\AppData\Local\Temp\atlas-t2-sdk-partial-tool-056-red --tb=short
```

Actual result: `1 passed, 5 warnings in 13.60s`, exit 0. Both repository CLI child processes were checked to exit naturally with code 0. The local FakeLLM observed three requests for OLD failure, NEW length-limited answer and continuation, then one follow-up request after restart. The isolated workspace write target did not exist; reopened SessionDB kept the discarded OLD audit separately from NEW-only canonical assistant history.

## Limits

This is a real local SDK/app-server subprocess and persistence/replay path, but uses a local fake provider. It is not real-model, Electron UI, all approval/wait/timeout/tool-error combinations, parity or superiority evidence. The parent Task 2 remains open.
