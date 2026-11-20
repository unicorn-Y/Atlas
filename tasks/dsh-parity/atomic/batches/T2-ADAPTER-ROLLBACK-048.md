# T2-ADAPTER-ROLLBACK-048 — production adapter stream to renderer store

## Scope and dependencies

- Files changed: `backend-adapter/tests/client.test.ts`, this record, progress and atomic ledgers.
- Dependencies: batches 045–047 (SDK/app-server cancellation, ACP cancellation, renderer rollback projection).
- Binary acceptance: call production `BackendAdapter.startRun`, open the controlled WebSocket transport, deliver ordered runtime envelopes including OLD delta, same-attempt rollback, NEW delta and cancellation, route each callback through the production renderer normalizer/store append, then assert original sequence/attempt IDs survive, final state is cancelled, and timeline/message projection contains NEW but no OLD.

## Result

The production adapter subscription callback delivered all five envelopes in order and retained OLD/NEW attempt IDs. The renderer store reached `cancelled`; the timeline projection removed OLD and retained NEW. The dedicated UI render assertion is in batch 047; together the batches cover the adapter callback and visible renderer consumer. This is a controlled WebSocket client test, not a live backend or launched Electron process.

## Verification

Command from `D:\Atlas\backend-adapter`:

```text
npx vitest run --root . tests/client.test.ts
```

Actual output:

```text
RUN  v5.0.4 D:/Atlas/backend-adapter
Test Files  1 passed (1)
Tests  24 passed (24)
Duration 348ms
```

An initial `npm run test:adapter` invocation from `frontend` used `--root ..` and therefore discovered 38 copies of the adapter test under worktrees and data staging, producing unrelated failures in those other copies. The precise package-root command above collected only the intended file and passed all 24 tests; the broad invocation is not treated as acceptance evidence.

## Limits

The adapter used a controlled WebSocket, not an actual Atlas WebSocket server. No Electron window/main/preload process was launched and no real model was used. Overall cancellation capability and edge remain `PARTIAL`; production server-to-adapter, packaged desktop, cross-consumer interactions, Task 1 source resolution, and superiority remain open.
