# T2-OLDNEW-CROSS-RUNTIME-101 — Local production-path attempt isolation

Status: `DONE_SCOPED` for the deterministic local OLD → rollback → NEW execution path and its current kernel, app-server/ACP, Python SDK, and renderer consumers. The full Task 2, real-model, packaged/visible desktop, parity, and superiority gates remain open.

## Scope

This batch validated the existing dirty production diff in `model_call.py`, `loop.py`, `run_drive.py`, runtime event normalization, timeline projection, `SideChat`, app-server, and Python SDK. Test-only fixes made in this continuation are limited to `core/tests/test_app_server_sdk_subprocess_attempts.py`, `core/tests/test_app_server_sdk_lifecycle.py`, and `core/tests/test_app_server_acp.py`: correct the workspace expectation, preserve UUID protocol in the fake, avoid lazy-import capture of a test config lambda, and import `time` used by the ACP subprocess helper. No retry permission, model credentials, endpoint, or production permission policy was changed.

## Verification evidence

Kernel attempt and recovery tests:

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_retry_attempt_isolation.py --tb=short --basetemp C:\Users\25011\AppData\Local\Temp\atlas-t2-attempt-kernel-101-red
```

Actual output: `3 passed, 5 warnings in 2.32s`; exit 0.

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_kernel_recovery.py --tb=short --basetemp C:\Users\25011\AppData\Local\Temp\atlas-t2-kernel-recovery-101
```

Actual output: `20 passed, 5 warnings in 2.86s`; exit 0.

Real `AtlasRuntime.run_turn` fixture path:

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_atlas_runtime_e2e.py::test_kernel_discards_partial_failed_tool_call_before_retry_and_persists_only_new --tb=short --basetemp C:\Users\25011\AppData\Local\Temp\atlas-t2-oldnew-runtime-101
```

Actual output: `1 passed, 5 warnings in 8.68s`; exit 0. The test uses a local FakeLLMServer, not a live model. It proves the failed partial tool call did not write its target, OLD is absent from persisted assistant messages after reopening SQLite, the discarded partial remains in attempt audit, NEW is persisted, and max-output continuation completes.

Spawned app-server / ACP consumer suite:

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_app_server_sdk_subprocess_attempts.py tests/test_app_server_sdk_lifecycle.py tests/test_app_server_acp.py --tb=short --basetemp C:\Users\25011\AppData\Local\Temp\atlas-t2-appserver-sdk-102-stable
```

Actual output: `47 passed, 5 warnings in 173.45s`; exit 0. This includes a spawned Atlas CLI app-server process, rollback during retry/approval, successful response selection, DB reopen, and ACP committed-only streaming. Initial attempts failed on test-fixture defects (undefined `selected`, a string UUID double without `.hex`, lazy import retaining a patched config object, and missing `time` import); these failures were preserved during diagnosis and the fixed full run is the evidence used here.

Python SDK tests:

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_app_server.py --tb=short --basetemp C:\Users\25011\AppData\Local\Temp\atlas-t2-python-sdk-102
```

Actual output: `7 passed, 1 warning in 0.03s`; exit 0. Warning: this SDK test project does not register the `unit` marker.

Renderer and wire contract:

```text
node_modules\.bin\vitest.cmd run src/renderer/services/runtimeEvents.test.ts src/renderer/components/timeline.test.ts src/renderer/components/timelineProjection.test.ts src/renderer/components/SideChat.test.tsx --reporter=dot --no-file-parallelism
```

Actual output: `Test Files 4 passed (4); Tests 39 passed (39); Duration 3.15s`; exit 0. Includes normalized `message.rollback`, failed-attempt retraction, successful continuation preservation, and rendered timeline text.

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_event_contract.py --tb=short --basetemp C:\Users\25011\AppData\Local\Temp\atlas-t2-renderer-event-contract-104
```

Actual output: `13 passed, 5 warnings in 2.39s`; exit 0.

```text
node_modules\.bin\tsc.cmd --noEmit -p tsconfig.renderer.json
```

Actual exit code: 0; no diagnostics.

The initial `pnpm exec vitest` attempted an install and exited with `ERR_PNPM_IGNORED_BUILDS`; build scripts were not approved or bypassed. The already installed Vitest binary ran the focused tests directly. The auto-generated `frontend/pnpm-lock.yaml` was verified as created during that command and removed; package manifests and tracked lockfiles have no changes from the install.

## Open obligations

- No live-model call was made in this batch; all model outputs came from deterministic local fixtures.
- No full Electron window / packaged desktop visual session was exercised. Renderer unit output is not visible-desktop proof.
- The broader Task 2 fallback/prompt compatibility and live provider gates remain tracked separately; this report closes only the exercised local attempt isolation slice.
- No parity or superiority claim is made.
