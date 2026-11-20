# T1-SHELL-ERROR-PLATFORM-INVOCATIONS-050

Status: DONE_SCOPED

## Scope and dependencies

Dependencies: T1-BASH-AST-CONTRACTS-049; extractor 12 shell AST rows and pinned source inventory.

Files:

- `core/scripts/dsh_shell_parse.py`
- `core/scripts/dsh_capability_audit.py`
- `core/tests/test_dsh_capability_audit.py`
- `tasks/dsh-parity/atomic/source-index.json` and `completion.json`
- this batch record, progress, batch queue, atomic capability and interaction-edge ledgers

## Binary acceptance

1. Bash `set`, `trap`, `exit`/`return`, platform-condition and static `exec`/source targets become specific span-bearing units; dynamic values are digest-only/unresolved.
2. Literal `bash`/`sh` and direct `.sh` invocations from package scripts, JSON command/run fields and YAML run/command fields resolve to exact in-scan target paths when present.
3. Invocation edges and shell semantic units remain unresolved obligations pending runtime/consumer validation.
4. Fixtures cover supported and dynamic cases; no script body is run; full scan and deterministic source inventory pass.

## Implementation and evidence

- Tree-sitter Bash AST now adds separate contracts for shell options, trap handlers/signals, exit/return status, platform-conditioned branches, and static/dynamic launch targets. Command arguments are retained as digest/count rather than copied; literal option/signal/status fields are kept where their shape is unambiguous.
- Added `script_invocation_edge` records for static `bash`/`sh` and direct `.sh` launch strings from package scripts, JSON `command`/`run` fields, and YAML `run`/`command` fields. Target paths are resolved relative to the package manifest or repository root and checked against the indexed source set. Each edge remains `UNRESOLVED`.
- Initial focused red tests failed because error-policy and invocation-edge units did not exist (`2 failed, 5 warnings in 6.66s`). The first implementation run also caught a Tree-sitter numeric argument node and YAML list-item `- run:` syntax; both were corrected. Final focused tests: `2 passed, 5 warnings in 4.80s`. Final full audit test file: `28 passed, 5 warnings in 17.48s`, exit 0. `py_compile` exit 0.
- Final pinned scan command:

  ```text
  $env:NODE_OPTIONS='--max-old-space-size=8192'; python core/scripts/dsh_validation_runner.py --cwd D:\Atlas\core --log-dir C:\Users\25011\AppData\Local\Temp\dsh-t1-050-shell-semantic-edges-final-20261118 --timeout 600 --cleanup-timeout 5 -- D:\Atlas\core\.venv\Scripts\python.exe scripts\dsh_capability_audit.py --source D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness --ledger ../tasks/dsh-parity/atomic --typescript-module D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness/node_modules/typescript/lib/typescript.js --scan
  ```

  Runner output: `{"duration_seconds":465.1710000000021,"leftover_count":0,"returncode":0,"status":"PASS","timed_out":false}`. Stdout summary: `{"component_count":369,"file_count":14988,"head":"d743267388641bc76f17c45ce8b4c231aed1d32c","mode":"scan","package_manifest_count":369,"semantic_unit_count":412060,"unresolved_semantic_unit_count":412060}`. Completion remains `INCOMPLETE`, 412,060/412,060 unresolved; extractor version 13, index size 340,075,313 bytes.
- Actual shell semantic counts: 5 error-policy, 1 trap, 2 platform-condition, 9 status-transition, 1 static launch-target units; 10 script invocation edges, all with target present in the source index. One parser-unavailable unit remains for `wine-windows-gates.sh` with native parser exit 3221225477.

## Limits and open work

- Harness clarification: rerunning the two focused tests with `core/.venv/Scripts/python.exe` failed during pytest setup because that environment lacks `semantic_version` (`ModuleNotFoundError` while importing the Atlas server); the tests did not execute in that attempt. The repository `python` interpreter then ran the same two tests successfully (`2 passed, 5 warnings in 6.25s`). This is an interpreter/dependency mismatch, not a product regression.
- All new semantic units and invocation edges stay unresolved; the existence of an entrypoint file does not validate its behavior or execution environment.
- `wine-windows-gates.sh` AST remains unavailable. Dynamic script paths, `cmd`/NSIS parsers, script platform/runtime behavior, all 412,060 source obligations, component parity, and superiority remain open.
