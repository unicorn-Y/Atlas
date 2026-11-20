# T1-TYPESCRIPT-ERROR-PROPAGATION-053 — DONE_SCOPED

## Scope

Extend each TypeScript/JavaScript function contract with syntax-level exception scope, awaited rejection and Promise reject/handler candidates. These are inventory obligations only and remain unresolved.

## Files and dependency

- `core/scripts/dsh_ts_contracts.cjs`: emit try/catch/finally spans and body digests, await rejection sites, `Promise.reject` sites and `.catch()`/`.finally()` handler candidates.
- `core/scripts/dsh_capability_audit.py`: extractor version 16.
- `core/tests/test_dsh_capability_audit.py`: TypeScript fixture asserting spans, digest-only exception values, await and Promise edge categories.
- Source index/completion and 053 batch/atomic/interaction/progress ledgers.
- Dependency: `T1-WINDOWS-SCRIPT-CONTRACTS-052`.

## Binary acceptance

1. A fixture containing `try/catch/finally`, `throw`, three `await` sites, `Promise.reject`, `.catch`, and `.finally` exposes the corresponding span-bearing/digest-only contracts.
2. Error values and source text are not copied into the new error-path fields.
3. Every function contract stays `UNRESOLVED`; no static construct is treated as runtime error handling.
4. Full audit tests, Python compilation, Node syntax check and pinned-source extractor-16 scan pass; completion remains `INCOMPLETE`.

## Commands and actual outputs

Red test before implementation:

```text
python -m pytest -q -p no:cacheprovider core/tests/test_dsh_capability_audit.py::test_typescript_contract_tracks_try_finally_await_and_promise_error_paths
FAILED at missing obligations.exception_scopes
1 failed, 5 warnings in 5.50s
```

An intermediate test attempt used the outer semantic-unit dict as if it directly contained `obligations`; it failed with `KeyError: 'obligations'` in the test comprehension (`1 failed, 5 warnings in 5.19s`). The assertion was corrected to read `unit["contract"]["obligations"]`; extractor behavior was unchanged by that correction.

Focused green:

```text
python -m pytest -q -p no:cacheprovider --tb=short core/tests/test_dsh_capability_audit.py::test_typescript_contract_tracks_try_finally_await_and_promise_error_paths
1 passed, 5 warnings in 4.77s
```

Full audit tests and syntax checks:

```text
python -m pytest -q -p no:cacheprovider core/tests/test_dsh_capability_audit.py
33 passed, 5 warnings in 18.15s

python -m py_compile core/scripts/dsh_capability_audit.py
node --check core/scripts/dsh_ts_contracts.cjs
both exit 0
```

Pinned-source scan via `core/scripts/dsh_validation_runner.py`:

```text
{"duration_seconds": 410.5630000000092, "leftover_count": 0, "returncode": 0, "status": "PASS", "timed_out": false}
{"component_count": 369, "file_count": 14988, "head": "d743267388641bc76f17c45ce8b4c231aed1d32c", "mode": "scan", "package_manifest_count": 369, "semantic_unit_count": 413732, "unresolved_semantic_unit_count": 413732}
```

Post-scan counts: extractor 16; 126,418 function contracts; 5,406 exception scopes; 86,118 await rejection candidates; 1,421 Promise rejection/handler candidates (`487` reject, `782` catch candidates, `152` finally candidates). All source obligations remain unresolved; completion is `INCOMPLETE` (413,732/413,732 unresolved).

## Open obligations

- Syntactic `.catch()`/`.finally()` can be custom methods, and `Promise` may be shadowed; candidate labels do not prove native Promise behavior.
- This contract does not prove which errors are caught, suppressed, transformed, propagated, retried, or visible to a caller at runtime.
- Python exception/finally paths, the remaining source-language families, actual consumers, parity and superiority remain open.
