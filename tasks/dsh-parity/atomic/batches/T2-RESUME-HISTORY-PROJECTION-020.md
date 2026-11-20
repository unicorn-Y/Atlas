# T2-RESUME-HISTORY-PROJECTION-020

## Scope

When a non-ephemeral Kernel request supplies prior history but its canonical SessionDB is empty, seed that history before appending the current user turn. A failed canonical read must not be mistaken for an empty transcript. The seeded transcript remains canonical for subsequent read/replay, and incomplete tool-call history is repaired without replaying the tool action.

Files changed: `core/atlas/engine/kernel/loop.py`, `core/tests/test_c1_recovery.py`, this batch record, `atomic-capabilities.jsonl`, `interaction-edges.jsonl`, `batch-queue.jsonl`, and `BEYOND-DSH-PROGRESS.md`.

## Evidence

Red, before the production fix, from `D:\Atlas\core`:

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_c1_recovery.py::test_resume_repairs_missing_tool_result_and_keeps_completed_history --tb=short
1 failed, 5 warnings in 4.39s
```

The real FakeLLM wire contained the system message and current prompt but omitted the explicitly supplied prior user message. The persisted transcript also lacked that prior user turn.

After the fix, the same node passed:

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_c1_recovery.py::test_resume_repairs_missing_tool_result_and_keeps_completed_history --tb=short
1 passed, 5 warnings in 3.66s
```

The test checks the actual provider request, reopened SessionDB rows, paired tool call/result IDs, `repair_state=unknown`, and that the tool action is not replayed. One assertion was corrected to account for `repair_state` being stored in `display_metadata`; a later isolated run saw a transient SQLite WAL permission error, then the same node and the complete file passed. This transient is retained as an observation, not identified as the root cause.

Full recovery file after the final canonical-read guard:

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_c1_recovery.py --tb=short
7 passed, 5 warnings in 15.36s
```

Combined retry/attempt/history boundary before the final guard:

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_retry_attempt_isolation.py tests/test_atlas_runtime_e2e.py::test_retry_attempt_rollback_is_emitted_by_kernel_before_new_answer tests/test_atlas_runtime_e2e.py::test_kernel_discards_partial_failed_tool_call_before_retry_and_persists_only_new tests/test_atlas_runtime_e2e.py::test_stream_fault_budget_disables_hidden_retry_only_when_opted_in tests/test_atlas_runtime_e2e.py::test_stream_options_compat_retry_is_budgeted_only_when_opted_in tests/test_atlas_runtime_e2e.py::test_stream_options_unrelated_bad_request_does_not_retry tests/test_atlas_runtime_e2e.py::test_auxiliary_complete_transport_retry_obeys_run_budget tests/test_c1_recovery.py --tb=short
17 passed, 5 warnings in 35.15s
```

Static checks after the final guard: `py_compile` passed for `loop.py`, `model_call.py`, `router.py`, `test_c1_recovery.py`, `test_retry_attempt_isolation.py`, and `test_atlas_runtime_e2e.py`. The append call is inside `AtlasKernel.run` and guarded by `canonical_history_read and not canonical_rows and history and not request.ephemeral`; AST parent inspection confirmed the exact branch. JSONL parsing passed for all three batch ledgers (25 batches, 29 capabilities, 19 interaction edges). `git diff --check` exited 0; only existing CRLF normalization notices were printed.

## Status and limits

`DONE_SCOPED`. This closes the fresh non-ephemeral SessionDB seed path and its actual Kernel/FakeLLM replay check only. It does not close the Task 2 attempt/replay matrix: Electron/native desktop, ACP real-kernel stream, app-server/SDK failure and restart combinations, normal max-output continuation, and full installed-runtime consumers remain open. No live model, user state/config/credentials, proxy override, port 8765, or `data/memory/**` was used. No commit/push/reset/stash/clean was performed.
