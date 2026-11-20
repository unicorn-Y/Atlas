# T1-WORKING-DIRECTORY-SEMANTIC-GAP-058 — runtime source units mapped to explicit Atlas gap

Status: DONE_SCOPED

## Files and dependencies

- `core/scripts/dsh_capability_audit.py`: pinned semantic decision overlay, fail-closed digest/head/reference validation, and unresolved count refresh.
- `core/tests/test_dsh_capability_audit.py`: stale digest, unknown unit, missing reference, and preserved-index assertions; module is marked `pytest.mark.unit`.
- `tasks/dsh-parity/atomic/semantic-decisions.jsonl`: 42 decisions bound to the pinned DSH head and the exact runtime source-unit digests.
- `tasks/dsh-parity/atomic/source-index.json`, `completion.json`, atomic/interaction/batch ledgers, this report, and progress.
- Dependencies: extractor-18 source index, fixed DSH head `d743267388641bc76f17c45ce8b4c231aed1d32c`, and the previously established bounded scan runner.

## Semantic mapping

The 42 extractable semantic units in `packages/session/working-directory/src/index.ts` are individually mapped to `T1-WORKING-DIRECTORY-SEMANTIC-GAP-058` and `EDGE-T1-WORKING-DIRECTORY-SEMANTIC-GAP-058`, each with its own source digest. The reviewed runtime contracts include:

- deployment default and absolute-path requirement;
- per-Session projection initialization from immutable origin, event reducer, and wire view;
- pure `get`, serialized `ensure` and `set`, filesystem resolve/stat/canonicalization;
- missing-current-directory recovery to original cwd/default;
- durable change event followed by model-visible notice, with notice failure warned without reverting committed state;
- service abort/liveness handling and serialization of concurrent changes;
- SDK methods that create/assert a live agent before get/set.

Atlas has per-run/per-tool `cwd` and `workspace_session_manage(move)`, which requires approval and changes the persisted workspace for the next run. It does not have the DSH per-session effective-cwd projection/get/set contract. Directly changing Atlas `workspace` would conflate execution cwd with the trust root, so no production shortcut was added. The DSH service's 42 source units are **mapped to an explicit parity gap**, not marked behaviorally equivalent or superior.

The component contains 235 indexed semantic units total. The other 193 units, including package/config/docs/tests and consumer files, remain unresolved. The consumer scan identifies separate shell, filesystem, terminal, LSP, skill/reference, subagent, SDK, workflow, and worktree seams that need their own mapping and runtime work.

## Verification

Red/green audit nodes:

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py::test_scan_applies_semantic_decisions_and_rejects_stale_source_digest tests/test_dsh_capability_audit.py::test_scan_rejects_unowned_semantic_decision_references --tb=short
```

Actual output: `2 passed, 5 warnings in 3.14s`, exit 0. Earlier red iterations exposed test-fixture selection mistakes (choosing a method signature whose digest did not include the changed body); the final test binds the full-file review unit and confirms stale source changes are rejected before the prior source index is overwritten.

Complete audit test file:

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py --tb=short
```

Actual output: `38 passed, 5 warnings in 13.88s`, exit 0.

Bounded fixed-source scan command:

```text
$env:NODE_OPTIONS='--max-old-space-size=8192'; python core/scripts/dsh_validation_runner.py --cwd D:\Atlas --log-dir D:\Atlas\tasks\dsh-parity\atomic\runs\T1-WORKING-DIRECTORY-SEMANTIC-GAP-058-scan --timeout 900 -- python core/scripts/dsh_capability_audit.py --source D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --ledger tasks\dsh-parity\atomic --scan
```

Actual runner output: `{"duration_seconds": 301.4219999999914, "leftover_count": 0, "returncode": 0, "status": "PASS", ..., "timed_out": false}`. Scanner stdout: `{"component_count":369,"file_count":14988,"head":"d743267388641bc76f17c45ce8b4c231aed1d32c","mode":"scan","package_manifest_count":369,"semantic_unit_count":413747,"unresolved_semantic_unit_count":413705}`. Post-scan verification found 42/42 runtime-file units MAPPED, 42/235 component units MAPPED, 193 component units still unresolved, and completion `total=413747, unresolved=413705`.

## Limits

This is source accounting and test evidence only. It does not implement working-directory parity, resolve consumer-package semantics, establish live model/desktop behavior, or demonstrate superiority. The full source ledger remains INCOMPLETE.
