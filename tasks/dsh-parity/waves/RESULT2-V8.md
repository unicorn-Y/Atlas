# WAVE 2 V8 Result — D1, D2, D3, D7

## Delivered

- **D1:** Added OS-assigned loopback port selection before desktop window/backend startup. The selected `ATLAS_PORT` is inherited by the backend and consumed by health checks, preload `apiBaseUrl`, and token header routing. A valid explicit `ATLAS_PORT` remains supported.
- **D2:** Added typed `BackendLifecycleEvent` IPC for `ready`, `fatal`, `shutdown-complete`, and `quit-inspection`. The preload subscription returns a disposer and fetches the latest lifecycle event after subscribing, so startup events sent before renderer listeners attach are recovered.
- **D3:** Kept adjacent `message.delta` folding in a reply node and stopped rebuilding the timeline for known non-projecting run metadata. Structural events still use full `buildTimeline` projection and replay remains event-by-event; D3 therefore remains PARTIAL.
- **D7:** Added a bounded backend event page endpoint carrying header, tail, high-water cursor, and projection baseline. The adapter requests contiguous pages when it detects a sequence gap. A newly attached empty renderer projection starts replay from sequence zero.
- Updated the D1/D2/D3/D7 parity ledger and coverage notes.

## Verification

- Frontend scoped tests: **16 passed** across the port allocator, backend-process lifecycle/startup, and timeline projection tests.
- Backend adapter reconnect tests: **3 passed** (`resumes the same run` and both sequence-gap repair paths).
- Backend event paging unit test: **1 passed** (`@pytest.mark.unit`).
- `npm run build`: **passed**; Electron/preload and renderer TypeScript checks completed with zero TS errors. Existing Vite chunk-size and duplicate static/dynamic import warnings remain.
- Full frontend vitest: **269 passed, 6 failed** across 60 files. Failures are confined to untouched `electron.navigation.test.ts` (2; incomplete Electron mocks), `useAtlasStore.test.ts` (2), and `components/x2/x2.test.tsx` (2). This prevents meeting the wave's full-suite CLOSED gate.
- Full backend-adapter test file: **19 passed, 1 failed**. The unrelated existing `accepts successful empty responses for void backend operations` test calls missing `BackendAdapter.deleteFact`; all three V8 reconnect/page tests pass.
- `git diff --check`: passed.

## Real model run

Started Atlas from this worktree on `127.0.0.1:8838` with `ATLAS_ROOT=D:\Atlas` and `http_proxy`/`https_proxy=http://127.0.0.1:7897` set in the backend launch shell. That configuration resolves the required `deepseek-v4.1-flash` model and `https://d1api.xin/v1` base URL; the credential remained in the Windows credential store.

Command:

```powershell
python scripts/dsh_live_ws_check.py 8838 "Reply with exactly the word: OK"
```

Observed output:

```text
[terminal] run.completed data={"result": "completed", "model": "deepseek-v4.1-flash", ...}
[reply] 'OK'
[result] terminal=run.completed chars=2
```

The test backend was stopped after the run. No credential values were printed or added to files.

## Row status

- D1: PARTIAL — port assignment/injection is implemented and tested; full frontend vitest is not green.
- D2: PARTIAL — typed lifecycle IPC is wired and type-checked; full frontend vitest is not green.
- D3: PARTIAL — delta and non-projecting metadata paths are incremental; structural projection and compressed replay remain.
- D7: PARTIAL — page-based gap repair and empty-projection replay are implemented and tested; full frontend vitest is not green.

All touched directories were included; remaining PARTIAL states reflect the recorded behavior gaps or the wave's explicit validation gate.
