# T1-TERMINAL-SERVICE-LIFECYCLE-068

Status: DONE_SCOPED (pinned DSH service lifecycle source coverage; Atlas service edge remains OPEN)

## Files and dependencies

- Ledger files: `tasks/dsh-parity/atomic/{semantic-decisions.jsonl,atomic-capabilities.jsonl,interaction-edges.jsonl,batch-queue.jsonl,source-index.json,completion.json}`
- Progress and this report.
- Depends on the 067 terminal API type/consumer map and pinned DSH head `d743267388641bc76f17c45ce8b4c231aed1d32c`.
- DSH files read: `packages/terminal/terminal/{src/index.ts,tests/service.spec.ts,package.json,tsconfig.json,README.i18n.yaml}`. Shared `src/types.ts` was mapped in 067.

## Source decisions

Mapped 329 remaining semantic units across the service registry/runtime, all 17 named service tests, package manifest/build inputs, and localized README fields. Runtime atoms distinguish backend contribution disposal, spawn reservation versus publication, pending-spawn cancellation and rollback, owner identity and session visibility, one active send operation, signal/close/kill, joining in-flight close, registry reload during owner cleanup, idempotent disposal, and aggregated cleanup failures. Test atoms are individual named service cases rather than one package-level claim.

The service contract publishes a session only after backend spawn, fences operations and list output to the exact live owner object, reserves names/concurrency before async provider creation, retains cleanup failures, and does not confuse a send wait result with shell exit. These facts are source-review findings; no DSH tests were run and no Atlas parity is claimed. The interaction edge remains OPEN until an Atlas model-terminal provider uses equivalent trusted owner identity and resource cleanup.

## Verification

Scoped integrity output:

```json
{"pinned_head":"d743267388641bc76f17c45ce8b4c231aed1d32c","files":5,"units":329,"resolved":329,"unresolved":0,"digest_and_refs":"PASS","global_total":413747,"global_unresolved":412380}
```

Focused ledger tests:

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py::test_scan_applies_semantic_decisions_and_rejects_stale_source_digest tests/test_dsh_capability_audit.py::test_scan_rejects_unowned_semantic_decision_references tests/test_dsh_capability_audit.py::test_check_rejects_unresolved_units_dangling_references_and_false_closed --basetemp C:\Users\25011\AppData\Local\Temp\atlas-t1-terminal-service-ledger-068 --tb=short
3 passed, 5 warnings in 2.69s
```

Global source accounting remains `INCOMPLETE` with 412,380 unresolved units. Terminal-bash backend, Atlas implementation, cross-runtime/UI interaction and superiority remain OPEN.
