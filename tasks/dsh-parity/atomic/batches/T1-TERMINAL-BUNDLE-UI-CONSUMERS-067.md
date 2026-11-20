# T1-TERMINAL-BUNDLE-UI-CONSUMERS-067

Status: DONE_SCOPED (pinned bundle/API/UI consumer source coverage; Atlas interaction edge remains OPEN)

## Files and dependencies

- Ledger files: `tasks/dsh-parity/atomic/{semantic-decisions.jsonl,atomic-capabilities.jsonl,interaction-edges.jsonl,batch-queue.jsonl,source-index.json,completion.json}`
- Progress and this report.
- Depends on `T1-TERMINAL-PACKAGE-SEMANTICS-066` and fixed DSH head `d743267388641bc76f17c45ce8b4c231aed1d32c`.
- Fixed-source files reviewed: `packages/experimental/terminal-bundle/{package.json,src/index.ts,cordis.patch.yml,locale/en.json,locale/zh.json,README.i18n.yaml,tsconfig.json}`; `packages/terminal/terminal/src/types.ts`; `packages/client/ui-tool/src/client/tool/models/{terminal-card-model.ts,tool-call-model.ts}`; `packages/client/ui-tool/src/client/tool/toolviews/details-row.tsx`; `packages/client/ui-tool/tests/terminal-card.client.spec.tsx`; `packages/core/tools/tests/gen-tool-catalog.spec.ts`.

## Source decisions

Mapped all 470 indexed semantic units in the 13 files to concrete activation, backend API type, generated catalog, UI-model/render consumer, or named test-contract atoms. This records the producer-consumer path: bundle/Cordis patch → terminal provider API → six registered tools and generated schemas → client tool-call model → terminal card/details renderer. The terminal DTO contract includes setup/cleanup failure, branded owner-scoped session identity, wait reason separate from top-level status, incremental send/cancel, bounded scrollback pages, allowed signals and backend lifecycle. UI tests separately cover cwd resolution, persistent shell state markers, standard shell and pwsh, PTC children, status/result formatting, malformed/background calls, long output, and generic fallback. Catalog tests cover package discovery/manifest completeness/schema harvesting and package attribution.

All records are source-only. The DSH package tests were not executed, and none of these source mappings assert Atlas behavior. The full Atlas producer-to-renderer interaction remains OPEN; Atlas's existing interactive WebSocket is not counted as the persistent model-facing terminal API.

## Verification

Scoped integrity output:

```json
{"pinned_head":"d743267388641bc76f17c45ce8b4c231aed1d32c","files":13,"semantic_units":470,"resolved":470,"unresolved":0,"source_digest_atom_edge_integrity":"PASS","global_total":413747,"global_unresolved":412709}
```

Focused ledger behavior command:

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py::test_scan_applies_semantic_decisions_and_rejects_stale_source_digest tests/test_dsh_capability_audit.py::test_scan_rejects_unowned_semantic_decision_references tests/test_dsh_capability_audit.py::test_check_rejects_unresolved_units_dangling_references_and_false_closed --basetemp C:\Users\25011\AppData\Local\Temp\atlas-t1-terminal-ui-ledger-067 --tb=short
3 passed, 5 warnings in 2.80s
```

Task 1 remains globally `INCOMPLETE`: 412,709 source semantic units remain unresolved. Terminal backend implementation, remaining DSH terminal service and desktop protocol consumers, Atlas wiring and superiority evidence remain open.
