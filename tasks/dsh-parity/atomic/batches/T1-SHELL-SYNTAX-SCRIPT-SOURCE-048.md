# T1-SHELL-SYNTAX-SCRIPT-SOURCE-048

Status: DONE_SCOPED

## Scope and dependencies

Dependencies: T1-POWERSHELL-AST-CONTRACTS-047; fixed source inventory and existing language extractors.

Files:

- `core/scripts/dsh_capability_audit.py`
- `core/scripts/dsh_shell_parse.py`
- `core/tests/test_dsh_capability_audit.py`
- `tasks/dsh-parity/atomic/source-index.json` and `completion.json`
- this batch record, progress, batch queue, atomic capability and interaction-edge ledgers

## Binary acceptance

1. The eight tracked `.sh` source files are passed only to `bash -n` or `sh -n`; no script is executed.
2. Syntax diagnostics retain line number and a diagnostic digest, and remain unresolved.
3. The 14 tracked `.cmd`, `.nsi`, and `.nsh` files are source-classified and each has an explicit parser-unavailable obligation.
4. A fixture command that would create a marker is not run; repeated indexing is deterministic.
5. The full pinned scan uses extractor version 11, completes without timeout or leftover process, and resolves no semantic obligation.

## Implementation and evidence

- Added a parse-only shell helper using the platform `bash -n`/`sh -n` executable with source on stdin. It does not invoke the script or source it. Syntax failures emit line number and a SHA-256 digest of parser diagnostics; unavailable parsers are explicit.
- Classified `.cmd`, `.nsi`, and `.nsh` as source and emits `script_parser_unavailable` for each. The existing index still records generic source review obligations. Extractor version is 11.
- The new test was first run before the helper/index integration had landed and failed at `StopIteration` for the absent shell contract (`1 failed` in `5.05s`). After integration and the `.nsi` fixture were present, the focused test passed as part of the full file run. The fixture checks valid Bash syntax, a malformed POSIX shell line 2, all three unsupported script suffixes, marker absence, and deterministic coverage.
- Final compile/syntax checks and audit tests:

  ```text
  python -m py_compile core/scripts/dsh_capability_audit.py core/scripts/dsh_shell_parse.py
  node --check core/scripts/dsh_ts_contracts.cjs
  python -m pytest -q -p no:cacheprovider core/tests/test_dsh_capability_audit.py
  25 passed, 5 warnings in 15.15s
  ```

- Full pinned scan command:

  ```text
  $env:NODE_OPTIONS='--max-old-space-size=8192'; python core/scripts/dsh_validation_runner.py --cwd D:\Atlas\core --log-dir C:\Users\25011\AppData\Local\Temp\dsh-t1-048-shell-source-final-20261118 --timeout 600 --cleanup-timeout 5 -- python scripts/dsh_capability_audit.py --source D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness --ledger ../tasks/dsh-parity/atomic --typescript-module D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness/node_modules/typescript/lib/typescript.js --scan
  ```

  Runner output: `{"duration_seconds":442.29700000000594,"leftover_count":0,"returncode":0,"status":"PASS","timed_out":false}`. Its stdout summary is `{"component_count":369,"file_count":14988,"head":"d743267388641bc76f17c45ce8b4c231aed1d32c","mode":"scan","package_manifest_count":369,"semantic_unit_count":411950,"unresolved_semantic_unit_count":411950}`. Completion remains `INCOMPLETE` with 411,950/411,950 unresolved. The pinned source index is 339,993,858 bytes and reports extractor version 11.

## Limits and open work

- This atom proves syntax parsing and source classification only. It does not extract Bash function/control-flow semantics, map script launch/call consumers, or execute platform behavior.
- `.cmd`, `.nsi`, and `.nsh` remain explicitly unparsed. Shell semantics, all 411,950 source obligations, cross-component behavior, runtime parity, and superiority remain open. No semantic unit was marked resolved.
