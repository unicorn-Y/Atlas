# CODEX-ATLAS-P7C-ELECTRON-BACKEND-LIFECYCLE

STATUS: READY  
WORKER: Luna  
BASE_BRANCH: main  
PREDECESSOR: CODEX-ATLAS-P7B-TRUE-STREAMING  
CODE_BASE_HEAD: bfd833a5f26a5cc7b92d960f164b794acc4990ad

## Goal

Make the Electron main process automatically reuse an existing Atlas backend or start one itself before the renderer window is opened.

Do only this stage.

Do **not** modify renderer UI, conversation history, MCP config, API keys, Runtime Protocol, Markdown, settings, packaging, MemoryOS, or other P7/P8 work.

## Current verified state

`frontend/src/main/electron.ts` currently calls `createWindow()` immediately after `app.whenReady()`.

It does not:

- probe `http://127.0.0.1:8765/api/health`;
- start Python/FastAPI;
- wait for backend readiness;
- distinguish an external backend from an Electron-managed backend;
- stop an Electron-managed backend on app exit.

## Required files

Primary:

- `frontend/src/main/electron.ts`
- create `frontend/src/main/backendProcess.ts`

Avoid touching other files unless strictly required.

## Required implementation

### 1. Backend manager module

Create `frontend/src/main/backendProcess.ts`.

Export a small API similar to:

`ensureBackendRunning(): Promise<BackendLaunchResult>`

`stopManagedBackend(): void | Promise<void>`

Result should distinguish at least:

- `ready`
- `managed` (started by this Electron process vs already external)
- optional `pid`

Keep the child-process handle private to this module.

### 2. Health probe

Probe exactly:

`http://127.0.0.1:8765/api/health`

Treat backend as ready only when:

- HTTP status is 200/OK;
- parsed JSON contains `status === "ok"`.

Use a short per-request timeout so a dead service cannot hang startup.

### 3. Reuse an existing backend

Before spawning anything, call the health probe.

If Atlas backend is already healthy:

- return ready;
- mark `managed=false`;
- do not spawn a second process;
- never kill this backend when Electron exits.

### 4. Resolve Atlas repo/core path

Support optional environment override:

`ATLAS_ROOT`

Otherwise derive repo root from the compiled Electron main path.

For the current build layout:

`frontend/dist-electron/main/electron.js`

the repo root can be derived relative to that location.

Build:

`coreDir = <repoRoot>/core`

Validate that:

`core/atlas/server.py`

exists before spawning.

Do not hard-code a user-specific path.

### 5. Python command selection

Priority:

1. `ATLAS_PYTHON` if set;
2. `python`;
3. Windows launcher `py -3`.

Start:

`-m uvicorn atlas.server:app --host 127.0.0.1 --port 8765`

with cwd set to `coreDir`.

If a candidate command is not found (ENOENT), try the next candidate.

If a Python process starts but then exits because Atlas/uvicorn itself failed, surface that failure instead of blindly trying every candidate.

### 6. Spawn behavior

Use Node child_process.

Do not open a console window.

Keep stdout/stderr piped.

Retain only a bounded stderr tail for startup diagnostics; do not accumulate unbounded output in memory.

Pass through existing environment variables.

Do not add or commit secrets.

### 7. Ready gate

After spawn, poll the health endpoint until one of these happens:

- backend becomes healthy -> success;
- child process exits -> fail immediately;
- startup timeout (~15 seconds) -> fail.

Do not use a single fixed sleep as proof of readiness.

### 8. Electron startup order

Change `frontend/src/main/electron.ts` so startup becomes:

`app.whenReady()`
→ `await ensureBackendRunning()`
→ `createWindow()`

The renderer window must not open before the backend readiness gate succeeds.

If backend startup fails:

- show a clear Electron `dialog.showErrorBox` (or equivalent native error dialog) with the startup error;
- quit the app;
- do not silently open the app in Mock mode in this stage.

### 9. Shutdown

Only if this Electron instance started the backend (`managed=true`):

- terminate that process on app quit.

On Windows, terminate the managed process tree by PID (for example via `taskkill /PID <pid> /T /F` or an equivalent targeted mechanism).

Never kill all `python.exe` processes.

If the backend was external (`managed=false`), leave it running.

Avoid double-cleanup races.

## Required verification

### A. Build

Run:

`cd D:\Atlas`
`npm run build`

Must PASS.

### B. External backend reuse smoke test

1. Manually start Atlas backend on 8765.
2. Start Electron.
3. Confirm Electron does not start a second backend.
4. Close Electron.
5. Confirm manually started backend is still alive.

### C. Managed backend smoke test

1. Ensure no Atlas backend is running on 8765.
2. Start Electron.
3. Confirm Electron starts backend automatically.
4. Confirm `GET /api/health` returns healthy while Electron is open.
5. Close Electron.
6. Confirm the Electron-managed backend process is gone.

### D. Startup failure smoke test

Temporarily point `ATLAS_PYTHON` to a nonexistent executable and ensure other fallback candidates are unavailable/disabled for the test, or otherwise induce a safe startup failure.

Confirm:

- a clear native error is shown;
- the normal Atlas window does not open;
- no orphan backend process remains.

Do not commit any local test-only environment changes.

## Scope guard

Do not:

- modify `backend-adapter`;
- disable Mock mode yet;
- change renderer UI;
- implement history loading;
- touch P7B streaming code unless a build break proves it necessary;
- fix the unrelated Windows `test_db_path_absolute` failure;
- modify Runtime Protocol 1.2.

## Git delivery

Before commit:

- `git status --short`
- `git diff --check`
- inspect `git diff`

Commit message:

`feat: manage Atlas backend from Electron`

Push to:

`origin main`

Never force-push.

Verify local HEAD equals remote main HEAD.

## Result file

Create:

`tasks/results/CODEX-ATLAS-P7C-ELECTRON-BACKEND-LIFECYCLE.result.md`

Include:

- RESULT
- BASE_HEAD
- FINAL_HEAD
- REMOTE_HEAD
- CHANGED_FILES
- BUILD_RESULT
- EXTERNAL_BACKEND_REUSE: PASS/FAIL
- MANAGED_BACKEND_START: PASS/FAIL
- MANAGED_BACKEND_STOP: PASS/FAIL
- STARTUP_FAILURE_HANDLING: PASS/FAIL
- KNOWN_ISSUES

Commit and push the result file.

## PASS gate

PASS only if:

1. frontend build passes;
2. an existing healthy backend is reused without spawning another;
3. with no backend running, Electron starts Atlas backend and waits for health before opening the window;
4. Electron stops only the backend process it owns;
5. external backend survives Electron exit;
6. safe startup failure produces a clear error and no normal app window;
7. code + result are committed and pushed;
8. remote main HEAD equals final local HEAD.
