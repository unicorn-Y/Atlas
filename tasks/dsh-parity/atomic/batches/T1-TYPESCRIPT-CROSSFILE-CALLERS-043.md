# T1-TYPESCRIPT-CROSSFILE-CALLERS-043

Status: DONE_SCOPED

## Scope and dependencies

Dependencies: T1-TYPESCRIPT-JAVASCRIPT-AST-CONTRACTS-034; pinned TypeScript 6.0.3 in the fixed DSH checkout.

Files:

- core/scripts/dsh_ts_contracts.cjs
- core/scripts/dsh_capability_audit.py
- core/tests/test_dsh_capability_audit.py
- tasks/dsh-parity/atomic/source-index.json
- this batch record, progress, batch queue, atomic capability and interaction-edge ledgers

## Binary acceptance

1. Named import aliases through a barrel re-export resolve to the exact scanned declaration path, qualname and source span.
2. Imported class method calls resolve across files; external imported calls and dynamic imports remain explicit unresolved edges.
3. Repeated fixture indexing is deterministic; caller edges do not silently resolve source semantic obligations.
4. The fixed DSH scan finishes under a bounded runner and records actual cross-file/unresolved counts without closing semantic obligations.

## Implementation and evidence

- Added a multi-file TypeScript fixture covering `execute as launch`, barrel re-export, `new Engine().run()`, external `node:fs/promises` import and dynamic `import()`. The new test first failed on missing cross-file edge, then passed after implementation.
- The extractor now creates a restricted TypeScript Program from the fixed scanned source files. Module resolution is accepted only when the resolved target is in that source set. Resolved signatures link to target function contracts; unresolved external imports and dynamic imports receive explicit resolution labels. Existing same-file edge shapes remain unchanged. Extractor version is 6.
- `node --check core/scripts/dsh_ts_contracts.cjs` → exit 0.
- Red test command: `python -m pytest -q -p no:cacheprovider -o addopts= core/tests/test_dsh_capability_audit.py::test_typescript_cross_file_callers_resolve_barrel_aliases_and_mark_external_imports` → exit 1 as expected; failed because no `cross_file_symbol` edge existed.
- Green focused suite: `python -m pytest -q -p no:cacheprovider -o addopts= core/tests/test_dsh_capability_audit.py` → `20 passed, 5 warnings in 7.32s`, exit 0. Warnings are existing FastAPI/Pydantic deprecations.
- Initial full scan with default Node heap: runner returned `status=FAIL`, returncode 1, `timed_out=false`, duration 85.781s, leftover_count 0. Node exited 134 near its default 4 GB heap (`Ineffective mark-compacts near heap limit`); no index result was produced by that attempt.
- Bounded rerun with `NODE_OPTIONS=--max-old-space-size=8192`: `python core/scripts/dsh_validation_runner.py --cwd D:\Atlas\core --log-dir C:\Users\25011\AppData\Local\Temp\dsh-t1-043-scan-20261118-8g --timeout 600 --cleanup-timeout 5 -- python scripts/dsh_capability_audit.py --source D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness --ledger ../tasks/dsh-parity/atomic --typescript-module D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness/node_modules/typescript/lib/typescript.js --scan` → `{"duration_seconds":342.03199999999197,"leftover_count":0,"returncode":0,"status":"PASS","timed_out":false}`.
- Scan summary from stdout: `{"component_count":369,"file_count":14988,"head":"d743267388641bc76f17c45ce8b4c231aed1d32c","mode":"scan","package_manifest_count":369,"semantic_unit_count":411862,"unresolved_semantic_unit_count":411862}`.
- Generated schema 3 / extractor 6 index is 335,147,220 bytes. Contract edge counts: `cross_file_symbol=48789`, `same_file_unique_name=104543`, `same_file_ambiguous_name=4773`, `unresolved_external_import=169764`, `dynamic_import_unresolved=423`. All 411,862 source semantic units remain unresolved; completion stays INCOMPLETE. The 169,764 unresolved external edges are evidence of an open lane, not proof that every imported API was analyzed.
- The first attempted runner command pointed at `scripts/dsh_validation_runner.py` from the repository root and exited 1 before starting; the corrected `core/scripts/...` command above is the actual scan evidence.

## Remaining obligations

This closes only scanned-source TypeScript/JavaScript cross-file call linking. Config-to-consumer flow, path aliases not resolved by the bounded module resolver, other source languages, Vue, full semantic mapping/review, and all implementation/parity/superiority obligations remain open. No source obligation is marked resolved by this batch.
