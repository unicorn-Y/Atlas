# T1-TERMINAL-PACKAGE-SEMANTICS-066

Status: DONE_SCOPED (all indexed units in the pinned `@deepseek-ai/dsh-tool-terminal` package are explained; Atlas runtime equivalence remains OPEN)

## Files and dependencies

- `tasks/dsh-parity/atomic/semantic-decisions.jsonl`
- `tasks/dsh-parity/atomic/atomic-capabilities.jsonl`
- `tasks/dsh-parity/atomic/interaction-edges.jsonl`
- `tasks/dsh-parity/atomic/batch-queue.jsonl`
- `tasks/dsh-parity/atomic/source-index.json`
- `tasks/dsh-parity/atomic/completion.json`
- This report and `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`
- Depends on the pinned DSH head `d743267388641bc76f17c45ce8b4c231aed1d32c` and the entry/render source reviews 064–065.

## Source decisions

Reviewed the remaining manifest, TypeScript build config, localized README field units, and all three package tests. The 200 `tools.spec.ts` units were bound to the individual schema/lifecycle, validation, presentation, output-bound, policy/error, send-cursor, jobs, cancellation and plugin-shape scenarios. The render tests map to spawn/send/read/list rendering and UTF-8 cap behavior. The loader integration test maps the Cordis composition and persistent shell-state contract. Manifest and `tsconfig` units map to publication/dependency and build-boundary atoms. Localized fields map by exact field path to usage, config/prompt, background/result, and documented-limit topics.

Added 26 source-only behavior atoms plus one open Atlas interaction edge. These are explicitly `PARTIAL`/`OPEN`: a DSH test or document is not evidence that Atlas implements the behavior. The terminal package comprises 11 indexed files and 478 semantic units; all 478 are now bound to exact pinned unit IDs, digests, atom rows and edge references. The three runtime files accounted for in batches 064–065 remain included in that total. Relevant DSH UI/bundle consumers outside this package are not covered by this batch and remain queued.

## Verification

Scoped integrity command output:

```json
{"pinned_head":"d743267388641bc76f17c45ce8b4c231aed1d32c","package_files":11,"package_semantic_units":478,"package_resolved":478,"package_unresolved":0,"unique_decision_ids":568,"source_digest_and_reference_integrity":"PASS","global_semantic_units":413747,"global_unresolved":413179}
```

Focused ledger behavior command:

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py::test_scan_applies_semantic_decisions_and_rejects_stale_source_digest tests/test_dsh_capability_audit.py::test_scan_rejects_unowned_semantic_decision_references tests/test_dsh_capability_audit.py::test_check_rejects_unresolved_units_dangling_references_and_false_closed --basetemp C:\Users\25011\AppData\Local\Temp\atlas-t1-terminal-ledger-066 --tb=short
3 passed, 5 warnings in 2.78s
```

No DSH package test command was run; these tests were statically reviewed as source contracts. Completion remains globally `INCOMPLETE`: 413,179 semantic units remain unresolved, and the Atlas terminal provider, consumer wiring and runtime parity are still open.
