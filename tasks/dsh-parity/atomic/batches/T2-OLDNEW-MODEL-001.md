# T2-OLDNEW-MODEL-001 — isolate final model-call result by attempt

- `batch_id`: `T2-OLDNEW-MODEL-001`
- `atomic_ids`: `ENG-MODEL-RETRY-SUCCESS-ATTEMPT-ONLY`
- `phase`: P1
- `dependencies`: Task 1 source-index schema and initialized atom/queue ledger are available; source semantic sign-off remains open.
- `implementation_dependencies`: none beyond the initialized Task 1 ledger; no frontend/desktop event API is introduced in this sub-batch.
- `verification_dependencies`: existing routed model stream fixture, `httpx.ReadError` retry classification, and deterministic retry sleep control.
- `global_completion_gates`: Task 2 kernel/UI/app-server/SDK/DB reopen/replay attempt contract remains open.

## Files

- Modify `core/atlas/engine/kernel/model_call.py`
- Create `core/tests/test_retry_attempt_isolation.py`
- Modify `tasks/dsh-parity/atomic/atomic-capabilities.jsonl`
- Modify `tasks/dsh-parity/atomic/batch-queue.jsonl`
- Modify `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`
- Create this batch plan before implementation.

## Binary acceptance

1. A stream that emits OLD text and incomplete tool arguments, raises a retryable read error, then returns NEW with a completion marker produces a `ModelCallResult` containing only NEW and no OLD tool call.
2. `on_attempt` records the failed OLD attempt and successful NEW attempt separately; total attempt count is two.
3. Existing duplicate/overlap delta handling, normal complete stream, tool arguments, retry budget, cancellation and output-limit continuation remain unchanged.
4. This sub-batch does not claim the streamed OLD text was withdrawn from consumers. The follow-up Task 2 event-identity batch must implement discard/commit semantics through kernel, desktop, app-server, SDK and DB replay before Task 2 can close.

## Rollback boundary

Only revert this batch's `model_call.py` hunks and its new test/ledger rows. Preserve pre-existing dirty content and all other batches.
