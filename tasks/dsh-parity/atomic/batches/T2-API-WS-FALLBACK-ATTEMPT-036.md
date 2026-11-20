# T2-API-WS-FALLBACK-ATTEMPT-036

Status: DONE_SCOPED

## Scope and dependencies

Dependencies: T2-FALLBACK-ATTEMPT-ISOLATION-034, existing T2-API-ATTEMPT-PERSISTENCE-003/005 and the isolated C1 Uvicorn `/ws/chat` fixture.

Files:

- `core/tests/test_c1_websocket_acceptance.py`
- this batch record, progress, batch queue, atomic capability and interaction-edge ledgers
- temporary API data root, dynamic loopback backend port, FakeLLM only

## Binary acceptance

1. The production `/ws/chat` backend receives primary then configured fallback model requests after the primary content-filter attempt.
2. OLD deltas are tagged with the discarded attempt ID and precede `message.rollback`; NEW deltas follow rollback with another attempt ID.
3. `message.completed`, canonical SessionDB transcript and discarded attempt audit agree: NEW only in canonical result, OLD retained as discarded audit.

## Implementation and evidence

- Extended the isolated backend fixture with an optional `fallback-model` while preserving existing single-model defaults; added `fallback_backend` with bounded retry settings.
- Added `test_websocket_fallback_rolls_back_primary_and_persists_only_fallback`, which starts actual `uvicorn atlas.server:app` on a random loopback port (asserted not 8765), drives `/ws/chat`, checks exact FakeLLM request models `fake-model`, `fallback-model`, checks ordered attempt-tagged deltas/rollback, and opens the temporary SessionDB to confirm NEW-only assistant transcript plus OLD discarded audit.
- New test alone: **1 passed, 5 warnings in 11.55s**, exit 0. Existing rollback plus fallback pair: **2 passed, 5 warnings in 23.67s**, exit 0. Warnings are existing FastAPI/Pydantic deprecations. `py_compile` and targeted `git diff --check` exited 0.
- The C1 fixture uses dynamic isolated backend/data paths but its current close helper terminates the uvicorn child; this evidence is not graceful-lifespan/shutdown evidence. No live model or Electron UI was used. The API process does not restart in this test; SDK process-restart replay is covered separately by T2-035. Packaged desktop, live model, all retry matrices and superiority remain open.
