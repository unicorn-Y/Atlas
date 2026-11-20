# T3-APPSERVER-EVENT-FAILURE-RECOVERY-032

Status: DONE_SCOPED

## Scope and dependencies

Dependencies: T3-015 durable enqueue receipt, T3-029 worker terminal state, and T3-031 ACP tool executor wiring.

Files:

- `core/atlas/engine/kernel/inbox.py`
- `core/atlas/tools/app_server.py`
- `core/tests/test_kernel_durable_inbox.py`
- `core/tests/test_app_server_sdk_subprocess_attempts.py`
- this batch record, `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`, and atomic queue/capability/interaction-edge ledgers
- temporary per-test child-process instrumentation only, if needed to inject a controlled append error

## Binary acceptance

1. If `inbox.enqueued` persistence fails, the app-server returns an RPC error without a receipt and does not start a provider request.
2. Repeating the same stable request ID after the fault is removed persists and executes exactly one item; no duplicate request or phantom receipt exists.
3. A task-state event append failure cannot be reported as a settled terminal result, silently dropped, or replayed into duplicate work. Status is queued/running/unknown as durable evidence supports.
4. No production fault-injection switch is added. All injected failure state stays in the test-owned process, temp root, and fake provider.

## Implementation and evidence

- Red before the production edit: `test_app_server_event_append_failure_returns_no_receipt_then_retries_once[inbox.enqueued-]` failed with `RuntimeError("Atlas app-server reader failed: Atlas app-server exited: ... test-only SessionDB event append failure")`. The event append exception escaped the `session/enqueue` request handler and terminated the CLI process. No provider request or success receipt was observed, but the same-request retry could not be sent.
- Production change is limited to `core/atlas/tools/app_server.py`: keep `ValueError` as the existing invalid-request response; catch storage/append exceptions from `inject_with_receipt`, return a static JSON-RPC internal error (`enqueue could not be durably recorded`), and continue the request loop. No exception detail is returned and no receipt is sent.
- Exact fault-injection command from `D:\Atlas\core`: `python -m pytest -q -p no:cacheprovider -o addopts= 'tests/test_app_server_sdk_subprocess_attempts.py::test_app_server_event_append_failure_returns_no_receipt_then_retries_once' --tb=short` → `2 passed, 5 warnings in 10.07s`, exit 0. The parameter cases fail `inbox.enqueued` persistence and `appserver.task` queued-state persistence once. In both cases the first call yields `AppServerError`, the provider has zero requests before retry, the same `fault-once` ID succeeds after the injected fault is removed, exactly one inbox enqueue and one provider call are observed, the final durable task state is completed, and the CLI exits naturally with code 0.
- Affected app-server/inbox regression command from `D:\Atlas\core`: `python -m pytest -q -p no:cacheprovider -o addopts= tests/test_app_server_sdk_subprocess_attempts.py tests/test_kernel_durable_inbox.py --tb=short` → `19 passed, 5 warnings in 82.25s`, exit 0.
- `python -m py_compile atlas/tools/app_server.py`, `git diff --check -- atlas/tools/app_server.py tests/test_app_server_sdk_subprocess_attempts.py`, and an AST check locating the new static error branch within async `serve_stdio` all exited 0.
- Tests use an isolated CLI child, temp `sitecustomize.py`, temp SessionDB and loopback FakeLLM. They do not establish live-model, desktop, packaged SDK, or full Task 3 parity.

`DONE_SCOPED`: enqueue event append failure now fails closed without killing the CLI or duplicating work on stable-ID retry. Terminal persistence failures outside the tested queued-state path, restart recovery, other consumers, and full DSH parity remain open.
