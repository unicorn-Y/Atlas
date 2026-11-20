# T1-PYTHON-ERROR-CLEANUP-054 — DONE_SCOPED

## Scope

Extend Python function inventory contracts with exception scopes, raise/cause sites, await rejection candidates and context-manager resource boundaries. No Python production source is executed.

## Files and dependency

- `core/scripts/dsh_capability_audit.py`: Python `Try`/`TryStar`, handler/else/finally spans, `raise`/`raise from`, `await`, `with` and `async with` contracts; extractor version 17.
- `core/tests/test_dsh_capability_audit.py`: AST fixture covering `except*`, cleanup body span, raises, await and async context manager without running the fixture.
- Source index/completion and 054 batch/atomic/interaction/progress ledgers.
- Dependency: `T1-TYPESCRIPT-ERROR-PROPAGATION-053`.

## Binary acceptance

1. Red fixture proves the prior Python function contract omitted exception scopes.
2. Extracted contract distinguishes `except` from `except*`, captures finally body span, `raise from`, awaits and context-manager scope; values remain digests.
3. New data remains unresolved and is never represented as runtime behavior.
4. Full audit tests, compilation and extractor-17 pinned-source scan pass; completion remains `INCOMPLETE`.

## Commands and actual outputs

Initial red test:

```text
python -m pytest -q -p no:cacheprovider --tb=short core/tests/test_dsh_capability_audit.py::test_python_contract_tracks_raise_except_star_finally_await_and_async_with
FAILED at missing obligations.exception_scopes
1 failed, 5 warnings in 5.96s
```

The first implementation run then showed the AST finally-body span starts at the first executable body statement (line 9), not at the `finally:` header (line 8); the fixture expectation was corrected to the actual AST body span. Final focused test:

```text
python -m pytest -q -p no:cacheprovider --tb=short core/tests/test_dsh_capability_audit.py::test_python_contract_tracks_raise_except_star_finally_await_and_async_with
1 passed, 5 warnings in 3.29s
```

Full audit tests and Python compilation:

```text
python -m pytest -q -p no:cacheprovider core/tests/test_dsh_capability_audit.py
34 passed, 5 warnings in 20.52s

python -m py_compile core/scripts/dsh_capability_audit.py
exit 0
```

Pinned-source scan via `core/scripts/dsh_validation_runner.py`:

```text
{"duration_seconds": 467.0149999999994, "leftover_count": 0, "returncode": 0, "status": "PASS", "timed_out": false}
{"component_count": 369, "file_count": 14988, "head": "d743267388641bc76f17c45ce8b4c231aed1d32c", "mode": "scan", "package_manifest_count": 369, "semantic_unit_count": 413732, "unresolved_semantic_unit_count": 413732}
```

Post-scan Python contract counts: 474 function/method contracts; 69 exception scopes (9 with a finally body); 64 handlers; 266 raises; 5 await points; 163 `with`/`async with` scopes. No `except*` occurs in the pinned Python source; the fixture proves extractor support only. Completion remains `INCOMPLETE`, 413,732/413,732 unresolved.

## Open obligations

- The five await points and context scopes are candidates; exception suppression by `__exit__`, cancellation, exception-group matching and caller-visible effects require runtime tracing.
- Python cross-file caller edges, non-Python semantic gaps, production parity and superiority remain open.
