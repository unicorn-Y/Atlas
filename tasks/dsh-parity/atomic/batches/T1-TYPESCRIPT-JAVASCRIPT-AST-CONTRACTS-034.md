# T1-TYPESCRIPT-JAVASCRIPT-AST-CONTRACTS-034

Status: DONE_SCOPED

## Scope and dependencies

Dependencies: T1-METHOD-CONFIG-CONTRACTS-033 schema v2 and the pinned DSH checkout `d743267388641bc76f17c45ce8b4c231aed1d32c`.

Files:

- `core/scripts/dsh_capability_audit.py`
- `core/scripts/dsh_ts_contracts.cjs`
- `core/tests/test_dsh_capability_audit.py`
- regenerated `tasks/dsh-parity/atomic/source-index.json` and `completion.json`
- atomic capability, interaction-edge, batch-queue, and progress ledgers

## Binary acceptance

1. TypeScript and JavaScript AST contracts capture function/method/arrow source spans, async state, parameter-default digests, catch/throw, platform branches, state assignments, and same-file uniquely resolved caller edges.
2. Missing compiler and syntax diagnostics remain explicit UNRESOLVED rows; no parser omission is treated as complete.
3. A pinned full-source scan emits reproducible counts, source hash, parser-diagnostic count, and all semantic items remain fail-closed until reviewed and mapped.

## Implementation and evidence

- Extractor is v5/index schema v3. TypeScript compiler invocation is explicit via `--typescript-module`, or resolved from `ATLAS_DSH_TYPESCRIPT_MODULE` / the source checkout. If unavailable, each TS/JS file gets a `typescript_parser_unavailable` unresolved row. TypeScript syntax diagnostics likewise become unresolved units.
- AST contracts include function declarations, methods/accessors/constructors, function expressions and arrows; source lines; default digests only; catch/throw facts; platform-condition digests; `state`/`status`/`phase` assignments; and same-file call-site edges. Ambiguous local names are marked ambiguous. Cross-file/import resolution is not claimed.
- TDD red evidence: fixture paths containing a directory named `fixture` were initially skipped due classification filtering; tests exposed absent AST rows and absent parse diagnostics. Removing that filter fixed coverage for test/fixture code as well as source code. First full scan then hit a TypeScript AST node without `getText`; guarded source extraction and a safe per-file AST walk allowed the complete scan to finish. No source files were changed.
- Unit command (`D:\Atlas\core`): `python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py --tb=short` → **19 passed, 5 warnings in 5.75s**, exit 0. Covered TS/JS contract extraction, missing compiler, syntax-error unresolved rows, Python/config extraction, deterministic IDs, and checker behavior.
- Syntax/static commands: `python -m py_compile scripts/dsh_capability_audit.py tests/test_dsh_capability_audit.py`, `node --check scripts/dsh_ts_contracts.cjs`, and `git diff --check -- scripts/dsh_capability_audit.py scripts/dsh_ts_contracts.cjs tests/test_dsh_capability_audit.py` all exited 0.
- Pinned scan command (`D:\Atlas\core`): `python scripts/dsh_validation_runner.py --cwd D:\Atlas\core --log-dir C:\Users\25011\AppData\Local\Temp\dsh-t1-034-scan-final-20261117 --timeout 600 --cleanup-timeout 5 -- python scripts/dsh_capability_audit.py --source D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness --ledger ../tasks/dsh-parity/atomic --typescript-module D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness/node_modules/typescript/lib/typescript.js --scan` → runner **PASS**, child returncode 0, `timed_out=false`, `leftover_count=0`, duration 126.375s. Child output: `{"component_count":369,"file_count":14988,"head":"d743267388641bc76f17c45ce8b4c231aed1d32c","mode":"scan","package_manifest_count":369,"semantic_unit_count":411862,"unresolved_semantic_unit_count":411862}`. TypeScript compiler version was 6.0.3. Index SHA256 `21586eb541dfdca8461a0618bbcc4deb76558562fecfcd21d1ce817cf520a04a`, size 284,009,724 bytes.
- Index-derived counts: 126,418 `typescript_function_contract` rows, zero AST parse diagnostics/parser-unavailable rows, 411,862 semantic rows total and all 411,862 unresolved. Contracts cover same-file call sites only; cross-file/import caller resolution remains open. `.vue`, other languages, migrations, full defaults/config-to-consumer flow, and human semantic review remain open.
- Fail-closed checker command (`D:\Atlas\core`): `python scripts/dsh_validation_runner.py --cwd D:\Atlas\core --log-dir C:\Users\25011\AppData\Local\Temp\dsh-t1-034-check-20261117 --timeout 600 --cleanup-timeout 5 -- python scripts/dsh_capability_audit.py --source D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness --ledger ../tasks/dsh-parity/atomic --typescript-module D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness/node_modules/typescript/lib/typescript.js --check` → runner `FAIL` as expected for unresolved work, child returncode 1, no timeout/leftovers; output `{"finding_count":412990,"findings_by_code":{"ENTRY_POINT_UNRESOLVED":1128,"SEMANTIC_UNIT_UNRESOLVED":411862},"mode":"check"}`.
- This batch increases structured source observability; it does not resolve any semantic obligation and does not close Task 1. No production feature, live model, private authorization, desktop route, or superiority claim is implied.
