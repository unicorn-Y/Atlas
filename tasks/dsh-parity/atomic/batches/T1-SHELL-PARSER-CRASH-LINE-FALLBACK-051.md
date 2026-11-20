# T1-SHELL-PARSER-CRASH-LINE-FALLBACK-051 — DONE_SCOPED

## Scope

Keep source-location coverage when the isolated shell AST helper fails. This batch does not claim Bash AST recovery or semantic closure for the affected script.

## Files and dependency

- `core/scripts/dsh_capability_audit.py`: add digest-only, source-line obligations for each nonblank physical line on a `.sh` parser-unavailable path; bump `EXTRACTOR_VERSION` to 14.
- `core/tests/test_dsh_capability_audit.py`: add a fixture proving line spans survive, all rows stay unresolved, and source text is not copied into the index.
- `tasks/dsh-parity/atomic/source-index.json` and `completion.json`: regenerated from the pinned source.
- Atomic ledgers and `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`: record scoped evidence and the next open source lane.
- Dependency: `T1-SHELL-ERROR-PLATFORM-INVOCATIONS-050`.

## Binary acceptance

1. A simulated nonzero shell parser helper produces one `shell_opaque_line_unresolved` row per nonblank source line, with exact line span, digest, error code and `UNRESOLVED` status.
2. The semantic index does not contain the fixture's source text and no shell file is executed.
3. The audit test file and Python compilation pass.
4. A full extractor-14 scan completes with no timeout or leftover process; the new units are in the generated index and every source obligation remains unresolved.

## Root-cause evidence and limits

- Pinned DSH source: `scripts/wine-windows-gates.sh`, 12,962 bytes, 288 physical lines, SHA-256 `8b2027bb88f9d4218f94d9e031c654122905fddb64e28afaa88154fee75f2692`.
- The Bash syntax check and Tree-sitter parse reported no syntax error. The full AST contract traversal produced Windows native exit `3221225477` (`0xC0000005`) on repeated isolated runs. Direct parse and a separate guarded traversal sometimes completed; a deterministic underlying native trigger was not established. Therefore this is recorded as an unresolved parser failure, not a parser fix.
- The fallback indexed 268 nonblank physical lines for this file. Each row stores only line span and SHA-256, with parser reason and `UNRESOLVED`; it contains no source line content and asserts no command behavior.
- `.cmd`/NSIS parsing, shell runtime effects, dynamic launch targets, all source obligations, production equivalence and superiority remain open.

## Commands and actual outputs

Initial red test:

```text
python -m pytest -q -p no:cacheprovider core/tests/test_dsh_capability_audit.py::test_shell_parser_crash_keeps_each_nonempty_source_line_unresolved
1 failed, 5 warnings in 5.50s
AssertionError: expected 4 opaque rows, got 0
```

Focused green tests:

```text
python -m pytest -q -p no:cacheprovider core/tests/test_dsh_capability_audit.py::test_shell_parser_crash_keeps_each_nonempty_source_line_unresolved core/tests/test_dsh_capability_audit.py::test_shell_parser_crash_isolated_as_unresolved_for_that_file
2 passed, 5 warnings in 4.75s
```

Full audit tests and compilation:

```text
python -m pytest -q -p no:cacheprovider core/tests/test_dsh_capability_audit.py
29 passed, 5 warnings in 19.09s

python -m py_compile core/scripts/dsh_capability_audit.py core/scripts/dsh_shell_parse.py
exit 0
```

Pinned-source scan via `core/scripts/dsh_validation_runner.py`:

```text
{"duration_seconds": 473.43799999999464, "leftover_count": 0, "returncode": 0, "status": "PASS", "timed_out": false}
{"component_count": 369, "file_count": 14988, "head": "d743267388641bc76f17c45ce8b4c231aed1d32c", "mode": "scan", "package_manifest_count": 369, "semantic_unit_count": 412328, "unresolved_semantic_unit_count": 412328}
```

Post-scan source-index verification: extractor version 14; 412,328 semantic units; 412,328 unresolved; exactly 268 opaque line rows, all for `scripts/wine-windows-gates.sh`. `completion.json` is `INCOMPLETE` with total 412,328 and unresolved 412,328.
