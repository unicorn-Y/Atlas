# T2-ACP-CANCEL-046 — ACP subprocess cancellation and discarded attempt isolation

## Scope and dependencies

- Files changed: `core/tests/fakes/fake_llm_provider.py`, `core/tests/test_app_server_acp.py`, this batch record, `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`, and the atomic capability/interaction/queue ledgers.
- Dependencies: `T2-CANCELLED-STREAM-WORKER-045` and `T2-ACP-KERNEL-ATTEMPT-STREAM-021`.
- Binary acceptance: an actual `python -m atlas.cli acp` subprocess must accept initialize/new/prompt/cancel, consume partial OLD text before cancellation, return `stopReason=cancelled`, emit no ACP `session/update` containing OLD, naturally exit 0 after stdin EOF, issue one loopback provider request, and after reopening its private SessionDB retain discarded/cancelled OLD audit while canonical assistant history excludes OLD.

## Implementation

- Added an optional `text_chunk_sent` event to the loopback `StallMidStream` fixture. The event is set only after the fake provider flushes the partial SSE chunk.
- Added a subprocess ACP JSON-RPC regression. A short bounded scheduler handoff follows the fixture flush; the persisted non-empty OLD `partial_text` audit is the authoritative evidence that the runtime consumed the chunk before cancellation. The test does not infer consumption from provider-side write alone.
- The test uses the existing isolated temporary data/config environment and a cached public tokenizer asset. It does not contact a real model or touch user data/configuration.

## Verification

Command from `D:\Atlas\core`:

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_app_server_acp.py::test_real_acp_subprocess_cancel_discards_partial_attempt_and_persists_audit --tb=short
```

Actual output:

```text
2026-11-18 05:49:41 [info     ] config.loaded path=C:\Users\25011\AppData\Local\Temp\atlas-tests-cas1g5tf\atlas\config\atlas.toml
.                                                                        [100%]
============================== warnings summary ==============================
... 5 existing deprecation warnings (FastAPI on_event and Pydantic class Config)
1 passed, 5 warnings in 5.76s
```

The test asserts subprocess exit code 0 before fixture cleanup, one fake-provider request, ACP cancel acknowledgement and cancelled prompt result, absence of OLD in all ACP session updates and reopened canonical assistant messages, plus a persisted `model/attempt` event with `status=discarded`, `category=cancelled`, and `partial_text` beginning with OLD.

## Limits

This closes the scoped ACP loopback subprocess path only. The test uses a fixture provider, not a real model. Packaged Electron main/preload/renderer visible rollback, remaining cross-consumer wait/approval/timeout/tool-error combinations, Task 1 source obligations, and superiority remain open. Overall capability and interaction edge remain `PARTIAL`.
