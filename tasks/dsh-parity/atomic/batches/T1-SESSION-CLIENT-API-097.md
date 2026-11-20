# T1-SESSION-CLIENT-API-097 — client application root and ISessions contract

Status: DONE_SCOPED for pinned source mapping and DSH acceptance evidence.

## Scope

- Pinned DSH head: `d743267388641bc76f17c45ce8b4c231aed1d32c`.
- Mapped all 58 indexed units: 30 in `src/client/index.ts`, 28 in `src/client/contract/sessions.ts`.
- Two atoms cover client remote application/lifecycle and the public session ownership/service interface; three edges cover apply generation, retain/release and session service operations.
- Atlas `backend-adapter/src/types.ts`, renderer event normalization and timeline projection were read only. No Atlas production code changed.

## Client application root

The client entry point applies session services to the shared remote client and binds session/control adapters to that connection generation. It delivers the connected callback once per generation, routes remote events into the object layer and keeps immediate control projection updates coherent with ready notifications and stream retries.

## `ISessions` and reference ownership

`SessionTarget` distinguishes ordinary `SessionId` from `SubagentAddress`. `SessionReference` represents a source-labelled retained Session with readiness and exact-once `release`/dispose. Retain options/information preserve caller source, abort/readiness and ownership state. `ISessions` exposes reference retain/lookup/release and typed list/search/create/fork/refresh/catalog/projection operations without collapsing failures or target identity.

## Consumer behavior

`client-apply.client.spec.ts` exercises remote event routing and connection-generation callbacks. `manager.client.spec.ts`, `sessions-service.client.spec.ts` and `reference-ownership.client.spec.ts` cover address-bound sessions, source-counted retention, readiness and disposal. `session-remote-rejection.client.spec.ts` covers typed failure propagation without inventing a successful session.

## Atlas comparison

The mapped DSH client root owns remote generation subscriptions and caller-labelled Session leases. Atlas has a backend adapter, renderer event normalization and timeline projection, but this batch did not run a paired remote reconnect, multiple retain-source, abort/release, subagent, or visible renderer trace. Both atoms and all three edges remain `PARTIAL` / implementation `OPEN`; no parity or superiority claim is made.

## Verification

```text
pnpm exec vitest run packages/api/session-controller/tests/client-apply.client.spec.ts packages/api/session-controller/tests/manager.client.spec.ts packages/api/session-controller/tests/sessions-service.client.spec.ts packages/api/session-controller/tests/reference-ownership.client.spec.ts packages/api/session-controller/tests/session-remote-rejection.client.spec.ts --reporter=dot --no-file-parallelism
```

Actual output: `Test Files 5 passed (5); Tests 167 passed (167); Duration 5.53s`; exit 0. Expected connection-retry diagnostics were emitted by the client-generation tests.

Audit module:

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py --tb=short --basetemp C:\Users\25011\AppData\Local\Temp\atlas-session-client-api-097-ledger
```

Actual output: `41 passed, 5 warnings in 13.99s`; exit 0.

Full scan command:

```text
python core/scripts/dsh_validation_runner.py --cwd D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --log-dir D:\Atlas\tasks\dsh-parity\atomic\runs\T1-SESSION-CLIENT-API-097-scan --timeout 480 --cleanup-timeout 10 -- python D:\Atlas\core\scripts\dsh_capability_audit.py --source D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --ledger D:\Atlas\tasks\dsh-parity\atomic --scan
```

Actual runner output: `{"duration_seconds": 270.48500000001513, "leftover_count": 0, "returncode": 0, "status": "PASS", "timed_out": false}`; supervisor exit 0. Reconciliation found 58/58 target decisions, zero missing/duplicate decisions and no digest/reference issues. Global inventory is 413,747 total / 406,988 unresolved and remains `INCOMPLETE`.
