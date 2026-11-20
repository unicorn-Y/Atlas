# T2-CROSS-RUNTIME-CANCEL-050 — isolated server → adapter → renderer cancellation

## Scope and dependencies

- Files changed: `backend-adapter/tests/backend_websocket_cancellation.integration.test.ts`, this record, progress and atomic ledgers.
- Dependencies: T2 batches 045–049.
- Binary acceptance: launch a real isolated Atlas uvicorn process on an OS-selected loopback port and a local scripted OpenAI-compatible SSE endpoint; connect with production `BackendAdapter` native WebSocket, send cancellation only after OLD arrives at its callback, then feed callbacks through renderer normalization/store. Assert OLD delta → matching rollback → cancelled order, final store status cancelled, projection excludes OLD, one model endpoint request, and no request escapes the isolated loopback fixture.

## Result

The integrated cross-runtime path passed. Test roots, backend config, HOME-family directories, and Atlas data are temporary. The fake model endpoint is a local Node HTTP/SSE server. The adapter was not mocked; it connected to the spawned Atlas server's actual `/ws/chat` and `/api` routes. On `rules.trust_required`, the test explicitly trusted only its temporary workspace through the adapter's production `trustRules` method.

## Verification

Command from `D:\Atlas\backend-adapter`:

```text
npx vitest run --root . tests/backend_websocket_cancellation.integration.test.ts --reporter=verbose
```

Actual output:

```text
RUN  v5.0.4 D:/Atlas/backend-adapter
✓ ... > preserves OLD rollback ordering across the actual server, adapter and renderer store 6126ms
Test Files  1 passed (1)
Tests  1 passed (1)
Duration 6.46s
```

Python compile and AST checks passed for `runtime_ws_router.py`, `run_drive.py`, and the isolated WebSocket test. AST confirms the cancellation gate is inside the intended async event loop and explicitly permits `message.rollback`. Targeted `git diff --check` exited 0.

## Limits

The Atlas backend was killed during test cleanup; this is not graceful-lifespan evidence. The renderer projection was exercised, not a launched Electron window or packaged app. The SSE server is a deterministic local fixture, not a real model. Real-model authentication, visible Electron process, other OLDNEW interactions, Task 1 semantic source work, and superiority remain open.
