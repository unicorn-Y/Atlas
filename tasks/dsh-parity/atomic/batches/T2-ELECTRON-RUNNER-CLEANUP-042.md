# T2-ELECTRON-RUNNER-CLEANUP-042

Status: DONE_SCOPED

## Scope and dependencies

Dependencies: T2-ELECTRON-MAXOUTPUT-AFTER-RETRY-041 failed cleanup evidence and actual Electron requestQuit/main-process behavior.

Files:

- frontend/scripts/dsh-electron-attempt-probe.mjs
- this batch record, progress, batch queue, atomic capability and interaction-edge ledgers
- private temporary Electron/Vite/API roots, FakeLLM only

## Binary acceptance

1. Probe waits for both visible successful output and the corresponding run.completed result=completed before requesting quit.
2. Electron process handle/PID is captured at launch; requestQuit and process exit use one absolute deadline; owned-tree fallback and Vite/backend helper waits are bounded.
3. Any forced cleanup turns overall status into error/nonzero while continuing cleanup of other owned processes.
4. One max-output probe after the change exits naturally: Electron=0, Vite=0, backend helper=0, no process/port leftovers.

## Implementation and evidence

- Captured renderer page and Electron child process handle/PID at launch; cleanup no longer calls app.process() after Playwright disconnect. Added a shared deadline helper around requestQuit/process exit and bounded taskkill waits for exact captured owned PIDs. Forced Electron/Vite/backend cleanup always marks final status error; cleanup then proceeds to the remaining owned service.
- During investigation, source inspection showed Electron requestExplicitQuit opens a confirmation when the renderer's activity summary says a task is still running. The prior probe waited only for visible text fragments and could request quit before the run.completed terminal frame. This is a supported race hypothesis, not a directly observed dialog. Probe now requires visible fragments plus run.completed/result=completed and fails explicitly on failed/cancelled terminal events.
- Syntax: node --check scripts/dsh-electron-attempt-probe.mjs exit 0. Related Python helper py_compile exit 0.
- Final actual command from D:\Atlas\frontend: node scripts/dsh-electron-attempt-probe.mjs max-output → exit 0; output status=ui_pass, scenario=max-output, visible_new=true, visible_old=false, rollback_seen=true, run_terminal_event=run.completed, run_result=completed, old_stream_chars=3, new_stream_chars=32, electron_exit_code=0, vite_exit_code=0, backend_exit_code=0.
- Private receipt: status=pass, fake_request_count=3, models all fake-model, assistant_text=[NEW answer, continuation completed], discarded_old_audit=true. The Uvicorn child was still force-terminated by the isolated helper (inner exit 1); this is not graceful API lifespan evidence.
- Postflight: no listener on 5191 or dynamic API port 2265 and no process containing the private root. The earlier 041 failure and owned-tree forced cleanup remain recorded in its history; the rerun is separate evidence.

## Remaining obligations

This closes only the Electron development-shell max-output/rollback combination. Packaged Electron, real model, normal backend lifespan, other retry/timeout/budget/tool-error/wait/cancel/approval combinations, Task 1 source obligations and superiority remain open.
