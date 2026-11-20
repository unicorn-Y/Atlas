# T1-SESSION-AGENT-095 — Agent identity, ownership and creation

Status: DONE_SCOPED for pinned source mapping and DSH acceptance evidence.

## Scope

- Pinned DSH head: `d743267388641bc76f17c45ce8b4c231aed1d32c`.
- Mapped all 83 indexed units in `packages/api/session-controller/src/agent.ts` to one capability atom and four operation edges.
- Direct Host consumers: `agent.host.spec.ts` and `subagent-catalog.host.spec.ts`.
- Atlas `agent/__init__.py`, `atlas_runtime.py` and `run_phases.py` were read-only comparison sources; no Atlas production code changed.

## Contract crosswalk

`ApiSessionAgentController` separates ordinary and subagent identity errors, distinguishing not-found, ownership mismatch, cwd/preset conflict, writer-held, busy and unexpected failure. `resolveAgent` and `resolveObservedAgent` do not fabricate an Agent from incomplete metadata: they inspect cold state, validate observations, try the retained/live registry where permitted, resume only a matching persisted identity, and preserve diagnostics. Races after resume/create are rechecked against returned Agent ownership and cwd.

`ensureSession` requires the projected activation observations before creating or resuming an Agent and single-flights concurrent callers. A model-selection projection is consumed only by a matching next request and only once; a reasoning-free request does not consume a selection that does not exactly match. Parent/subagent descriptors are checked independently of child catalog availability. Live parent catalog values come from maintained registry state; cold catalog reads respect migration state, and an Agent outliving Session registration is not republished as an active Session.

Direct tests include resume/creation races, invalid observations, exact cwd and preset validation, writer contention classification, activation projection requirements, one-shot model selection, and cold/live subagent catalog and parent validation.

## Atlas comparison

This maps the DSH Session Controller’s Agent resolver and ownership boundary. Atlas has corresponding runtime/orchestrator and subtask machinery, but this batch does not pair the two systems under the same cold/live identity, concurrent create, resume, ownership, or model-selection cases. The atom and four edges remain `PARTIAL` / implementation `OPEN`; no parity or superiority claim is made.

## Focused verification

```text
pnpm exec vitest run packages/api/session-controller/tests/agent.host.spec.ts packages/api/session-controller/tests/subagent-catalog.host.spec.ts --reporter=dot --no-file-parallelism
```

Actual output: `Test Files 2 passed (2); Tests 28 passed (28); Duration 2.23s`; exit 0.

Audit-module command:

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py --tb=short --basetemp C:\Users\25011\AppData\Local\Temp\atlas-session-agent-095-ledger
```

Actual output: `41 passed, 5 warnings in 13.83s`; exit 0.

Full scan command:

```text
python core/scripts/dsh_validation_runner.py --cwd D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --log-dir D:\Atlas\tasks\dsh-parity\atomic\runs\T1-SESSION-AGENT-095-scan --timeout 480 --cleanup-timeout 10 -- python D:\Atlas\core\scripts\dsh_capability_audit.py --source D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --ledger D:\Atlas\tasks\dsh-parity\atomic --scan
```

Actual runner output: `{"duration_seconds": 281.35899999999674, "leftover_count": 0, "returncode": 0, "status": "PASS", "timed_out": false}`; supervisor exit 0. Reconciliation found 83/83 target decisions, zero missing/duplicates and no digest/reference issues. Global inventory is 413,747 total / 407,247 unresolved and remains `INCOMPLETE`.
