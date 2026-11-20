# T1-PYTHON-ENV-CONFIG-READS-046

Status: DONE_SCOPED

## Scope and dependencies

Dependencies: T1-TS-ENV-CONFIG-READS-045; existing Python AST function contracts.

Files:

- core/scripts/dsh_capability_audit.py
- core/tests/test_dsh_capability_audit.py
- tasks/dsh-parity/atomic/source-index.json
- this batch record, progress, batch queue, atomic capability and interaction-edge ledgers

## Binary acceptance

1. Python `os.environ.get`, `os.getenv`, imported/aliased `getenv` and imported/aliased `environ` accesses resolve static string keys.
2. Dynamic environment keys remain explicitly unresolved.
3. Call default arguments store only SHA-256 digest, not raw fallback value.
4. Repeated fixture indexing is deterministic and the fixed source scan finishes bounded without resolving semantic obligations.

## Implementation and evidence

- Added a fixture using `import os as operating_system`, `from os import getenv as read_environment`, and `from os import environ as environment_map`, covering `.get`, `getenv`, static mapping subscript and dynamic mapping subscript.
- Python AST contracts now record environment access with source line, key and resolution; call default arguments are represented by digest only. The fixture red test failed on absent `configuration_reads`, then passed after implementation.
- `python -m pytest -q -p no:cacheprovider -o addopts= core/tests/test_dsh_capability_audit.py` → `23 passed, 5 warnings in 15.44s`, exit 0. Focused final test → `1 passed, 5 warnings in 4.03s`, exit 0. `python -m py_compile core/scripts/dsh_capability_audit.py` → exit 0.
- Bounded full scan with `NODE_OPTIONS=--max-old-space-size=8192`: `python core/scripts/dsh_validation_runner.py --cwd D:\Atlas\core --log-dir C:\Users\25011\AppData\Local\Temp\dsh-t1-046-python-env-reads-20261118 --timeout 600 --cleanup-timeout 5 -- python scripts/dsh_capability_audit.py --source D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness --ledger ../tasks/dsh-parity/atomic --typescript-module D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness/node_modules/typescript/lib/typescript.js --scan` → `{"duration_seconds":422.67200000000594,"leftover_count":0,"returncode":0,"status":"PASS","timed_out":false}`.
- Index summary: extractor 9, 14,988 files, 369 components, 411,862 semantic units, all 411,862 still unresolved. Python contracts contain 12 static environment-key reads across 9 functions, 1 dynamic key unresolved and 6 fallback digests. JSON config links remain 40 reads across 8 field units. Index size 339,924,471 bytes.

## Remaining obligations

Only syntactically recognized Python `os` environment APIs are covered. Runtime config-loader values, TOML/YAML consumers, other-language APIs, alias/dataflow beyond direct imports, and semantic review remain open. No source obligation is closed by this batch; parity and superiority remain unproven.
