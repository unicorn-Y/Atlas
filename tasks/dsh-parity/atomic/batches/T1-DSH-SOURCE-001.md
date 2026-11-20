# T1-DSH-SOURCE-001 — DSH source inventory and audit substrate

- `batch_id`: `T1-DSH-SOURCE-001`
- `atomic_ids`: `T1-SOURCE-FILE-CLOSURE`, `T1-SEMANTIC-COVERAGE-EXTRACTION`, `T1-DIGEST-INVALIDATION`, `T1-AUDIT-CHECK`, `T1-BOUNDED-RUNNER`
- `phase`: P1
- `dependencies`: none
- `implementation_dependencies`: none
- `verification_dependencies`: fixed DSH source commit `d743267388641bc76f17c45ce8b4c231aed1d32c`; initial read-only path/hash snapshot.
- `global_completion_gates`: semantic obligations manually mapped; Task 1 full source closure remains open until every source unit is mapped or evidenced as excluded.

## Files

- Create `core/scripts/dsh_capability_audit.py`
- Create `core/scripts/dsh_validation_runner.py`
- Create `core/tests/test_dsh_capability_audit.py`
- Create `tasks/dsh-parity/atomic/source-index.json`
- Create `tasks/dsh-parity/atomic/atomic-capabilities.jsonl`
- Create `tasks/dsh-parity/atomic/interaction-edges.jsonl`
- Create `tasks/dsh-parity/atomic/batch-queue.jsonl`
- Create `tasks/dsh-parity/atomic/completion.json`
- Modify `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`
- Create this batch plan before implementation.

## Binary acceptance

1. Inventory is generated read-only from the pinned source commit, repeat generation is byte-stable, and every discovered path has digest, classification and discovery parent.
2. Package/build/registration/config/protocol/UI entry points and parseable semantic units receive stable IDs and references. Unsupported/dynamic units remain explicit `UNRESOLVED`; the checker exits nonzero for unresolved units, source additions/removals/renames, stale digests, missing references, empty required fields, or claimed CLOSED without evidence.
3. Tests demonstrate a new package/manifest, an internal method/default/state/platform unit change without a new package, stale evidence, dangling references, and a fake CLOSED record all fail checking.
4. Bounded runner tests demonstrate deadline, output-then-hang, PID reuse, child cleanup ownership and leftover reporting; it must not turn an unrun test into PASS.

## Execution boundary

- Read only `D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness`; do not execute upstream scripts or package lifecycle hooks.
- Keep all local generated state in `tasks/dsh-parity/atomic`; do not read credentials or mutate user data.
- Roll back only files created by this batch; do not touch pre-existing dirty files.
- This batch creates the audit substrate. It does not mark Task 1 closed until the semantic coverage ledger is individually signed off.

## Initial snapshot

- DSH HEAD: `d743267388641bc76f17c45ce8b4c231aed1d32c`
- DSH tracked file count (from `git ls-files`): 14,988
- DSH `package.json` count: 369
- Atlas branch/HEAD: `wave3` / `060071ab`
