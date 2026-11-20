# T1-CLI-ENTRY-SEMANTICS-083 — trace the pinned CLI bin and package exports

Status: DONE_SCOPED

## Files, dependency, and scope

- Reviewed pinned DSH commit `d743267388641bc76f17c45ce8b4c231aed1d32c`: `apps/cli/package.json`, `apps/cli/src/bin.ts`, `apps/cli/src/args.ts`, `apps/cli/src/profile-boot.ts`, `apps/cli/tsdown.config.ts`, `apps/cli/tests/args.spec.ts`, `apps/cli/tests/built-bin.e2e.ts`, `apps/cli/tests/resolved-profile-boot.spec.ts`, and Desktop host consumers/tests.
- Compared Atlas's installed script `atlas=atlas.cli:cli_main` and packaged backend entry `core/atlas/desktop_entry.py`; Atlas implementation was not changed in this source-mapping batch.
- Updated only the parity ledger, generated source index/completion via audit scan, batch record, queue and progress.
- Dependency: `T1-AUDIT-ENTRY-DECISIONS-082` enabled digest-bound `entry_id` decisions.

## Source and consumer findings

- DSH manifest `bin.dsh` points to `lib/bin.js`; `src/bin.ts::runCli` dispatches profile boot, plugin forwarding, config dump and config-schema dump after `parseDshArgs` decides the owned/forwarded argument boundary.
- `package.json` exports `./profile-boot`, `./lib/*`, and `./package.json`. `apps/desktop-host/src/index.ts` imports `runProfile`; `apps/desktop-host/src/cli.ts` imports `runCli`. Desktop tests and packed CLI tests are additional consumers.
- Atlas's `core/pyproject.toml` registers `atlas=atlas.cli:cli_main`; its Click command tree does not provide a verified DSH profile-launcher/shared-profile-package contract. Both entries map to explicit open Atlas gap atoms, not parity claims.
- The package `package.json` `configuration_default` semantic unit and the many CLI methods/configuration/consumer units remain unresolved; entry-point mapping is not source-semantic closure.

## DSH test evidence

Parameter parser suite:

```text
pnpm exec vitest run apps/cli/tests/args.spec.ts --reporter=dot --no-file-parallelism
```

Actual output: `Test Files 1 passed (1); Tests 58 passed (58); Duration 341ms`; exit 0.

Built CLI launcher cases, using the repository's e2e configuration:

```text
pnpm run test:e2e -- apps/cli/tests/built-bin.e2e.ts -t "requires a profile and rejects removed flags|routes help and usage errors without activating startup-dependent rows" --reporter=dot --no-file-parallelism
```

Actual output: `Test Files 1 passed (1); Tests 2 passed | 31 skipped (33); Duration 19.64s`; exit 0. Skips are the other tests excluded by the focused name filter.

Profile lifecycle source tests:

```text
pnpm exec vitest run apps/cli/tests/resolved-profile-boot.spec.ts --reporter=dot --no-file-parallelism
```

Actual output: `Test Files 1 passed (1); Tests 7 passed (7); Duration 951ms`; exit 0.

Desktop host IPC settlement consumer:

```text
pnpm run test:e2e -- apps/cli/tests/desktop-host.e2e.ts --reporter=dot --no-file-parallelism
```

Actual output: `Test Files 1 passed (1); Tests 2 passed (2); Duration 670ms`; exit 0. This test creates a temporary stub `@deepseek-ai/dsh/profile-boot`, so it proves the host IPC handoff/settlement path, not package-artifact export resolution.

An earlier default-config invocation explicitly listing `built-bin.e2e.ts` collected only the `args.spec.ts` file (`4 passed | 54 skipped`); the built-bin suite is under `vitest.e2e.config.ts`, so that output is not counted as built-bin evidence. An accidental `python -m vitest` command also exited 1 with `No module named vitest`; it was corrected to the repository's `pnpm` entrypoints above and is not a product test result.

## Digest-bound mappings and index application

Mapped entry IDs:

- `DSH-3A8B83E68D63E52E96A9` — `package_bin`, `apps/cli/package.json`, digest `6ae99480328644257038be83783fc7b86e9c156422e384cdc3a6fdc237f87777` → `T1-DSH-CLI-BIN-083` / `EDGE-T1-DSH-CLI-BIN-083`.
- `DSH-9A9F742D50E85467F2E3` — aggregate `package_exports`, same manifest digest → `T1-DSH-CLI-PUBLIC-EXPORTS-083` / `EDGE-T1-DSH-CLI-PUBLIC-EXPORTS-083`.

Full pinned scan command:

```text
python core/scripts/dsh_validation_runner.py --cwd D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --log-dir D:\Atlas\tasks\dsh-parity\atomic\runs\T1-CLI-ENTRY-SEMANTICS-083-scan --timeout 480 --cleanup-timeout 10 -- python D:\Atlas\core\scripts\dsh_capability_audit.py --source D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --ledger D:\Atlas\tasks\dsh-parity\atomic --scan
```

Actual runner result: `{"duration_seconds": 279.3289999999979, "leftover_count": 0, "returncode": 0, "status": "PASS", "timed_out": false}`. Scan stdout reports 369 components, 14,988 files, 413,747 semantic units, 408,217 unresolved at the pinned head. A post-scan JSON check found both entry points `MAPPED`, and every atom/edge reference exists. `completion.json` remains `INCOMPLETE`, source obligations 413,747 total / 408,217 unresolved. The scan applied source accounting only; no global parity/superiority completion.

## Atlas audit test and outstanding limits

After ledger updates, the full local audit test module passed `41 passed, 5 warnings in 13.82s`, exit 0. Scoped `git diff --check` exited 0.

Open: CLI per-function/config/state/error/platform/consumer semantic units; DSH package artifact export resolution in a non-stub packaged consumer; production implementation and paired runtime/UI parity; all superiority gates. Next, map every indexed `apps/cli/src/args.ts` unit and distinguish false-positive default lexemes from runtime defaults.
