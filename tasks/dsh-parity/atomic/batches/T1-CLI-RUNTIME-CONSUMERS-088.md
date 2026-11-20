# T1-CLI-RUNTIME-CONSUMERS-088 — plugin consent and process shutdown

Status: DONE_SCOPED for source mapping and pinned DSH acceptance.

## Scope and evidence

- Pinned DSH head: `d743267388641bc76f17c45ce8b4c231aed1d32c`.
- Reviewed all 21 indexed units in `apps/cli/src/plugin.ts` and all 25 indexed units in `apps/cli/src/process-shutdown.ts` against their focused tests and the Atlas CLI/desktop lifecycle surfaces.
- Each source unit has a digest-bound decision in `atomic/semantic-decisions.jsonl`; file-level contracts are `T1-DSH-CLI-PLUGIN-SEMANTICS-088` and `T1-DSH-CLI-PROCESS-SHUTDOWN-088`. The related interaction edges are `EDGE-T1-DSH-CLI-PLUGIN-CONSENT-088` and `EDGE-T1-DSH-CLI-SHUTDOWN-088`.

## Unit crosswalk

### Plugin command (`plugin.ts`, 21 units)

- Imports and profile-context defaults (lines 2–8, 47): package operations, installation anchor, profile templates/default bundles, atomic file lock, filesystem and path operations are dependencies of the command contract, not standalone user features.
- `requireDesktopProfile` and its typed contract (lines 10, 90): the reserved Desktop profile must already exist; failures return a diagnostic and do not initialize or replace Desktop state.
- `versionCommand` and its function contracts (lines 17, 45): only the three DSH-owned exemption verbs are intercepted; argument parsing rejects duplicates, unknown flags, missing exact package/runtime versions, wildcard versions and missing `--accept-risk`. Grant warns before mutation, modifies profile compatibility metadata under the package manifest lock, and does not invoke pnpm. List reads compatibility metadata, emits warnings, and writes JSON; revoke removes only the exact pair.
- `runPlugin` and callbacks (lines 70, 93, 103): Desktop initialization is checked before work; ordinary plugin arguments remain pnpm-owned; existing profile compatibility warnings are reported; package manager command/environment are installation-supplied; stdout/stderr stream separately; `127`, package incompatibility hints, diagnostics and Git-hosted build-script guidance are preserved.
- Tests: `plugin.spec.ts` checks exact consent, malformed input, no-pnpm metadata operations, warning/diagnostic behavior, Desktop profile invariants and lock behavior. `plugin-compatibility.expected.e2e.ts` checks the actual built CLI through refusal, startup denial, explicit consent, install, startup admission and revoke.

### Process shutdown (`process-shutdown.ts`, 25 units)

- `PROCESS_SHUTDOWN_TIMEOUT_MS` and the public controller contract (lines 4–13): 5-second default grace; natural shutdown is awaitable; interrupts are escalatory.
- `createProcessShutdown` and its nested contracts (lines 22–64): one disposal promise is coalesced; timeout forces exit once; natural completion records the exit code once; disposal rejection forces exit; the timer clears on terminal settlement.
- Public `shutdown` and `interrupt` implementations (lines 66–72): normal repeated shutdown joins the original result; first signal starts a drain, repeated signal forces exit; signal-started disposal forces exit after drain.
- Tests: `process-shutdown.spec.ts` checks natural completion, rejection, default `process.exitCode`, 5-second/custom bound, Ctrl+C escalation, signal-started drain, coalescing and one-shot behavior.

## Atlas comparison

Atlas has marketplace/plugin operations and several shutdown paths, including CLI daemon controls and FastAPI lifespan teardown. This mapping did not establish DSH-equivalent profile-scoped pnpm operations, exact risk-consent lifecycle, or a shared bounded CLI process-exit controller. Both capability atoms remain `PARTIAL` with `implementation_status: OPEN`; no Atlas parity or superiority is claimed and no product code changed.

## Verification

Focused unit command:

```text
pnpm exec vitest run apps/cli/tests/plugin.spec.ts apps/cli/tests/process-shutdown.spec.ts --reporter=dot --no-file-parallelism
```

Actual output: `Test Files 2 passed (2); Tests 31 passed (31); Duration 1.13s`; exit 0.

Built CLI compatibility command:

```text
pnpm run test:expected -- apps/cli/tests/plugin-compatibility.expected.e2e.ts --reporter=dot --no-file-parallelism
```

Actual output: `Test Files 1 passed (1); Tests 1 passed (1); Duration 5.93s`; exit 0.

Atlas audit module:

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py --tb=short --basetemp C:\Users\25011\AppData\Local\Temp\atlas-cli-runtime-088-ledger
```

Actual output: `41 passed, 5 warnings in 14.37s`; exit 0.

Full scan command:

```text
python core/scripts/dsh_validation_runner.py --cwd D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --log-dir D:\Atlas\tasks\dsh-parity\atomic\runs\T1-CLI-RUNTIME-CONSUMERS-088-scan --timeout 480 --cleanup-timeout 10 -- python D:\Atlas\core\scripts\dsh_capability_audit.py --source D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --ledger D:\Atlas\tasks\dsh-parity\atomic --scan
```

Actual runner output: `{"duration_seconds": 270.625, "leftover_count": 0, "returncode": 0, "status": "PASS", "timed_out": false}`; supervisor exit 0. Post-scan check: 46/46 target units have digest-bound MAPPED decisions, zero missing; global index is 413,747 total / 408,057 unresolved and `INCOMPLETE`.

This source mapping does not close Task 1, Task 2, live-model authorization, or superiority gates.
