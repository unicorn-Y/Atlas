# T1-TS-JSON-CONFIG-CONSUMERS-044

Status: DONE_SCOPED

## Scope and dependencies

Dependencies: T1-TYPESCRIPT-CROSSFILE-CALLERS-043; scanned-source TypeScript checker and JSON configuration field units.

Files:

- core/scripts/dsh_capability_audit.py
- core/scripts/dsh_ts_contracts.cjs
- core/tests/test_dsh_capability_audit.py
- tasks/dsh-parity/atomic/source-index.json
- this batch record, progress, batch queue, atomic capability and interaction-edge ledgers

## Binary acceptance

1. Default and namespace imports of an indexed JSON configuration resolve nested static property reads to the exact config file and field path.
2. Configuration field units point back to consumer path, function qualname, line and access path by stable unit ID; raw default values are not copied into consumer contracts.
3. Dynamic element access is recorded as unresolved rather than guessed.
4. Repeated fixture generation is deterministic; the pinned full scan completes under a bounded runner and leaves source obligations unresolved until reviewed.

## Implementation and evidence

- Added a fixture importing `config/settings.json` as both a default binding and namespace. Static `retry.default` access maps to the field unit; `settings.retry[dynamicKey]` remains `dynamic_property_unresolved`. Consumer contracts contain field-unit IDs and do not contain `value*` fields. The repeated fixture comparison is exact.
- Python passes only indexed config paths and field names to the TS helper, not field values. The helper enables JSON module resolution, maps default/namespace/named import bindings, and extracts property chains during the existing contract traversal. Python adds deduplicated consumer records to corresponding configuration-field units. Extractor version is 7.
- Red command: `python -m pytest -q -p no:cacheprovider -o addopts= core/tests/test_dsh_capability_audit.py::test_typescript_json_config_imports_link_to_exact_config_fields_without_copying_defaults` → first failed because `configuration_reads` did not exist. A later test-only assertion also initially confused the digit in a source line/stable ID with a leaked default; the assertion was corrected to inspect contract keys. Final focused command → `1 passed, 5 warnings in 5.75s`, exit 0.
- Full audit-script tests: `python -m pytest -q -p no:cacheprovider -o addopts= core/tests/test_dsh_capability_audit.py` → `21 passed, 5 warnings in 12.85s`, exit 0. Warnings are existing FastAPI/Pydantic deprecations.
- `python -m py_compile core/scripts/dsh_capability_audit.py` → exit 0. `node --check core/scripts/dsh_ts_contracts.cjs` → exit 0.
- Full fixed-source command ran with `NODE_OPTIONS=--max-old-space-size=8192`: `python core/scripts/dsh_validation_runner.py --cwd D:\Atlas\core --log-dir C:\Users\25011\AppData\Local\Temp\dsh-t1-044-config-consumers-20261118 --timeout 600 --cleanup-timeout 5 -- python scripts/dsh_capability_audit.py --source D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness --ledger ../tasks/dsh-parity/atomic --typescript-module D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness/node_modules/typescript/lib/typescript.js --scan` → `{"duration_seconds":416.37599999999998,"leftover_count":0,"returncode":0,"status":"PASS","timed_out":false}`.
- Index summary: 14,988 files, 369 components, 411,862 semantic units, all 411,862 still unresolved. JSON config consumer counts: 40 resolved reads on 8 field units; 1 dynamic field read unresolved. Index size 339,717,709 bytes. Sample mapped fields came from `.github/issue-management/config.json` and point to `github.mjs` functions; values were not emitted in the summary.

## Remaining obligations

This only maps static TS/JS imports from indexed JSON config fields. TOML/YAML/runtime-loaded config, environment variables, dynamic paths, non-TS/JS consumers and semantic review remain open. No source semantic obligation is closed by this batch; parity and superiority remain unproven.
