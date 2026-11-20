# T2-ELECTRON-RETRY-ATTEMPT-038

Status: DONE_SCOPED

## Scope and dependencies

Dependencies: T2-ELECTRON-FALLBACK-ATTEMPT-037 and the existing isolated DropMidStream(after_chars=3) retry fixture.

Files:

- frontend/scripts/dsh-electron-attempt-probe.mjs
- core/scripts/dsh_electron_attempt_backend.py
- this batch record, progress, batch queue, atomic capability and interaction-edge ledgers
- private temporary Electron/Vite/API roots; FakeLLM only

## Binary acceptance

1. The actual renderer receives the emitted OLD prefix before rollback and the complete NEW attempt after rollback; its final visible answer contains NEW and no OLD.
2. The isolated backend receives exactly two retry requests, persists NEW only in the canonical transcript, and records the partial OLD text as a discarded retry audit.
3. Electron, Vite and the helper exit naturally; backend forced termination is explicitly identified, not presented as lifespan success.

## Implementation and evidence

- Root cause of the first probe failure was a harness contract mismatch: retry deliberately uses DropMidStream(..., after_chars=3), but the renderer assertion expected the full OLD answer. It now requires the actual OLD prefix for retry while keeping complete OLD validation for content-filter fallback and complete NEW validation for both scenarios.
- The helper likewise validates the retry audit against the emitted OLD prefix; fallback still requires its complete OLD filtered answer.
- One earlier bounded run failed before model calls with a SessionDB sidecar preflight message for a disappearing state.db-shm. A second run reached the renderer assertion and showed two fake-model requests, so the one preflight observation was not reproduced. No SessionDB production code was changed. A later run reached the durable audit check and exposed the fixture prefix mismatch above.
- Final command from D:\Atlas\frontend: node scripts/dsh-electron-attempt-probe.mjs retry → exit 0 and output status=ui_pass, scenario=retry, visible_new=true, visible_old=false, rollback_seen=true, old_stream_chars=3, new_stream_chars=19, Electron exit 0, Vite exit 0. Private helper receipt: status=pass, fake_request_count=2, models=["fake-model","fake-model"], canonical assistant text=["NEW answer survives"], discarded_old_audit=true, and inner Uvicorn exit 1 after forced cleanup. This does not prove graceful Uvicorn shutdown.
- python -m py_compile scripts/dsh_electron_attempt_backend.py and node --check scripts/dsh-electron-attempt-probe.mjs exited 0. Postflight found no listener on ports 5191 or the dynamic API port and no process command line containing the final private root.
- Honest boundary incident: a one-off diagnostic directly opened the temporary SessionDB by importing Atlas state code without an isolated config root; import logging showed it loaded D:\Atlas\config\atlas.toml. No config values were printed or copied and no write was made, but a real config read occurred. No further such direct import was performed; this deviation is recorded rather than treated as clean isolation.

## Remaining obligations

This is an isolated development-shell Electron retry/fallback contract using FakeLLM, not real-model, packaged-app, graceful-lifespan, or full consumer-matrix evidence. SessionDB preflight race remains unproven after one observation and is not claimed fixed. Max-output continuation, timeout/budget, tool errors, approvals/wait/cancel, restart/replay across UI, all source semantic obligations, and superiority remain open.
