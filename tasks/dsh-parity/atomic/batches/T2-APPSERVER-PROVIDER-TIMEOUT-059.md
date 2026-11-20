# T2-APPSERVER-PROVIDER-TIMEOUT-059 — timeout after OLD partial stream

Status: DONE_SCOPED

## Files and dependencies

- `core/tests/test_app_server_sdk_subprocess_attempts.py`: `pytest.mark.unit` integration through the real Atlas CLI app-server subprocess and Python SDK.
- This report, `BEYOND-DSH-PROGRESS.md`, and atomic capability/interaction/batch ledgers.
- Dependencies: app-server OLD rollback audit, provider timeout routing, durable enqueue/wait/task status, and SessionDB transcript/audit.
- No production change was required.

## Binary acceptance

1. The first provider response emits a partial OLD stream and disconnects. Later requests all hang; the provider read timeout is configured to one second in this test's isolated temporary config only.
2. The actual app-server task reaches `failed` within the test's 30-second request bound. Canonical assistant history excludes OLD; the discarded audit stores exactly the consumed prefix `OLD timeout `, and no committed attempt contains OLD.
3. The app-server child exits naturally with code 0.

## Verification

Collection was explicitly checked: the exact node reported `1 test collected`.

Exact green command from `D:\Atlas\core`:

```text
python -m pytest -q -s -p no:cacheprovider -o addopts= tests/test_app_server_sdk_subprocess_attempts.py::test_app_server_provider_timeout_keeps_old_partial_only_in_attempt_audit --basetemp C:\Users\25011\AppData\Local\Temp\atlas-t2-timeout-oldnew-059-final --tb=short
```

Actual output: `1 passed, 5 warnings in 19.50s`, exit 0. The 5 warnings are the existing FastAPI and Pydantic deprecations. The process exited naturally with code 0; the SessionDB query confirmed the canonical/audit separation.

The first red attempt returned `completed` because the fake server's scripted responses ran out and its documented default response was `Text("ok")`; this did not exercise a timeout terminal. The final fixture uses a responder that returns a hang for every request after the OLD disconnect, preventing the implicit default-success path. This is recorded as a fixture correction, not a production fix.

## Limits

This is a local fixture-provider and real app-server process test, not live-model or Electron-visible evidence. It covers provider read-timeout after OLD partial output only. Other retry/timeouts, desktop delivery, complete source coverage, parity, and superiority remain open.
