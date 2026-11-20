# T1-INDEX-SYNC-080 — reconcile the generated semantic index

Status: DONE_SCOPED_AFTER_T1-TYPESCRIPT-AST-HEAP-081

## Files and dependencies

- Generated target: `tasks/dsh-parity/atomic/source-index.json`.
- Inputs: fixed DSH commit `d743267388641bc76f17c45ce8b4c231aed1d32c`, `semantic-decisions.jsonl`, and `core/scripts/dsh_capability_audit.py`.
- Evidence: `atomic/runs/T1-INDEX-SYNC-080-scan/` and the recovered scan in `atomic/runs/T1-TYPESCRIPT-AST-HEAP-081-scan-480/`.
- Dependency: T1-TYPESCRIPT-AST-HEAP-081.

## Initial failed scan

Exact bounded command:

```text
python core/scripts/dsh_validation_runner.py --cwd D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --log-dir D:\Atlas\tasks\dsh-parity\atomic\runs\T1-INDEX-SYNC-080-scan --timeout 180 --cleanup-timeout 10 -- python D:\Atlas\core\scripts\dsh_capability_audit.py --source D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --ledger D:\Atlas\tasks\dsh-parity\atomic --scan
```

Actual runner result: `{"duration_seconds": 94.73400000002584, "leftover_count": 0, "returncode": 1, "status": "FAIL", "timed_out": false}`. The full stderr in `stderr.log` records TypeScript AST extraction failure, Node exit 134, V8 mark-compact near 4090 MB and fatal heap exhaustion. The index was not rewritten on this failure.

## Recovery

The AST child heap issue and complete successful rescan are recorded in `T1-TYPESCRIPT-AST-HEAP-081.md`. The final scanner output reports 413,747 semantic units and 408,217 unresolved; `completion.json` has the same totals. This batch closes only the stale index/completion discrepancy. The unresolved source obligations remain open.
