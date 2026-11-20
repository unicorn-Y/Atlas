# T1-CLI-STARTUP-AND-SDK-SOURCE-089 — startup diagnostics and SDK source fallback

Status: DONE_SCOPED for source mapping and pinned DSH acceptance.

## Scope

- Pinned DSH head: `d743267388641bc76f17c45ce8b4c231aed1d32c`.
- Reviewed 14 indexed units in `apps/cli/src/startup-diagnostics.ts` and three in `apps/cli/src/sdk-source.cordis.patch.yml`.
- The diagnostic consumer is `apps/cli/src/bin.ts`; the SDK patch consumer is `packages/sdk/client/src/launch.ts`. Tests are the diagnostic unit suite, SDK keyless startup failure child process, and SDK launcher suite.
- Digest-bound decisions are linked to `T1-DSH-CLI-STARTUP-DIAGNOSTICS-089` / `EDGE-T1-DSH-CLI-STARTUP-DIAGNOSTICS-089` and `T1-DSH-SDK-SOURCE-PATCH-089` / `EDGE-T1-DSH-SDK-SOURCE-LAUNCH-PATCH-089`.

## Contracts and consumer paths

- `reportStartupFailure` prints the startup summary, captures full error details with getters/custom inspectors disabled, and writes a unique report under the selected DSH home. On POSIX the log directory/file modes are 0700/0600. A write failure prints the full report inline and does not claim a saved path. Stderr completion is awaited; its callback error rejects to the caller. `bin.ts` catches `StartupError`, awaits this helper, then exits with code 1.
- The source-only SDK launcher branch requires all three files (`src/bin.ts`, `src/sdk-source.cordis.patch.yml`, `tsconfig.json`), selects the absolute TSX loader, passes the patch, and provides `TSX_TSCONFIG_PATH`. A present built executable bypasses the source patch and TSX environment.
- The source patch disables only `typert-loader` for a clean source checkout. It does not represent a general SDK plugin omission or a model/auth setting. Atlas startup failures use separate CLI and API lifespan paths; an equivalent structured diagnostic log contract was not established, so the Atlas atom stays OPEN.

## Verification

`pnpm exec vitest run apps/cli/tests/startup-diagnostics.spec.ts --reporter=dot --no-file-parallelism`:

```text
Test Files 1 passed (1); Tests 6 passed (6); Duration 694ms; exit 0.
```

`pnpm run test:e2e -- apps/cli/tests/profiles/sdk/keyless-smoke.e2e.ts -t "exits after startup failure with stdin open" --reporter=dot --no-file-parallelism`:

```text
Test Files 1 passed (1); Tests 2 passed | 15 skipped (17); Duration 6.50s; exit 0.
```

The process test uses a private temporary DSH home and deliberately invalid startup configuration. It verifies successful file output and blocked-log inline fallback; it makes no model request.

`pnpm exec vitest run packages/sdk/client/tests/launch.spec.ts --reporter=dot --no-file-parallelism`:

```text
Test Files 1 passed (1); Tests 14 passed (14); Duration 323ms; exit 0.
```

Atlas audit module:

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py --tb=short --basetemp C:\Users\25011\AppData\Local\Temp\atlas-startup-sdk-source-089-ledger
```

Actual output: `41 passed, 5 warnings in 14.20s`; exit 0.

Full source scan:

```text
python core/scripts/dsh_validation_runner.py --cwd D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --log-dir D:\Atlas\tasks\dsh-parity\atomic\runs\T1-CLI-STARTUP-AND-SDK-SOURCE-089-scan --timeout 480 --cleanup-timeout 10 -- python D:\Atlas\core\scripts\dsh_capability_audit.py --source D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --ledger D:\Atlas\tasks\dsh-parity\atomic --scan
```

Actual runner output: `{"duration_seconds": 273.2030000000086, "leftover_count": 0, "returncode": 0, "status": "PASS", "timed_out": false}`; supervisor exit 0. Post-scan check: 17/17 target units have digest-bound MAPPED decisions, zero missing; all indexed units under `apps/cli/src/` are now resolved. Global index is 413,747 total / 408,040 unresolved and `INCOMPLETE`.

This batch does not implement Atlas startup diagnostics or SDK source-launch parity and does not close Task 1.
