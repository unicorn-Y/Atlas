# T1-POWERSHELL-AST-CONTRACTS-047

Status: DONE_SCOPED

## Scope and dependencies

Dependencies: T1-PYTHON-ENV-CONFIG-READS-046; pinned source inventory and Python/TypeScript contract extractors.

Files:

- core/scripts/dsh_capability_audit.py
- core/scripts/dsh_powershell_contracts.ps1
- core/tests/test_dsh_capability_audit.py
- tasks/dsh-parity/atomic/source-index.json and completion.json
- this batch record, progress, batch queue, atomic capability and interaction-edge ledgers

## Binary acceptance

1. All scanned `.ps1` files are parsed by PowerShell's language Parser; functions expose names/spans/parameter default digests.
2. Throw/catch/finally, platform-condition digests and state/status/phase assignment digests are extracted from AST.
3. Syntax errors and an unavailable PowerShell parser become explicit unresolved units.
4. Fixture repeat is deterministic; full pinned scan completes bounded and no semantic obligation is marked resolved.

## Implementation and evidence

- Added `dsh_powershell_contracts.ps1`, which calls `System.Management.Automation.Language.Parser.ParseFile` and serializes only AST contract metadata and digests; it never executes scanned scripts. Added `.ps1` to source classification and integrated function/parse-error/unavailable-parser units in the audit index.
- Fixture first failed because `.ps1` had no contract units. It now covers a function parameter default, throw/catch/finally, `$IsWindows`, `$status`/`$phase` assignments, deterministic rebuild, and a deliberately malformed second script preserved as unresolved parse-error evidence.
- Focused final test: `python -m pytest -q -p no:cacheprovider -o addopts= core/tests/test_dsh_capability_audit.py::test_powershell_parser_contracts_capture_function_defaults_failures_and_state` → `1 passed, 5 warnings in 5.47s`, exit 0.
- Full audit tests: `python -m pytest -q -p no:cacheprovider -o addopts= core/tests/test_dsh_capability_audit.py` → `24 passed, 5 warnings in 16.32s`, exit 0. Warnings are existing FastAPI/Pydantic deprecations. `py_compile` and `node --check` → exit 0; PowerShell helper was executed by the test and full scan.
- Full pinned scan used `NODE_OPTIONS=--max-old-space-size=8192`: `python core/scripts/dsh_validation_runner.py --cwd D:\Atlas\core --log-dir C:\Users\25011\AppData\Local\Temp\dsh-t1-047-powershell-ast-20261118 --timeout 600 --cleanup-timeout 5 -- python scripts/dsh_capability_audit.py --source D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness --ledger ../tasks/dsh-parity/atomic --typescript-module D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness/node_modules/typescript/lib/typescript.js --scan` → `{"duration_seconds":419.93700000000536,"leftover_count":0,"returncode":0,"status":"PASS","timed_out":false}`.
- Index summary: extractor 10, 14,988 files, 369 components, 411,916 semantic units, all 411,916 unresolved. 13 `.ps1` source files yielded 46 function contracts across 9 files and no parse errors in the fixed source. Index size 339,977,368 bytes. No script behavior or platform execution was performed.

## Remaining obligations

This is static AST coverage only for PowerShell. `.sh`, `.cmd`, `.nsi/.nsh`, runtime behavior, shell-specific consumer edges and all semantic review remain open. No source obligation is closed; parity and superiority remain unproven.
