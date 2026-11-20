# T1-CLI-CONFIG-PROJECTIONS-087 — resolve YAML and schema inspection

Status: DONE_SCOPED

## Scope

- Pinned source head: `d743267388641bc76f17c45ce8b4c231aed1d32c`.
- Reviewed all 17 indexed units across `apps/cli/src/dump-config.ts` and `dump-config-schema.ts`, their `bin.ts`/`profile-boot.ts` consumers, relevant acceptance tests, and Atlas `core/atlas/cli.py` / `desktop_entry.py`.
- Changed only the parity ledger, generated source-index/completion, queue, report and progress. No DSH upstream or Atlas product source was changed.
- Dependencies: CLI dispatch 085 and profile lifecycle 086.

## Contract mapped

All 17 units are MAPPED, with digest and atom/edge references verified. The YAML command calls `prepareProfile` but never mounts the profile; the `defaultOnly` recovery route excludes profile, home and argv layers and does not parse those files. Normal projection labels bundle, profile, home and invocation overlays in order. JSON Schema shares layer collection, imports trusted module code for schema metadata but does not apply plugins or evaluate `!!js`; it restores `stdout.write` in `finally`, emits JSON on stdout and source diagnostics on stderr, and sets exit code 1 when collection is incomplete. The Atlas counterpart remains explicitly open.

## Verification

The exact pinned schema acceptance was run in batch 085 on unchanged source:

```text
pnpm run test:expected -- apps/cli/tests/dump-config-schema.expected.e2e.ts --reporter=dot --no-file-parallelism
```

Actual output: `Test Files 1 passed (1); Tests 11 passed (11); Duration 13.43s`; exit 0. It includes both schema and YAML branches, native carrier handling, malformed/unsupported diagnostics, no plugin apply/`!!js`, incomplete exit behavior, and patch module resolution.

Pinned built-bin projection evidence was also run in batch 085 on the same immutable head:

```text
pnpm run test:e2e -- apps/cli/tests/built-bin.e2e.ts -t "requires a profile and rejects removed flags|routes help and usage errors without activating startup-dependent rows|fails loud on a nonexistent profile with the plugin-command hint|creates a custom profile from a shipped template before booting it|forwards CLI authentication and stdin through pnpm while preserving its exit code|prints the app's own help|prints the headless profile without Host or browser layers|prints the exact standalone sdk-minimal tree without dsh-base|composes the profile user layer and a --patch overlay in order" --reporter=dot --no-file-parallelism
```

Actual output was `Tests 8 passed | 25 skipped (33); Duration 21.98s`, exit 0. Additional pinned runs passed the custom template/unknown-source cases (`2 passed | 31 skipped; 7.61s`) and the custom-template YAML projection (`1 passed | 32 skipped; 1.12s`). These results and collection details are in `T1-CLI-BIN-DISPATCH-085.md`.

Ledger module after this batch's decisions:

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py --tb=short --basetemp C:\Users\25011\AppData\Local\Temp\atlas-cli-projections-087-ledger
```

Actual output: `41 passed, 5 warnings in 13.86s`; exit 0.

Full pinned scan:

```text
python core/scripts/dsh_validation_runner.py --cwd D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --log-dir D:\Atlas\tasks\dsh-parity\atomic\runs\T1-CLI-CONFIG-PROJECTIONS-087-scan --timeout 480 --cleanup-timeout 10 -- python D:\Atlas\core\scripts\dsh_capability_audit.py --source D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --ledger D:\Atlas\tasks\dsh-parity\atomic --scan
```

Actual runner output: `{"duration_seconds":271.9679999999935,"leftover_count":0,"returncode":0,"status":"PASS","timed_out":false}`; exit 0. The final reconciliation is 17 indexed projection units / 17 decisions / no missing or invalid digest/ref. Global source index is 413,747 total / 408,103 unresolved; completion stays `INCOMPLETE`.

## Limits

No live model, Atlas projection implementation, packaged Atlas Desktop proof, parity or superiority is claimed. A separate unbundled source-tree schema invocation in batch 085 returned incomplete with native Loader carrier diagnostics; the official fixture-backed packaged acceptance passed and both observations are retained separately. Continue the CLI consumer family and return to Task2 uncovered product edges.
