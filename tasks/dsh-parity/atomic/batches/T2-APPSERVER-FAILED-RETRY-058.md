# T2-APPSERVER-FAILED-RETRY-058 — failed retry keeps OLD only in attempt audit

Status: DONE_SCOPED

## Files and dependencies

- `core/tests/test_app_server_sdk_subprocess_attempts.py`: `pytest.mark.unit` integration test using the local loopback provider, Atlas Python SDK, and real repository CLI app-server child.
- This report, `BEYOND-DSH-PROGRESS.md`, and atomic capability/interaction/batch ledgers.
- Dependencies: T2 app-server retry/rollback audit, durable enqueue/wait/task status, and SessionDB canonical transcript plus attempt audit.
- No production change was required for this sequence.

## Binary acceptance

1. The first provider response streams OLD then drops; retry requests return provider errors until app-server task status reaches `failed`.
2. SessionDB canonical assistant transcript contains no OLD, while discarded attempt audit retains the exact consumed partial prefix and no attempt commits OLD.
3. The actual app-server child exits naturally with code 0 after shutdown.

## Verification

Collection was explicitly checked: the exact node reported `1 test collected`.

Exact command from `D:\Atlas\core`:

```text
python -m pytest -q -s -p no:cacheprovider -o addopts= tests/test_app_server_sdk_subprocess_attempts.py::test_app_server_failed_retry_keeps_old_partial_only_in_attempt_audit --basetemp C:\Users\25011\AppData\Local\Temp\atlas-t2-failed-retry-058-red --tb=short
```

Actual output: `1 passed, 5 warnings in 12.54s`, exit 0. The task reached `failed` after at least two real loopback requests. Reopened SessionDB showed no `OLD content before retry failure` in canonical assistant rows, retained only the streamed prefix `OLD conten` in one discarded `model/attempt` audit row, and had no committed attempt containing OLD. The repository CLI process exited naturally with code 0. Warnings are the existing FastAPI and Pydantic deprecations.

## Limits

This is fixture-provider evidence through the real Python SDK/app-server process, not live-model or visible Electron proof. It does not cover all provider timeout, approval, cancellation, or UI combinations. Task 1's complete source semantics and overall parity/superiority remain open.
