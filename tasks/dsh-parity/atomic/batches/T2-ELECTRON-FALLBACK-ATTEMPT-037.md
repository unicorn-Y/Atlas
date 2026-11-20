# T2-ELECTRON-FALLBACK-ATTEMPT-037

Status: DONE_SCOPED

## Scope and dependencies

Dependencies: T2-API-WS-FALLBACK-ATTEMPT-036, existing Electron attempt rollback surface, isolated IsolatedBackend, private Vite runner on port 5191.

Files:

- core/tests/test_c1_websocket_acceptance.py
- core/scripts/dsh_electron_attempt_backend.py
- frontend/scripts/dsh-electron-attempt-probe.mjs
- this batch record, progress, batch queue, atomic capability and interaction-edge ledgers
- isolated temporary Atlas data root and dynamic loopback API; FakeLLM only

## Binary acceptance

1. Actual Electron renderer sends one run through the isolated API; primary fake-model content-filter attempt rolls back before configured fallback-model commits.
2. Renderer receives OLD → rollback → NEW attempt frames; final visible assistant content contains NEW and excludes OLD.
3. Temporary SessionDB canonical transcript contains NEW only and retains the primary OLD attempt as discarded audit.
4. Electron and Vite close normally; backend cleanup is reported separately and is not called graceful lifespan evidence.

## Implementation and evidence

- Extended the isolated desktop backend helper for retry/fallback scenarios, and added renderer-frame capture plus final visible-message assertions to the existing temporary Electron probe. The fallback OLD response is completed with finish_reason=content_filter, so the whole old answer is expected in the discarded-attempt audit.
- Command from D:\Atlas\frontend: node scripts/dsh-electron-attempt-probe.mjs fallback → outer status=ui_pass, scenario=fallback, visible_new=true, visible_old=false, rollback_seen=true, old_stream_chars=19, new_stream_chars=19, Electron exit 0, Vite exit 0, backend helper exit 0. The private receipt reports fake requests fake-model → fallback-model, canonical assistant text NEW fallback answer, and discarded OLD audit true.
- The private receipt records the Uvicorn child cleanup as IsolatedBackend.close termination, inner Uvicorn return code 1. This is not normal lifespan shutdown proof. The test is actual Electron renderer interaction against local isolated services, not a packaged production build or real model run.
- The first script revision had a syntax error; it was corrected before the successful probe. No product defect is inferred from that harness error.
- No live model, 8765, user config/credentials, data/memory/**, or persistent user data were used. See the retry follow-up batch for a later one-time diagnostic config-import deviation.

## Remaining obligations

Fallback via the development Electron shell is one consumer-path result only. Packaged Electron, graceful backend lifespan, real-model behavior, retry/max-output/timeout/budget/tool-error matrices, source-wide semantic coverage, and same-condition superiority remain open.
