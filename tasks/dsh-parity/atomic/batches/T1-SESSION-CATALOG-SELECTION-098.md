# T1-SESSION-CATALOG-SELECTION-098 — catalog, selection projection and archive gate

Status: DONE_SCOPED for pinned source mapping and DSH acceptance evidence.

## Scope

- Pinned DSH head: `d743267388641bc76f17c45ce8b4c231aed1d32c`.
- Mapped 71 indexed units: `catalog.ts` 27, `skill-catalog.ts` 18, `model-selection-projection.ts` 14, `archived-session-gate.ts` 12.
- Four atoms and four edges isolate subagent catalog, skill listing, model-selection projection/one-shot consumption, and archived-session command gating.
- Atlas model/router/project instruction sources were read only; no product code changed.

## Contract crosswalk

The Host subagent catalog serves complete parent-scoped values from maintained live registry state or cold persisted metadata. It uses migration state to defer unsafe cold reads, keeps parent identity/not-found distinct from cancellation, and does not republish an Agent that outlives its Session registration. The skill catalog is a scoped typed list operation with an abort signal and no Session or prompt mutation.

The model-selection projection validates persisted selection state, updates the selected model projection, distinguishes default/preset/reasoning attributes, and consumes a pending selection only when the exact next request matches. The archive gate discovers archived Session ancestry for the current Agent and blocks interactive command paths beneath that archive without classifying ordinary active Sessions as archived.

The five direct Host consumer suites cover subagent catalog and parent state, model catalog/projection, preset resolution, cold Session behavior and archived-command gating.

## Atlas comparison

This maps DSH catalog ownership, model selection and archive gate behavior. Atlas has model routing, project instructions and runtime/session state, but this batch did not compare the same model-selection persistence, catalog generation, archived ancestry and blocked command cases through Atlas API/SDK/desktop. Atoms and edges remain `PARTIAL` / implementation `OPEN`; no parity or superiority claim is made.

## Verification

```text
pnpm exec vitest run packages/api/session-controller/tests/subagent-catalog.host.spec.ts packages/api/session-controller/tests/session-models.host.spec.ts packages/api/session-controller/tests/session-presets.host.spec.ts packages/api/session-controller/tests/session-cold.host.spec.ts packages/api/session-controller/tests/archived-session-gate.host.spec.ts --reporter=dot --no-file-parallelism
```

Actual output: `Test Files 5 passed (5); Tests 68 passed (68); Duration 4.23s`; exit 0.

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py --tb=short --basetemp C:\Users\25011\AppData\Local\Temp\atlas-session-catalog-098-ledger
```

Actual output: `41 passed, 5 warnings in 13.84s`; exit 0.

Full scan command:

```text
python core/scripts/dsh_validation_runner.py --cwd D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --log-dir D:\Atlas\tasks\dsh-parity\atomic\runs\T1-SESSION-CATALOG-SELECTION-098-scan --timeout 480 --cleanup-timeout 10 -- python D:\Atlas\core\scripts\dsh_capability_audit.py --source D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --ledger D:\Atlas\tasks\dsh-parity\atomic --scan
```

Actual runner output: `{"duration_seconds": 271.81299999999464, "leftover_count": 0, "returncode": 0, "status": "PASS", "timed_out": false}`; supervisor exit 0. Reconciliation found 71/71 target decisions, zero missing/duplicate decisions and no digest/reference issues. Global inventory is 413,747 total / 406,917 unresolved and remains `INCOMPLETE`.
