# T1-AUDIT-ENTRY-DECISIONS-082 — bind semantic decisions to package entry points

Status: DONE_SCOPED

## Files and dependency

- `core/scripts/dsh_capability_audit.py`: accept digest-bound semantic decisions keyed by exactly one semantic `unit_id` or source-index `entry_id`.
- `core/tests/test_dsh_capability_audit.py`: cover successful `package_bin` mapping and reject unknown, stale, or dangling entry decisions.
- Dependency: the successful pinned-source index refresh from `T1-INDEX-SYNC-080` and TypeScript heap correction from `T1-TYPESCRIPT-AST-HEAP-081`.
- This batch makes entry points addressable in the ledger. It does not mark any DSH entry as mapped or claim CLI parity.

## Red-first evidence

Before implementation, the new valid `entry_id` decision was rejected by `_apply_semantic_decisions`:

```text
ValueError: semantic decision contains unsupported fields
```

The focused red was `1 failed, 5 warnings in 4.03s`, exit 1. The regression passed after implementation.

## Implementation and tests

The audit accepts exactly one non-empty target field. It resolves `entry_id` only against the source index entry-point table and continues to enforce source head, entry digest, schema, unique decisions, evidence, and atom/edge referential integrity. Entry and unit decision namespaces are distinct.

The focused command from `D:\Atlas\core`:

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py::test_semantic_decisions_can_map_package_entry_points tests/test_dsh_capability_audit.py::test_entry_point_decisions_reject_unknown_stale_and_dangling_targets --tb=short --basetemp C:\Users\25011\AppData\Local\Temp\atlas-entry-082-focused
```

Actual result: `2 passed, 5 warnings in 3.48s`, exit 0. This covers a valid `scan_to_ledger` mapping and rejection of unknown entry ID, stale digest, missing atom, and missing edge.

The complete audit test module:

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py --tb=short --basetemp C:\Users\25011\AppData\Local\Temp\atlas-entry-082-suite
```

Actual result: `41 passed, 5 warnings in 14.14s`, exit 0. `py_compile` for the modified Python files exited 0.

## Limits and next work

The index currently contains unresolved DSH CLI `package_bin` entry `DSH-3A8B83E68D63E52E96A9` (`apps/cli/package.json`, `dsh: lib/bin.js`). This batch only adds a safe way to bind decisions to such entries. CLI source semantics, production execution, source references, and all parity/superiority gates remain open. Next: inspect and map the CLI entry/exports against its launcher, argument parser, build configuration, tests, and actual pinned DSH test behavior.
