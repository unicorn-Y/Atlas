# T1-CLI-BIN-DISPATCH-085 — resolve the CLI dispatcher contract

Status: DONE_SCOPED

## Scope and files

- Pinned DSH head: `d743267388641bc76f17c45ce8b4c231aed1d32c`.
- Read: `apps/cli/src/bin.ts`, `args.ts`, `profile-boot.ts`, `plugin.ts`, `dump-config.ts`, `dump-config-schema.ts`, `apps/cli/package.json`, `built-bin.e2e.ts`, `dump-config-schema.expected.e2e.ts`, `resolved-profile-boot.spec.ts`, `core/atlas/cli.py`, and `core/atlas/desktop_entry.py`.
- Changed only Atlas parity ledgers/report/progress/queue. No DSH upstream or Atlas product source was changed.
- Dependency: `T1-CLI-ENTRY-SEMANTICS-083` and `T1-CLI-ARGS-SEMANTICS-084`.

## Semantic resolution

All 14 indexed `bin.ts` units now have digest-bound decisions: 13 MAPPED to the dispatcher gap and concrete profile/plugin/config/schema consumer edges, and one EXCLUDED. The excluded `default` token at line 70 is the exhaustive switch arm paired with `invocation satisfies never`; it is control flow, not a configuration value. No indexed unit is unresolved and all referenced atom/edge IDs exist.

The dispatcher lazily imports only the selected mode. Profile mode loads the layered environment and catches `StartupError` for diagnostics/exit 1; plugin mode forwards the parsed profile, arguments and package manager and exits with the plugin result; config and schema inspection call distinct boot-free projection paths. Atlas's Click CLI and desktop entry do not demonstrate these contracts. The new atom and all four consumer edges remain `PARTIAL`/open; mapping DSH behavior is not Atlas parity.

## Verification

Official built-bin e2e, first selected branch set:

```text
pnpm run test:e2e -- apps/cli/tests/built-bin.e2e.ts -t "requires a profile and rejects removed flags|routes help and usage errors without activating startup-dependent rows|fails loud on a nonexistent profile with the plugin-command hint|creates a custom profile from a shipped template before booting it|forwards CLI authentication and stdin through pnpm while preserving its exit code|prints the app's own help|prints the headless profile without Host or browser layers|prints the exact standalone sdk-minimal tree without dsh-base|composes the profile user layer and a --patch overlay in order" --reporter=dot --no-file-parallelism
```

Actual output: `Test Files 1 passed (1); Tests 8 passed | 25 skipped (33); Duration 21.98s`; exit 0. The regex matched eight cases; the shipped-template initialization case was run separately below.

Additional launcher/config cases:

```text
pnpm run test:e2e -- apps/cli/tests/built-bin.e2e.ts -t "creates a custom profile from the shipped web template before booting it|rejects an unknown source before creating the target profile" --reporter=verbose --no-file-parallelism
```

Actual output: `Tests 2 passed | 31 skipped (33); Duration 7.61s`; exit 0.

```text
pnpm run test:e2e -- apps/cli/tests/built-bin.e2e.ts -t "creates a custom profile from a shipped template before printing it" --reporter=verbose --no-file-parallelism
```

Actual output: `Tests 1 passed | 32 skipped (33); Duration 1.12s`; exit 0.

Schema-specific expected acceptance:

```text
pnpm run test:expected -- apps/cli/tests/dump-config-schema.expected.e2e.ts --reporter=dot --no-file-parallelism
```

Actual output: `Test Files 1 passed (1); Tests 11 passed (11); Duration 13.43s`; exit 0. This checks schema shape, collection without plugin apply, diagnostics/incomplete exit handling, and patch/module resolution.

An extra direct source-tree invocation used a unique temporary `DSH_HOME`, without credentials or live models:

```text
node --import tsx/esm apps/cli/src/bin.ts --profile web --dump-config-schema
```

Captured result: exit 1, `SCHEMA_COMPLETE=False`, 8 diagnostics. Four were warnings about projection of native validators/transforms; four errors said Loader tree carriers at paths `/181` through `/184` were unrecognized. This invocation is retained as an incomplete source-tree observation, not a packaged CLI pass/fail: the official schema acceptance uses isolated native fixtures and passed 11/11. The isolated temp tree was not a user DSH home.

Atlas ledger tests after decisions:

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py --tb=short --basetemp C:\Users\25011\AppData\Local\Temp\atlas-cli-bin-085-ledger
```

Actual output: `41 passed, 5 warnings in 14.19s`; exit 0.

Full pinned source scan:

```text
python core/scripts/dsh_validation_runner.py --cwd D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --log-dir D:\Atlas\tasks\dsh-parity\atomic\runs\T1-CLI-BIN-DISPATCH-085-scan --timeout 480 --cleanup-timeout 10 -- python D:\Atlas\core\scripts\dsh_capability_audit.py --source D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --ledger D:\Atlas\tasks\dsh-parity\atomic --scan
```

Actual runner output: `{"duration_seconds":273.68799999999464,"leftover_count":0,"returncode":0,"status":"PASS","timed_out":false}`; exit 0. Reconciliation: pinned head unchanged, 14 `bin.ts` units, 13 MAPPED / 1 EXCLUDED, no missing decisions or dangling references. Global source inventory: 413,747 total / 408,180 unresolved; completion remains `INCOMPLETE`.

## Limits and next work

No Atlas CLI parity, live model, packaged Atlas desktop comparison, or superiority result is claimed. The unbundled source invocation's incomplete schema result remains visible above. Next: resolve the 60 indexed `profile-boot.ts` semantic obligations against exact consumers/tests; do not treat this dispatcher mapping as lifecycle completion.
