# T1-TYPESCRIPT-AST-HEAP-081 — preserve full-project TypeScript resolution within a bounded Node heap

Status: DONE_SCOPED

## Files and dependencies

- `core/scripts/dsh_capability_audit.py`: invoke the full TypeScript AST helper with `--max-old-space-size=8192`.
- `core/tests/test_dsh_capability_audit.py`: verify the Node child command includes the explicit heap ceiling.
- `tasks/dsh-parity/atomic/source-index.json`: refreshed only by a successful full scan.
- `tasks/dsh-parity/atomic/completion.json`, `semantic-decisions.jsonl`, this report, queue and progress.
- Dependency: fixed DSH commit `d743267388641bc76f17c45ce8b4c231aed1d32c` and existing full-project cross-file TypeScript program.

The parser stays a single TypeScript Program so import aliases and cross-file caller edges retain their existing resolution semantics. It is not split by file.

## Red-first regression

New test red before the implementation:

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py::test_typescript_extractor_child_has_an_explicit_heap_ceiling --tb=short --basetemp C:\Users\25011\AppData\Local\Temp\atlas-t1-ts-heap-081-red
```

Actual result: `1 failed, 5 warnings in 2.97s`, exit 1; the spawned command had the helper path at index 1 instead of an explicit heap cap.

After the fix, the focused test output was `1 passed, 5 warnings in 2.29s`. Full audit test module:

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py --tb=short --basetemp C:\Users\25011\AppData\Local\Temp\atlas-t1-ts-heap-081-suite
```

Actual output: `39 passed, 5 warnings in 12.91s`, exit 0.

## Full-source rescan

The first run with the new heap cap and a 180-second supervisor deadline returned `TIMEOUT` at 180.109s, exit signal 15, no leftover processes, and empty stdout/stderr. That result was retained under `runs/T1-TYPESCRIPT-AST-HEAP-081-scan/`; it was not counted as a pass.

The successful bounded run used a fresh directory:

```text
python core/scripts/dsh_validation_runner.py --cwd D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --log-dir D:\Atlas\tasks\dsh-parity\atomic\runs\T1-TYPESCRIPT-AST-HEAP-081-scan-480 --timeout 480 --cleanup-timeout 10 -- python D:\Atlas\core\scripts\dsh_capability_audit.py --source D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --ledger D:\Atlas\tasks\dsh-parity\atomic --scan
```

Actual runner result: `{"duration_seconds": 273.98399999999674, "leftover_count": 0, "returncode": 0, "status": "PASS", "timed_out": false}`. `stdout.log` contains:

```json
{"component_count": 369, "file_count": 14988, "head": "d743267388641bc76f17c45ce8b4c231aed1d32c", "mode": "scan", "package_manifest_count": 369, "semantic_unit_count": 413747, "unresolved_semantic_unit_count": 408217}
```

Post-scan check: `source-index.json` and `completion.json` both report 413,747 total / 408,217 unresolved; 5,530 semantic decisions are mapped or excluded. The full set remains incomplete. This scan is inventory/index evidence, not runtime parity or superiority.

The final validation parsed every nonempty line in the four JSONL ledgers: `atomic-capabilities.jsonl` 418 rows, `interaction-edges.jsonl` 136, `batch-queue.jsonl` 138, and `semantic-decisions.jsonl` 5,530; all parsed successfully. Scoped `git diff --check` exited 0.
