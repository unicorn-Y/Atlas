# T1-PROFILE-BOOT-SEMANTICS-086 — resolve profile lifecycle source obligations

Status: DONE_SCOPED

## Scope

- Pinned DSH head: `d743267388641bc76f17c45ce8b4c231aed1d32c`.
- Reviewed all 60 indexed units in `apps/cli/src/profile-boot.ts`, plus the profile consumer path in `apps/cli/src/bin.ts`, `dump-config.ts`, `dump-config-schema.ts`, Desktop host `index.ts`/`cli.ts`, and Atlas `core/atlas/cli.py` / `desktop_entry.py`.
- Reviewed relevant tests: `resolved-profile-boot.spec.ts`, `process-shutdown.spec.ts`, `profile-hmr.spec.ts`, built-bin profile lifecycle cases, Web failure matrix, and best-effort startup suite.
- Only parity ledgers, source index/completion, this report, progress and queue changed. No DSH upstream or Atlas product source changed.
- Dependency: `T1-CLI-BIN-DISPATCH-085`.

## Semantic resolution

All 60 indexed units have digest-bound decisions: 56 MAPPED to a still-open profile-lifecycle contract and six concrete consumer edges, four EXCLUDED as source-index `default` word false positives. The excluded lines are error/help/doc strings (`unknown default profile`, `--from-default-profile` guidance, and “default dump”), not runtime values. Actual defaults that the lexical extractor did not identify—`home=resolveDshHome()`, `prepareProfile(..., userLayer=true)`, `createAppReady`'s initial `ready=false`, and optional resolved/template/packageManager inputs—are recorded in their function/type decisions.

The mapped source contract covers exclusive profile creation and rollback, empty root reset, profile/bundle/user/home/CLI patch precedence, runtime resolution before plugin import, frozen proxy/launch environment, cmdline injection, ready transition, signal code mapping, fail-loud handling, memoized ordered cleanup and error aggregation. DSH Desktop consumes the exported profile runtime; Atlas's Click CLI and desktop entry do not establish an equivalent shared lifecycle. The gap atom stays `PARTIAL` / `OPEN`.

## Verification evidence

Direct lifecycle unit group:

```text
pnpm exec vitest run apps/cli/tests/resolved-profile-boot.spec.ts apps/cli/tests/process-shutdown.spec.ts apps/cli/tests/profile-hmr.spec.ts --reporter=dot --no-file-parallelism
```

Actual output: `Test Files 3 passed (3); Tests 22 passed (22); Duration 1.48s`; exit 0.

Built-bin process consumers:

```text
pnpm run test:e2e -- apps/cli/tests/built-bin.e2e.ts -t "lets a profile without a parser ignore app arguments and dispose on a startup-time signal|fully settles a custom profile, hot-reloads its patch layer with removal reverting, and disposes on a signal|hands the app arguments to the profile, which applies them before its rows start|starts a consumer on its composed value when the invocation carries no app arguments|keeps the app arguments across a user patch reload" --reporter=verbose --no-file-parallelism
```

Actual output: `Test Files 1 passed (1); Tests 5 passed | 28 skipped (33); Duration 11.33s`; exit 0. The five named cases verify signal disposal, patch removal/revert, app-argument delivery, composed-value consumer startup and argument persistence across reload.

Real local profile failure matrix:

```text
pnpm run test:expected -- apps/cli/tests/profiles/web/tests/web-failure-matrix.expected.e2e.ts --reporter=dot --no-file-parallelism
```

Actual output: `Test Files 1 passed (1); Tests 51 passed (51); Duration 195.99s`; exit 0.

Best-effort startup and detached work failure:

```text
pnpm run test:expected -- apps/cli/tests/profiles/web/tests/web-best-effort-startup.expected.e2e.ts --reporter=verbose --no-file-parallelism
```

Actual output: `Test Files 1 passed (1); Tests 8 passed (8); Duration 30.35s`; exit 0. Cases include usable Web startup while unrelated entries fail and failure/disposal after detached work rejects.

Atlas ledger module after digest correction:

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py --tb=short --basetemp C:\Users\25011\AppData\Local\Temp\atlas-profile-boot-086-final-ledger
```

Actual output: `41 passed, 5 warnings in 13.95s`; exit 0.

The first full scan failed and is retained at `runs/T1-PROFILE-BOOT-SEMANTICS-086-scan/`: runner returned exit 2 after 262.734s, no timeout/leftovers; audit surfaced only `ValueError`. Direct digest comparison found six mistyped copied hashes in new decisions. They were corrected and verified before the second scan.

Second full pinned scan command:

```text
python core/scripts/dsh_validation_runner.py --cwd D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --log-dir D:\Atlas\tasks\dsh-parity\atomic\runs\T1-PROFILE-BOOT-SEMANTICS-086-scan-r2 --timeout 480 --cleanup-timeout 10 -- python D:\Atlas\core\scripts\dsh_capability_audit.py --source D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --ledger D:\Atlas\tasks\dsh-parity\atomic --scan
```

Actual output: `{"duration_seconds":272.76600000000326,"leftover_count":0,"returncode":0,"status":"PASS","timed_out":false}`; exit 0. Post-scan check: 60 target units, 56 MAPPED / 4 EXCLUDED, no bad digest/ref; global inventory 413,747 total / 408,120 unresolved, completion `INCOMPLETE`.

## Limits and next work

Tests ran locally with DSH fixtures/processes; no live model, actual packaged Atlas Desktop, Atlas parity, or superiority is claimed. Task 1's full source semantic universe remains open. Continue into Task 2's cross-consumer attempt rollback/commit implementation and verification; do not stop at this mapping batch.
