# T2-SDK-PROMPT-CALLBACK-DRAIN-063

Status: DONE_SCOPED (one OLDNEW SDK callback-failure path is fixed and verified; Task 2 remains open)

## Files and dependencies

- `sdk/python/atlas_sdk/app_server.py`: cancel a running prompt when the `answer`, `approve`, or event callback raises; drain the actual `session/wait` barrier before returning the callback error or exposing the session for reuse.
- `core/tests/test_app_server_sdk_subprocess_attempts.py`: real CLI app-server subprocess regression for OLD partial output, retry rollback, `ask_user` wait, callback exception, cancellation, same-session reuse, and reopened SessionDB.
- `tasks/dsh-parity/atomic/atomic-capabilities.jsonl`, `interaction-edges.jsonl`, `batch-queue.jsonl`, this report, and progress.
- Dependency: existing isolated FakeLLMServer and CLI app-server harness; no external provider or account.

## Root cause and behavior

The SDK invoked user-provided callbacks inline while servicing the session prompt notification queue. If a callback raised, `prompt()` exited and removed its notification consumer without cancelling or waiting for the app-server run. The run remained active in `ask_user`, so the next prompt on that session failed with `session already has an active run`.

The SDK now sends `session/cancel` for the active session, keeps draining the original prompt until its response, then calls the server's `session/wait` settle barrier before re-raising the original callback exception. Approval callback failures remain fail-closed; no approval or input value is fabricated after the callback throws.

## Red/green evidence

The first valid red used an actual SDK client and `python -m atlas.cli` subprocess. After the callback exception, the immediate next prompt failed with `AppServerError: session already has an active run` (`1 failed, 5 warnings in 11.64s`). An earlier attempt used the wrong `ask_user` argument name and never invoked the callback; that was a fixture error, not product evidence.

Final explicit collection from `D:\Atlas\core`:

```text
python -m pytest --collect-only -q -p no:cacheprovider -o addopts= tests/test_app_server_sdk_subprocess_attempts.py::test_sdk_prompt_callback_failure_cancels_rolled_back_run_before_reusing_session
```

Output: `1 test collected in 0.43s`.

Final focused command:

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_app_server_sdk_subprocess_attempts.py::test_sdk_prompt_callback_failure_cancels_rolled_back_run_before_reusing_session --basetemp C:\Users\25011\AppData\Local\Temp\atlas-t2-sdk-callback-cancel-062-final2 --tb=short
```

Output: `1 passed, 5 warnings in 12.66s`, exit 0. The regression observed the cancellation event, reused the same session for a second completed prompt, reopened the isolated SessionDB, verified the canonical transcript excludes OLD and contains the recovery response, and verified the discarded attempt audit preserves the actual OLD partial text. The CLI app-server process exited naturally with code 0.

Existing SDK behavior checks:

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_app_server.py::test_concurrent_session_prompts_route_interleaved_responses_and_events tests/test_app_server.py::test_prompt_keeps_rollback_event_and_returns_only_committed_attempt tests/test_app_server.py::test_sdk_wait_uses_session_settle_barrier --tb=short
```

Output: `3 passed, 1 warning in 0.04s`, exit 0. The warning is an unregistered `pytest.mark.unit` warning when running from the SDK package without the core pytest configuration.

`py_compile`, AST parse plus settle-barrier ownership check, and targeted `git diff --check` all exited 0.

## Limits

This is local fixture-provider evidence through the real CLI app-server subprocess and Python SDK. It is not live-model, visible Electron, packaged-desktop, or global OLDNEW completion evidence. Other SDK callback, transport disconnect, reconnect, and cross-runtime interactions remain open.

