# T1-TS-ENV-CONFIG-READS-045

Status: DONE_SCOPED

## Scope and dependencies

Dependencies: T1-TS-JSON-CONFIG-CONSUMERS-044; TS/JS function contract traversal and pinned full-source scanner.

Files:

- core/scripts/dsh_ts_contracts.cjs
- core/scripts/dsh_capability_audit.py (extractor version)
- core/tests/test_dsh_capability_audit.py
- tasks/dsh-parity/atomic/source-index.json
- this batch record, progress, batch queue, atomic capability and interaction-edge ledgers

## Binary acceptance

1. Static `process.env.NAME`, `process.env["NAME"]` and `import.meta.env.NAME` reads are identified with exact key and source line.
2. `??` / `||` fallbacks record only operator and digest, never the raw default string/value.
3. Dynamic environment keys remain explicitly unresolved.
4. Repeated fixture generation is deterministic and the pinned full scan completes within a bounded runner without resolving source obligations.

## Implementation and evidence

- Added a fixture for process.env dot access, bracket static access, import.meta.env access, nullish/or fallback digests, and dynamic bracket access. Before implementation the red test found no environment reads; after implementation the focused test passes.
- Environment accesses are extracted during the existing AST walk. Static names receive `resolved_environment_key`; dynamic names receive `dynamic_environment_key_unresolved`. Direct fallback expressions retain only SHA-256 and `??`/`||` operator. No environment values or credential files are opened.
- `python -m pytest -q -p no:cacheprovider -o addopts= core/tests/test_dsh_capability_audit.py` → `22 passed, 5 warnings in 13.78s`, exit 0. Warnings are existing FastAPI/Pydantic deprecations. `python -m py_compile core/scripts/dsh_capability_audit.py` and `node --check core/scripts/dsh_ts_contracts.cjs` → exit 0.
- Full scan used `NODE_OPTIONS=--max-old-space-size=8192`: `python core/scripts/dsh_validation_runner.py --cwd D:\Atlas\core --log-dir C:\Users\25011\AppData\Local\Temp\dsh-t1-045-env-config-reads-20261118 --timeout 600 --cleanup-timeout 5 -- python scripts/dsh_capability_audit.py --source D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness --ledger ../tasks/dsh-parity/atomic --typescript-module D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness/node_modules/typescript/lib/typescript.js --scan` → `{"duration_seconds":399.2969999999994,"leftover_count":0,"returncode":0,"status":"PASS","timed_out":false}`.
- Index summary: extractor 8, 14,988 files, 369 components, 411,862 semantic units, all 411,862 unresolved. It records 611 static environment key reads, 309 dynamic-key unresolved reads and 62 fallback digests; no raw fallback values are serialized. JSON config mapping remains 40 reads across 8 config field units. Index size 339,903,966 bytes.

## Remaining obligations

This covers only TS/JS syntactic environment reads. Runtime config loaders, Python/Vue/other-language environment APIs, TOML/YAML consumers, dynamic key resolution and semantic review remain open. No source obligation is closed; overall parity and superiority remain unproven.
