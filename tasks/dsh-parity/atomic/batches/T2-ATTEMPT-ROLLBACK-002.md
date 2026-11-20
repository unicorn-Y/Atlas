# T2-ATTEMPT-ROLLBACK-002 — retract failed streamed attempts from active projections

- `batch_id`: `T2-ATTEMPT-ROLLBACK-002`
- `atomic_ids`: `ENG-MODEL-ATTEMPT-ROLLBACK`, `D-ATTEMPT-AWARE-TIMELINE`, `D-SIDECHAT-ATTEMPT-ROLLBACK`
- `phase`: P1
- `dependencies`: `T2-ATTEMPT-LIFECYCLE-001` event facts.
- `implementation_dependencies`: model events carry stable request `attempt_id`; run-level streaming already preserves incremental chunks.
- `verification_dependencies`: AtlasKernel with loopback FakeLLMServer DropMidStream→Text, event contract, timeline projection replay/incremental tests.
- `global_completion_gates`: durable DB reopen/replay, app-server, SDK, full desktop runtime and real model remain separate open obligations.

## Files

- Modify `core/atlas/engine/kernel/model_call.py`
- Modify `core/atlas/engine/kernel/loop.py`
- Modify `core/atlas/agent/run_phases.py`
- Modify `core/atlas/api/run_drive.py`
- Modify `core/atlas/api/event_names.py`
- Modify `core/tests/test_retry_attempt_isolation.py`
- Modify `core/tests/test_atlas_runtime_e2e.py`
- Read/verify unchanged contract test `core/tests/test_event_contract.py`
- Modify `frontend/src/types/runtime.ts`
- Modify `frontend/src/renderer/services/runtimeEvents.ts`
- Modify `frontend/src/renderer/components/timelineProjection.ts`
- Modify `frontend/src/renderer/components/timelineProjection.test.ts`
- Modify `frontend/src/renderer/App.tsx`
- Modify `frontend/src/renderer/components/SideChat.tsx`
- Modify `frontend/src/renderer/services/runtimeEvents.test.ts`
- Modify atomic capabilities, interaction edges, queue and progress records.

## Binary acceptance

1. Kernel FakeLLMServer `OLD` mid-stream disconnect then `NEW` completion emits stable attempt identity and `message.rollback` before the second attempt's chunks; final result is exactly NEW.
2. Timeline incremental projection may show OLD while attempt 1 is live, but after its rollback it removes only attempt 1 text and tool-preparing rows; replaying the full event history yields the same NEW-only projection.
3. App live-text and SideChat reducers consume rollback without deleting unrelated earlier messages/runs; successful completion remains NEW.
4. Existing retry budgets, cancellation, overlap/streaming behavior and event contract remain valid. This batch does not assert durable rollback semantics in DB/app-server/SDK.

## Rollback boundary

Revert only this batch's rollback event propagation/projection changes and tests. Preserve model attempt-local accumulator isolation and lifecycle events from prior batches.
