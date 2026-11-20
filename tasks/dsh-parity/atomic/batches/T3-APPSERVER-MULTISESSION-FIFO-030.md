# T3-APPSERVER-MULTISESSION-FIFO-030

Status: DONE_SCOPED

## Scope and dependencies

Dependencies: T3-026 durable enqueue worker, T3-028 pending request recovery, and T3-029 worker terminal state.

Expected files:

- `core/atlas/tools/app_server.py` (only if the real subprocess regression exposes a production defect)
- `core/tests/test_app_server_sdk_subprocess_attempts.py`
- `sdk/python/atlas_sdk/app_server.py` and `sdk/python/tests/test_app_server.py` only if the protocol surface needs a change
- this batch record, `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`, and the atomic queue/capability/interaction-edge ledgers

## Binary acceptance

1. One real CLI app-server process owns two SDK sessions. Session A receives two stable request IDs in FIFO order while session B receives a third.
2. With A's first provider request held open, B's task reaches terminal completed. A's second provider request does not begin before A's first settles; it then completes after it.
3. Each result, SessionDB event, and request ID remains attached to its originating session. Exactly three provider requests occur; no enqueue receipt is replayed or executed twice.
4. The CLI app-server exits naturally with code 0. Tests use isolated data and FakeLLM, not live model or user service evidence.

## Implementation and evidence

- Added `test_app_server_keeps_session_fifo_while_other_session_runs_independently` before changing production code. It passed on the first production-path run, so no code change was needed.
- Command from `D:\Atlas\core`: `python -m pytest -q -p no:cacheprovider -o addopts= tests/test_app_server_sdk_subprocess_attempts.py::test_app_server_keeps_session_fifo_while_other_session_runs_independently --tb=short` → `1 passed, 5 warnings in 9.61s`, exit 0.
- One actual CLI app-server subprocess owned two SDK sessions. While session A's first loopback FakeLLM request was held, session B completed; session A's second task remained queued and only started after A's first request settled. Provider requests occurred A-first, B-only, A-second (exactly 3). Reopened SessionDB transcripts and events contained each result and request ID only under its originating conversation. The app-server subprocess exited naturally with code 0.

`DONE_SCOPED`: same-session FIFO and cross-session worker independence are confirmed through the CLI app-server and Python SDK with isolated SessionDB/FakeLLM. This does not close live-model, renderer/Electron, ACP, packaged runtime, or complete Task 3 obligations.
