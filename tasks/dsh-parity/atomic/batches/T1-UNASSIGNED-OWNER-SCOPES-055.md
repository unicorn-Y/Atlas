# T1-UNASSIGNED-OWNER-SCOPES-055 — shell fallback and exhaustive source scopes

Status: DONE_SCOPED

## Files and dependencies

- `core/scripts/dsh_shell_parse.py`: treat a nonzero host shell result with empty stderr as host-parser failure, then use the pinned Tree-sitter grammar to distinguish valid source from syntax errors. Shell scripts remain parse-only.
- `core/scripts/dsh_capability_audit.py`: assign the root `package.json` to the root package component `@deepseek-ai/dsh-root` while leaving unrelated root files in repository scope.
- `core/tests/test_dsh_capability_audit.py`: Windows WSL app-execution alias regression and root-component/repository-scope regression; the module is marked `pytest.mark.unit`.
- Regenerated `tasks/dsh-parity/atomic/source-index.json` and `completion.json`; updated this batch, progress and atomic ledgers.
- Dependencies: pinned DSH commit `d743267388641bc76f17c45ce8b4c231aed1d32c`; extractor 18; pinned `tree-sitter-bash` grammar.

## Binary acceptance

1. A simulated Windows `bash.EXE` app alias returning exit 1, launcher text on stdout and empty stderr does not label valid shell source as a syntax error; the invalid fixture still reports line 2.
2. Root package manifest uses `component:@deepseek-ai/dsh-root`; README remains `repository:root`; all generated file and semantic-unit scope counts reconcile.
3. Full audit suite passes, pinned-source scan exits naturally with no owned children, and no source unit is promoted from unresolved.

## Red/green and verification

- Shell alias red: `python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py::test_shell_parse_uses_pinned_grammar_when_windows_shell_alias_returns_launcher_text --tb=short` → `1 failed, 5 warnings`; valid fixture received an empty-stderr diagnostic digest from the WSL alias.
- Shell targeted green: `python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py::test_shell_parse_uses_pinned_grammar_when_windows_shell_alias_returns_launcher_text tests/test_dsh_capability_audit.py::test_shell_scripts_are_parse_only_and_other_script_languages_remain_explicitly_unresolved tests/test_dsh_capability_audit.py::test_shell_ast_keeps_error_platform_status_and_dynamic_launch_semantics_unresolved --tb=short` → `3 passed, 5 warnings in 5.23s`.
- Root-scope red: the existing deterministic scope test expected `component:@fixture/root` but received `repository:root` for root `package.json`; after the `_component_for` fix the exact node → `1 passed, 5 warnings in 2.57s`.
- Final full audit: `python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py --tb=short` → `36 passed, 5 warnings in 13.26s`; collection separately confirmed `36 tests collected`.
- `python -m py_compile core/scripts/dsh_capability_audit.py core/scripts/dsh_shell_parse.py core/tests/test_dsh_capability_audit.py core/tests/test_app_server_sdk_subprocess_attempts.py` → exit 0. Targeted `git diff --check` → exit 0.
- First full scan without a Node heap override failed honestly after 98.047s: Node exit 134/V8 heap OOM, runner `FAIL`, returncode 1, timed_out false, leftover_count 0. Complete logs: `tasks/dsh-parity/atomic/runs/T1-UNASSIGNED-OWNER-SCOPES-055-extractor18/`.
- Final scan command used a process-scoped heap limit only: `$env:NODE_OPTIONS='--max-old-space-size=8192'; python core/scripts/dsh_validation_runner.py --cwd D:\Atlas --log-dir D:\Atlas\tasks\dsh-parity\atomic\runs\T1-UNASSIGNED-OWNER-SCOPES-055-final --timeout 900 -- python core/scripts/dsh_capability_audit.py --source D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --ledger tasks/dsh-parity/atomic --scan`.
- Actual runner output: `{"duration_seconds": 285.6100000000006, "leftover_count": 0, "returncode": 0, "status": "PASS", "timed_out": false, ...}`. Scanner stdout: `{"component_count": 369, "file_count": 14988, "head": "d743267388641bc76f17c45ce8b4c231aed1d32c", "mode": "scan", "package_manifest_count": 369, "semantic_unit_count": 413747, "unresolved_semantic_unit_count": 413747}`.

## Scope and limits

- Index totals reconcile: 14,988 files, 369 components, 381 scopes (369 component and 12 repository), 413,747 semantic units, 1,128 entry points. There are no files or semantic units without a scope, no components without a component scope, and scope file/unit sums match source totals.
- All 413,747 semantic units and all 1,128 entry points remain `UNRESOLVED`; `completion.json` remains `INCOMPLETE`. This batch closes source ownership assignment and the host parser false-error, not semantic review or parity.
- The DSH checkout was read only. No shell script or build/install script was executed. No real provider, desktop runtime or superiority evidence is claimed.
