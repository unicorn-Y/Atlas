# T3-APPSERVER-ACP-PENDING-REQUEST-031

Status: DONE_SCOPED

## Scope and dependencies

Dependencies: T3-028 pending request identity/invalidation, T3-029 worker terminal state, and T3-030 multi-session FIFO.

Files:

- `core/atlas/tools/app_server.py`
- `core/tests/test_app_server_acp.py`
- this batch record, `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`, and atomic queue/capability/interaction-edge ledgers

## Binary acceptance

1. Actual `serve_stdio(protocol="acp")` runs a real Kernel/FakeLLM tool request through the ACP permission callback. One stable ACP permission request is correlated to its session and answered once.
2. `reject_once` prevents the file side effect; `allow_once` writes the exact requested bytes once. Both requests reach normal ACP prompt completion.
3. ACP v1 free-text input remains an explicit unsupported result; it emits no fake input/permission request and does not wait for a response.
4. The app-server owns and gracefully shuts down `LocalExecutionRuntime` after draining active runs, while memory close remains in a `finally` path.

## Implementation and evidence

- Red: the actual Kernel tool call reached `local_file` and emitted an ACP permission request, but `allow_once` did not create the file; captured production error was `No executor is available for this tool`. The CLI app-server created `AgentOrchestrator` with no `LocalExecutionRuntime`.
- Fix: `serve_stdio` now creates the shared `LocalExecutionRuntime`, injects it into the orchestrator and shuts it down after active tasks drain, before closing memory. Memory close still runs if runtime shutdown raises.
- Initial test setup used `write_file`, which this agent runtime did not dispatch; changed to the actual `local_file` action schema. The first fixed UUID fixture also used an invalid hex seed for SQLite application-id generation; the test fixture now supplies a valid hex seed. These setup errors were not treated as product failures.
- Final command from `D:\Atlas\core`: `python -m pytest -q -p no:cacheprovider -o addopts= tests/test_app_server_acp.py --tb=short` → `15 passed, 5 warnings in 14.33s`, exit 0. The ACP permission cases use real `AgentOrchestrator`/Kernel, loopback FakeLLM, actual LocalExecutionRuntime and a real temporary file. Other ACP protocol stubs remain protocol unit tests.
- A separate protocol node proves ACP free-text `ask_user` returns the explicit unsupported result without emitting an input/permission request or waiting.

`DONE_SCOPED`: ACP permission allow/reject reaches the real local file executor through the app-server Kernel path. ACP free-text remains explicitly unsupported. No ACP reconnect, live model, desktop/browser, or packaged runtime evidence is included.
