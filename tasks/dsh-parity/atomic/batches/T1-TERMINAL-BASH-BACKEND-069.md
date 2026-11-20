# T1-TERMINAL-BASH-BACKEND-069

Status: DONE_SCOPED (all indexed terminal-bash package semantics accounted; Atlas backend parity remains OPEN)

## Files and dependencies

- Ledger: `tasks/dsh-parity/atomic/{semantic-decisions.jsonl,atomic-capabilities.jsonl,interaction-edges.jsonl,batch-queue.jsonl,source-index.json,completion.json}`
- Progress and this report.
- Depends on 067 shared terminal provider types, 068 terminal service lifecycle, and pinned DSH head `d743267388641bc76f17c45ce8b4c231aed1d32c`.
- DSH package files: manifest/docs/localized fields/build config; `src/{config,index,sanitize,session}.ts`; and all six config/backend/local/sanitizer/session-buffer/session test files (14 indexed files total).

## Source decisions

Mapped all 1,346 indexed units. The 105 named test cases were given individual behavior atoms. Runtime mapping separates shell dialect/default/validation, backend registration and startup rollback, sandbox fencing and environment scrubbing, shell prompt bootstrap, split control-sequence/prompt sanitation, bounded UTF-8 scrollback/operation output, asynchronous readiness/foreground inspection, send cancellation ownership, verified-group signaling, close/retry behavior and localized config documentation.

The DSH tests describe nuanced state constraints: a send timeout or inferred idle does not establish top-level shell exit; cancellation retains operation ownership until async provider writes/signals settle; owner cleanup and startup rollback must not publish false success; read and byte limits are separate; sandbox policy wraps exact argv and does not silently bypass missing provider. These are source requirements. No DSH test was executed and no Atlas parity is claimed. POSIX confinement remains a separate runtime/lane obligation.

## Verification

Scoped integrity output:

```json
{"pinned_head":"d743267388641bc76f17c45ce8b4c231aed1d32c","files":14,"semantic_units":1346,"resolved":1346,"unresolved":0,"all_file_digests_and_atom_edge_refs":"PASS","global_total":413747,"global_unresolved":411034}
```

Focused ledger tests:

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py::test_scan_applies_semantic_decisions_and_rejects_stale_source_digest tests/test_dsh_capability_audit.py::test_scan_rejects_unowned_semantic_decision_references tests/test_dsh_capability_audit.py::test_check_rejects_unresolved_units_dangling_references_and_false_closed --basetemp C:\Users\25011\AppData\Local\Temp\atlas-t1-terminal-bash-ledger-069 --tb=short
3 passed, 5 warnings in 2.68s
```

Global source accounting remains incomplete with 411,034 unresolved units. The next implementation atom is an Atlas local owner-scoped terminal provider through real PTY/process ownership. It must preserve fail-closed behavior where the platform/backend cannot provide the requested contract; this source review does not close the POSIX sandbox lane.
