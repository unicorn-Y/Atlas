# T1-WINDOWS-SCRIPT-CONTRACTS-052 — DONE_SCOPED

## Scope

Add line-anchored, value-redacted source contracts for the tracked Windows command scripts and NSIS installer files, plus static invocation/include/macro edges. All new rows remain unresolved; no script or installer was executed.

## Files and dependency

- `core/scripts/dsh_capability_audit.py`: `.cmd`/`.nsi`/`.nsh` line contract extraction; static `cmd`/`makensis` launch resolution; NSIS include and macro-definition/call edges; extractor version 15.
- `core/tests/test_dsh_capability_audit.py`: batch state/dynamic target, NSIS construct/install state, and static edge fixtures.
- `tasks/dsh-parity/atomic/source-index.json`, `completion.json`, batch/atomic/interaction-edge ledgers and `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`.
- Dependency: `T1-SHELL-PARSER-CRASH-LINE-FALLBACK-051`.

## Binary acceptance

1. Every nonblank `.cmd`, `.nsi`, and `.nsh` line receives a line-span contract with digest and `UNRESOLVED` status.
2. Batch scope, variable assignment, conditions, control transfer and dynamic target patterns are classified without storing assigned values or expanded paths.
3. NSIS conditional/function/macro/section/default/install-state/include directives are distinguished; static includes and macro calls point to tracked source files when found.
4. Package/workflow launch strings may resolve `.cmd` targets; all invocation/include/macro edges remain unresolved pending runtime and consumer validation.
5. Fixture tests, compilation and pinned-source scan pass; completion remains `INCOMPLETE` and no source obligation is auto-closed.

## Commands and actual outputs

Before implementation, the two structural fixture tests failed (`FF`) because the expected `windows_batch_*` and `nsis_*` contracts did not exist.

Focused new fixture tests:

```text
python -m pytest -q -p no:cacheprovider core/tests/test_dsh_capability_audit.py::test_windows_batch_contracts_capture_state_and_dynamic_targets_without_values core/tests/test_dsh_capability_audit.py::test_nsis_contracts_capture_include_function_macro_branch_and_install_state core/tests/test_dsh_capability_audit.py::test_windows_script_invocation_edges_cover_cmd_and_nsis_include
3 passed, 5 warnings in 4.63s
```

Full audit tests and compilation:

```text
python -m pytest -q -p no:cacheprovider core/tests/test_dsh_capability_audit.py
32 passed, 5 warnings in 19.20s

python -m py_compile core/scripts/dsh_capability_audit.py core/scripts/dsh_shell_parse.py
exit 0
```

Pinned-source scan via `core/scripts/dsh_validation_runner.py`:

```text
{"duration_seconds": 445.68799999999464, "leftover_count": 0, "returncode": 0, "status": "PASS", "timed_out": false}
{"component_count": 369, "file_count": 14988, "head": "d743267388641bc76f17c45ce8b4c231aed1d32c", "mode": "scan", "package_manifest_count": 369, "semantic_unit_count": 413732, "unresolved_semantic_unit_count": 413732}
```

Post-scan index facts: extractor version 15; 1,404 Windows script line contracts; 15 NSIS include edges; 36 macro invocation edges; 10 existing script invocation edges. All 1,455 of these rows are unresolved. Completion is `INCOMPLETE`, total 413,732 and unresolved 413,732.

## Open obligations

- These are line-token contracts, not complete `cmd.exe` or NSIS grammars. Labels, expansion precedence, installer VM/control-flow effects, architecture/OS differences, registry/rollback effects, installer UI and consumer behavior need deeper semantic tracing and runtime comparison.
- Static include/macro existence does not prove preprocessing or resolved execution order. Dynamic paths and expansion values remain unresolved.
- All source parity and superiority obligations remain open; this batch is only a source-map increment.
