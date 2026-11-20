# T1-CLI-ARGS-SEMANTICS-084 — resolve every indexed args.ts semantic unit

Status: DONE_SCOPED

## Files, dependency, and acceptance

- Pinned source reviewed at DSH head `d743267388641bc76f17c45ce8b4c231aed1d32c`: `apps/cli/src/args.ts`; tests: `apps/cli/tests/args.spec.ts`.
- Atlas comparison read `core/atlas/cli.py` and `core/tests/test_cli_headless.py`. No Atlas source changed.
- Ledger changes: semantic decisions, one open CLI gap atom, three interaction edges, generated index/completion, queue, report, progress.
- Dependency: `T1-CLI-ENTRY-SEMANTICS-083`.
- Acceptance: all 23 indexed units are MAPPED or evidenced EXCLUDED, with valid references; no Atlas parity/closure claim.

## Reviewed semantics

The 17 behavior/import/export/file-review units cover Commander import, `DshInvocation`, repeatable patch collection, repeated-profile rejection, Desktop reservation, `resolveBoot`, exported `parseDshArgs`, its main/help/plugin actions, and the whole file. Source evidence is recorded per unit with line span and relevant `args.spec.ts` test names.

Six `configuration_default` rows were false positives from the lexical `DEFAULT_RE` matching the word in CLI option names/error/help text (`--from-default-profile`, `--dump-default-config`). They are EXCLUDED with per-row reasons; the actual parser validations remain MAPPED under `resolveBoot`/`parseDshArgs`. No configuration default was inferred from these option names.

The Atlas Click CLI has separate commands and has no demonstrated equivalent for DSH profile shorthand, launcher/application argument boundary, profile-scoped plugin forwarding, Desktop reservation or boot-free profile dump modes. The new atom remains `status=PARTIAL`, `implementation_status=OPEN`.

## Test and audit evidence

The full pinned parser suite was run in the preceding batch with unchanged DSH source:

```text
pnpm exec vitest run apps/cli/tests/args.spec.ts --reporter=dot --no-file-parallelism
```

Actual output: `Test Files 1 passed (1); Tests 58 passed (58); Duration 341ms`; exit 0. No DSH source changed in this ledger-only batch.

After appending the 23 decisions, the full Atlas audit test module passed `41 passed, 5 warnings in 13.91s`, exit 0.

Full pinned index application:

```text
python core/scripts/dsh_validation_runner.py --cwd D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --log-dir D:\Atlas\tasks\dsh-parity\atomic\runs\T1-CLI-ARGS-SEMANTICS-084-scan --timeout 480 --cleanup-timeout 10 -- python D:\Atlas\core\scripts\dsh_capability_audit.py --source D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --ledger D:\Atlas\tasks\dsh-parity\atomic --scan
```

Actual runner result: `{"duration_seconds": 271.0789999999979, "leftover_count": 0, "returncode": 0, "status": "PASS", "timed_out": false}`. The post-scan check found 23 `apps/cli/src/args.ts` units: 17 MAPPED, six EXCLUDED; all MAPPED refs exist. Global completion changed from 408,217 to 408,194 unresolved out of 413,747 and remains `INCOMPLETE`. Scoped `git diff --check` exited 0.

## Limits

This is source semantic mapping only. DSH parser behavior was tested; no Atlas profile CLI feature was implemented or paired-run. CLI `bin.ts`, all other modules, global semantic closure, actual product parity, live, protocol, integration, and superiority gates remain open. Next source slice is the `bin.ts` dispatcher.
