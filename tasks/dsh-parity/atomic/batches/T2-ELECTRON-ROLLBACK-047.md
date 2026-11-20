# T2-ELECTRON-ROLLBACK-047 — renderer rollback through the desktop event store

## Scope and dependencies

- Files changed: `frontend/src/renderer/services/runtimeEvents.test.ts`, this batch record, `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`, and the atomic capability/interaction/queue ledgers.
- Dependencies: `T2-CANCELLED-ATTEMPT-043`, `T2-CANCELLED-STREAM-WORKER-045`, and `T2-ACP-CANCEL-046`.
- Binary acceptance: normalize actual runtime envelopes for `run.started → OLD message.delta → message.rollback → NEW message.delta → run.cancelled`; append them through the renderer store; assert the run is cancelled and the rendered `ConversationActivity` contains NEW but not OLD.

## Result

The renderer's existing rollback projection satisfied the new integrated regression; no production change was needed in this atom. Runtime events are consumed by the renderer through `backend-adapter` directly, so this path does not relay through Electron main/preload. The test drives the real envelope normalizer, store `appendEvent`, and `ConversationActivity` render path rather than only calling the text reducer.

## Verification

Command from `D:\Atlas\frontend`:

```text
npm test -- src/renderer/services/runtimeEvents.test.ts src/renderer/components/timelineProjection.test.ts
```

Actual output:

```text
RUN  v5.0.4 D:/Atlas/frontend
Test Files  2 passed (2)
Tests  17 passed (17)
Duration  1.33s
```

One initial fixture run failed because `window` was absent under Vitest's Node environment; stubbing the browser event target in the test fixed the environment requirement. This was not a production failure.

## Limits

This is a renderer integration test, not a launched Electron desktop/window probe. ACP subprocess coverage is in batch 046 and SDK/app-server subprocess coverage in batch 045. No real model was used. Electron packaged startup, a visible interactive window, full cross-consumer combinations, Task 1 source obligations, and superiority remain open; the capability/edge remains `PARTIAL`.
