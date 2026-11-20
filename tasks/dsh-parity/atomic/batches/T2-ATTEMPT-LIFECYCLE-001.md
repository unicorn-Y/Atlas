# T2-ATTEMPT-LIFECYCLE-001 — model attempt lifecycle facts

- `batch_id`: `T2-ATTEMPT-LIFECYCLE-001`
- `atomic_ids`: `ENG-MODEL-RETRY-SUCCESS-ATTEMPT-ONLY`, `ENG-MODEL-ATTEMPT-LIFECYCLE`
- `phase`: P1
- `dependencies`: `T1-DSH-SOURCE-001` audit substrate and the OLD→NEW final-result red/green fixture.
- `implementation_dependencies`: existing `complete_stream(on_event=...)` internal callback.
- `verification_dependencies`: retryable `httpx.ReadError`, deterministic retry delay, exact lifecycle event order.
- `global_completion_gates`: Task 2 UI rollback, durable event replay, app-server, SDK and desktop consumption remain open.

## Files

- Modify `core/atlas/engine/kernel/model_call.py`
- Modify `core/tests/test_retry_attempt_isolation.py`
- Modify `tasks/dsh-parity/atomic/atomic-capabilities.jsonl`
- Modify `tasks/dsh-parity/atomic/interaction-edges.jsonl`
- Modify `tasks/dsh-parity/atomic/batch-queue.jsonl`
- Modify `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`
- Create this batch plan.

## Binary acceptance

1. Retry OLD→NEW emits `attempt_started(1)`, `attempt_discarded(1)`, `attempt_started(2)`, `attempt_committed(2)` in this order.
2. Successful `ModelCallResult` remains only NEW, and failed attempt tool fragments remain absent from the successful result.
3. Adjacent streaming delta overlap and tool argument regressions pass.
4. This batch does not claim that downstream UI, event replay, app-server or SDK hides/retracts OLD; those remain queued Task 2 obligations.

## Rollback boundary

Revert only lifecycle event additions in `model_call.py`, their assertions, and this batch's ledger/progress rows. Preserve prior attempt-local result isolation and unrelated pre-existing dirty changes.
