# T1-BASH-AST-CONTRACTS-049

Status: DONE_SCOPED

## Scope and dependencies

Dependencies: T1-SHELL-SYNTAX-SCRIPT-SOURCE-048; shell syntax contracts; pinned Tree-sitter runtime and Bash grammar.

Files:

- `core/scripts/dsh_shell_parse.py`
- `core/scripts/dsh_capability_audit.py`
- `core/tests/test_dsh_capability_audit.py`
- `tasks/dsh-parity/atomic/tooling/requirements.txt`
- `tasks/dsh-parity/atomic/source-index.json` and `completion.json`
- this batch record, progress, batch queue, atomic capability and interaction-edge ledgers

## Binary acceptance

1. Parsed Bash AST function, control-flow and literal command nodes carry source spans and remain unresolved semantic obligations.
2. Dynamic command names and per-file parser crashes remain explicit unresolved records; one file cannot abort unrelated source extraction.
3. A side-effecting fixture is never executed; repeated fixture indexing remains deterministic.
4. The full pinned scan uses the explicitly selected Python interpreter with locked grammar dependencies and leaves all semantic obligations unresolved.

## Implementation and evidence

- Added the audit-only pins `tree-sitter==0.26.0` and `tree-sitter-bash==0.25.1`. The runtime pin matches `core/pyproject.toml`; only the grammar is additional. The helper still runs `bash -n`/`sh -n` first and never executes scanned scripts.
- Added AST contracts for Bash functions, control-flow statements and literal command names, including line spans and enclosing function. Dynamic command names are digest-only `shell_dynamic_command_unresolved` units. All remain `UNRESOLVED`.
- The test was first red: missing `shell_function_contract` caused `StopIteration` (`1 failed` in `4.78s`). Focused final tests for AST spans, dynamic command and parser-crash isolation: `2 passed, 5 warnings in 4.32s`. Full audit suite: `python -m pytest -q -p no:cacheprovider core/tests/test_dsh_capability_audit.py` → `26 passed, 5 warnings in 12.86s`, exit 0. `python -m py_compile core/scripts/dsh_capability_audit.py core/scripts/dsh_shell_parse.py` → exit 0.
- A full scan using an implicit Python executable failed closed at 232.437s because the `tree-sitter-bash` native parser crashed on `scripts/wine-windows-gates.sh` (exit `3221225477`), without timeout or leftovers. A per-file probe isolated the crash to that file; the other seven files parsed. The extractor now launches one parser child per file and records the crashed file as `SHELL_AST_HELPER_EXIT_3221225477` rather than losing the entire scan.
- An earlier runner invocation selected `core/.venv` before its parser dependency was installed and returned PASS while marking Tree-sitter unavailable. That run is not accepted as AST evidence. A direct pytest attempt in `core/.venv` also failed during setup because that environment lacks `semantic_version`; the final test command above used the repository's working test environment. The temporary runtime conflict was corrected: `core/.venv` is restored to `tree-sitter==0.26.0` as declared by `core/pyproject.toml`.
- Final full pinned scan command:

  ```text
  $env:NODE_OPTIONS='--max-old-space-size=8192'; python core/scripts/dsh_validation_runner.py --cwd D:\Atlas\core --log-dir C:\Users\25011\AppData\Local\Temp\dsh-t1-049-bash-ast-isolated-20261118 --timeout 600 --cleanup-timeout 5 -- D:\Atlas\core\.venv\Scripts\python.exe scripts\dsh_capability_audit.py --source D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness --ledger ../tasks/dsh-parity/atomic --typescript-module D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness/node_modules/typescript/lib/typescript.js --scan
  ```

  Runner output: `{"duration_seconds":452.18799999999464,"leftover_count":0,"returncode":0,"status":"PASS","timed_out":false}`. Scan stdout: `{"component_count":369,"file_count":14988,"head":"d743267388641bc76f17c45ce8b4c231aed1d32c","mode":"scan","package_manifest_count":369,"semantic_unit_count":412032,"unresolved_semantic_unit_count":412032}`. Index extractor version 12, size 340,044,983 bytes; completion stays `INCOMPLETE` (412,032/412,032 unresolved).
- Indexed shell counts: 7 syntax contracts; 0 function contracts among the seven AST-parsed files; 7 control-flow contracts; 69 literal command units; 6 dynamic command units unresolved; 1 parser-crash unresolved unit for `wine-windows-gates.sh`. The eight tracked shell files are therefore not all semantically parsed. The 14 `.cmd/.nsi/.nsh` files stay parser-unavailable.

## Limits and open work

- The one Bash parser crash remains unresolved, including functions and other AST content in `wine-windows-gates.sh`. Zero parsed function definitions is an observed count, not proof the source has none.
- Error handling (`trap`, `set -e` interactions), platform branches, state changes, script launch/call edges, cmd/NSIS grammar, runtime behavior, all 412,032 source obligations, parity, and superiority remain open. No semantic obligation was closed.
