# T2-ELECTRON-ATTEMPT-ROLLBACK-022

## Scope

Exercise OLD stream failure → NEW success through the actual Electron main/preload/renderer path against an isolated FastAPI child and loopback FakeLLM. Acceptance is binary: actual window targets strict Vite `127.0.0.1:5191` and a dynamically assigned private API port; Electron renderer reaches health/configuration APIs; a real `/ws/chat` `run.start` is sent; an assistant message shows NEW and no assistant message shows OLD; reopened private SessionDB contains NEW only and discarded OLD remains in `model/attempt` audit; Electron and Vite exit naturally, no own processes/listeners remain.

Files changed for this atom: `frontend/src/main/electron.ts`, `frontend/src/main/electron.lifecycle.test.ts`, `frontend/scripts/dsh-electron-attempt-probe.mjs`, `frontend/scripts/dsh-electron-vite-server.mjs`, `core/scripts/dsh_electron_attempt_backend.py`, and this atom's progress/atomic records. The only production change is a test-mode guard around OS startup integration registration; normal desktop startup remains unchanged. The isolated probe uses the existing actual IPC `requestQuit()` path, not a new production exit hook.

## Failed attempts retained

- Initial private helper failed before ready because its test root collided with the Node runner's temp/profile paths; fixed by isolating a `backend/` subtree.
- Vite CLI readiness parsing initially missed ANSI-colored URL output; later corrected and Vite was moved to a helper using the Vite server API for natural close.
- Early Electron windows reported backend disconnected and emitted no `run.start`; those runs were not accepted. The runner had mismatched `ATLAS_DATA_DIR` and token roots, and an earlier draft also accepted the user's own prompt text as if it were the assistant's NEW answer. The final probe asserts the health/configuration handshake and selects only `[data-message-role="assistant"]` content.
- A later actual UI pass failed while collecting its receipt because the helper imported the wrong `SessionDB` module/path. The audit reader now uses `atlas.engine.state.atlas_state.SessionDB` and the isolated `backend/atlas/engine/state.db`.
- An earlier Electron close timeout used `taskkill` on that run's own tree and is retained as forced cleanup, not graceful evidence. The final run used the application's existing explicit quit IPC and did not require forced cleanup.

## Exact successful commands and observed output

From `D:\Atlas\frontend`:

```text
node --check scripts/dsh-electron-attempt-probe.mjs
exit 0

node scripts/dsh-electron-attempt-probe.mjs
{
  "root": "<private temp root>",
  "vite_url": "http://127.0.0.1:5191",
  "api_url": "http://127.0.0.1:14212",
  "status": "ui_pass",
  "window_url": "http://127.0.0.1:5191/",
  "conversation_id": "92f91dc6-0a8e-465a-abe3-b7ce85f007fe",
  "visible_new": true,
  "visible_old": false,
  "electron_exit_code": 0,
  "electron_cleanup": "window.atlasDesktop.requestQuit → main-process before-quit cleanup",
  "vite_exit_code": 0,
  "vite_cleanup": "close marker → Vite server.close() → helper process exit",
  "backend_exit_code": 0
}
```

The helper's private `receipt.json` for that same run was read back and contained:

```json
{
  "done_seen": true,
  "conversation_id": "92f91dc6-0a8e-465a-abe3-b7ce85f007fe",
  "fake_request_count": 2,
  "assistant_text": ["NEW answer survives"],
  "discarded_old_audit": true,
  "backend_exit_code": 1,
  "backend_cleanup": "IsolatedBackend.close termination (not graceful-lifespan proof)",
  "status": "pass"
}
```

The differing backend exit codes refer to different processes: the Node runner/helper exited 0 after saving its receipt; the isolated Uvicorn backend process was terminated by the existing `IsolatedBackend.close()` fixture and exited 1. This is not natural backend-lifespan evidence. The exact Atlas UI/API/model path did complete before that fixture cleanup.

Other checks from their respective directories:

```text
npx vitest run --root . src/main/electron.lifecycle.test.ts
Test Files  1 passed (1)
Tests       7 passed (7)
exit 0

npm run build
tsc electron + preload build + renderer tsc + Vite production build
✓ built in 4.14s
exit 0

python -m py_compile scripts/dsh_electron_attempt_backend.py
exit 0

git diff --check -- frontend/src/main/electron.ts frontend/src/main/electron.lifecycle.test.ts frontend/scripts/dsh-electron-attempt-probe.mjs frontend/scripts/dsh-electron-vite-server.mjs core/scripts/dsh_electron_attempt_backend.py
exit 0
```

Postflight process/port inspection found no probe, Vite, Electron, Python helper, listener on 5191/private API port, or use of 8765/8871–8876. The isolated FakeLLM server emitted a Windows connection-reset diagnostic during fixture shutdown; it did not affect either model request, transcript, audit, UI result, or helper exit. No user credential/config, real model, proxy/account change, `data/memory/**`, or user service was used.

## Status and limits

`DONE_SCOPED`: actual Electron main/preload/native window and renderer-to-API/WebSocket retry consumer are exercised, with durable transcript/audit and natural Electron/Vite exit. This is a development-shell Electron run, not an installed/packaged application or real-model run. Backend cleanup is forced by the existing test fixture, so graceful backend lifespan is still open. Task 2 remains open for the remaining retry/fallback/tool/timeout/normal-max-output combinations and distribution/consumer obligations. No commit/push/reset/stash/clean.
