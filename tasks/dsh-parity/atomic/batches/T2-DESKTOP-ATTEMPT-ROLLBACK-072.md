# T2-DESKTOP-ATTEMPT-ROLLBACK-072

Status: `DONE_SCOPED` for renderer event normalization, timeline projection/replay, and SideChat component consumption. The full desktop OLD→NEW gate remains open.

## Scope

- Verified the existing production consumers `frontend/src/renderer/services/runtimeEvents.ts`, `frontend/src/renderer/components/timelineProjection.ts`, `frontend/src/renderer/components/timeline.ts`, and `frontend/src/renderer/components/SideChat.tsx`.
- Added `frontend/src/renderer/components/SideChat.test.tsx`, which mounts the actual SideChat component with the existing React test renderer, captures its `backend.startRun` callback, and injects OLD delta → matching rollback → NEW delta.
- Existing focused tests already covered attempt-aware runtime normalization/reduction and incremental plus replayed timeline projections. No production code change was needed in this verification batch.

## Acceptance and evidence

The mounted SideChat test asserts OLD is visible after its delta, disappears after rollback, and NEW becomes visible without OLD reappearing.

Exact command from `D:\Atlas\frontend`:

```text
npx vitest run src/renderer/services/runtimeEvents.test.ts src/renderer/components/timelineProjection.test.ts src/renderer/components/SideChat.test.tsx
Test Files  3 passed (3)
Tests       18 passed (18)
Duration    1.35s
```

Exact type check from `D:\Atlas\frontend`:

```text
npx tsc --noEmit -p tsconfig.renderer.json
exit 0
```

The event tests are local renderer tests; there was no Electron window, real API backend, or model-provider run. This does not close desktop packaged/runtime replay, reconnect, other attempt states (approval/input/normal max-output continuation), or Task 2 superiority gates.
