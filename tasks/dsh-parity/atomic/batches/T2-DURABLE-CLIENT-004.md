# T2-DURABLE-CLIENT-004 — durable attempt audit and app-server client results

- `batch_id`: `T2-DURABLE-CLIENT-004`
- `atomic_ids`: `ENG-MODEL-ATTEMPT-AUDIT-DURABLE`, `ENG-APP-SERVER-ATTEMPT-RESULT`, `ENG-ACP-ATTEMPT-COMMIT`, `SDK-ATTEMPT-ROLLBACK-DELIVERY`
- `phase`: P1
- `dependencies`: `T2-ATTEMPT-ROLLBACK-002`; model lifecycle facts and `message.rollback` are wired through AtlasKernel.
- `implementation_dependencies`: kernel canonical transcript persistence and existing `session_sync.append_session_event`; app-server `session/event` notification; SDK per-session notification queue.
- `verification_dependencies`: FakeLLMServer OLD disconnect→NEW, reopen `SessionDB`, JSON-RPC app-server lifecycle fixture, ACP queue protocol fixture, SDK protocol subprocess fixture.
- `global_completion_gates`: actual CLI process invocation, API WebSocket/browser desktop, and live model remain separate gates.

## Files

- Modify `core/atlas/engine/kernel/model_call.py`
- Modify `core/atlas/engine/kernel/loop.py`
- Modify `core/atlas/tools/app_server.py`
- Modify `core/tests/test_atlas_runtime_e2e.py`
- Modify `core/tests/test_app_server_sdk_lifecycle.py`
- Modify `core/tests/test_app_server_acp.py`
- Modify `sdk/python/tests/test_app_server.py`
- Read/verify `sdk/python/atlas_sdk/app_server.py` behavior; edit only if a failing contract test identifies a gap.
- Modify Task2 atomic capability, interaction-edge, batch-queue and progress records.

## Binary acceptance

1. After an OLD→NEW kernel run, a newly-opened SessionDB transcript has only NEW as the assistant response; a separate durable `model/attempt` event records OLD's failed/discarded attempt and its identity/category.
2. App-server JSON-RPC `session/prompt` result text is NEW, not OLDNEW, while `session/event` still delivers the rollback in order.
3. ACP does not emit discarded attempt chunks. The committed NEW text is emitted through `session/update`, and final prompt status is successful.
4. Python SDK routes the rollback event to the correct session callback and returns the server's NEW final result.
5. Existing cancel/approval/input protocol tests continue to pass. No credentials, external model or network endpoint are used.

## Rollback boundary

Revert only durable model-attempt event and client result filtering changes introduced by this batch and its test/ledger rows. Keep Task2 kernel/UI rollback work intact.

## Implementation record

- `core/atlas/engine/kernel/model_call.py` now includes the actually streamed partial text on `attempt_discarded` lifecycle facts.
- `core/atlas/engine/kernel/loop.py` persists discarded and committed attempt facts as `model/attempt` SessionDB events for non-ephemeral sessions. A failed audit write emits a recovery notice and log entry. The kernel also emits an internal `model_attempt_committed` event for client protocols.
- `core/atlas/tools/app_server.py` buffers attempt-tagged chunks until commit, removes discarded buffers on rollback, and returns only committed text. ACP publishes attempt-tagged text only after commit; untagged legacy chunks keep their existing behavior.
- `sdk/python/atlas_sdk/app_server.py` was inspected and needed no production change: the existing per-session notification queue routes rollback correctly. Its protocol test now covers OLD → rollback → NEW and the final result.
- Stable command from `D:\Atlas\core`:
  ` $env:PYTHONPATH='D:\Atlas\sdk\python'; python -m pytest -q -p no:cacheprovider -o addopts= tests/test_app_server_sdk_lifecycle.py tests/test_app_server_acp.py tests/test_atlas_runtime_e2e.py::test_retry_attempt_rollback_is_emitted_by_kernel_before_new_answer ../sdk/python/tests/test_app_server.py --tb=short `
  Output: `20 passed, 5 warnings in 9.31s`, exit code 0. The kernel test reopens SessionDB and verifies transcript `NEW` plus a separate discarded-attempt audit row containing the received `OLD` prefix. JSON-RPC, ACP, and SDK tests use local protocol fixtures; no external model, credentials, or network endpoint.
- Red evidence: ACP initially emitted `['OLD', 'NEW']` instead of `['NEW']`; the app-server JSON-RPC contract previously returned `OLDNEW`; the new ACP red test reproduced the first leak. The SDK protocol node passed because its existing per-session routing already preserved order and result.
- Batch remains PARTIAL: the local deterministic protocol and persistence contracts pass; actual CLI subprocess, API WebSocket, desktop runtime, and external-model gates remain separate and are not claimed here.
