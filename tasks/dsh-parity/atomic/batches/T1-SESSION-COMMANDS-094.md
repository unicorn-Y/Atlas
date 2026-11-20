# T1-SESSION-COMMANDS-094 — SessionCommandController host commands

Status: DONE_SCOPED for pinned source mapping and DSH acceptance evidence.

## Scope

- Pinned DSH head: `d743267388641bc76f17c45ce8b4c231aed1d32c`.
- Mapped all 120 indexed units in `packages/api/session-controller/src/commands.ts` to one Host command atom and four operation edges.
- Direct DSH consumers: create/fork, queue/attachment, upload, cold-session and model-selection Host suites.
- Atlas comparison was read-only. No Atlas production code changed.

## Contract crosswalk

`SessionCommandController` exposes `create`, `selectModel`, `rename`, `fork`, `prompt`, `attachment`, `updateQueue`, and `cancel`. Request validation separates create target metadata from workspace defaults, rejects conflicting targets, and returns typed failures for cold source, persistence, lineage, and Agent creation errors. Model selection and rename are explicit commands rather than mutations implicit in prompt submission.

Prompt validation requires actual user content; request identity, queue/steer placement, accepted/rejected receipts, supported image blocks and staged file citations are reconciled against the exact Agent/session generation. File upload is bounded, cancellable and session-bound. Upload/storage failures use the command error vocabulary. A receipt is only published for a still-current Agent; when prompt delivery fails or a queued occurrence is removed, the prior binding is restored or retired as required. Cancel returns an explicit result while matching the request/Agent state.

The capability has four consumer edges:

- create/fork target, lineage and cold-source handling;
- model selection and rename metadata;
- prompt/queue/steer/cancel request identity and retirement;
- bounded upload, image admission, file receipt binding and storage failures.

`commands-create-fork.host.spec.ts`, `commands-queue-attachment.host.spec.ts`, `commands-upload-file.host.spec.ts`, `session-cold.host.spec.ts`, and `session-models.host.spec.ts` exercise these operation families, including contradictory targets, cold resolution, cancellation during storage, Agent disposal, exact receipt ownership, queued removal and error mapping.

## Atlas comparison

Atlas has conversation/run routes, tool upload paths and queue/steer handling. This batch did not run a paired command matrix against the same DSH requests and outcomes, particularly for cold-source resolution, file receipt restoration/retirement and subagent lineage. The atom and edges stay `PARTIAL` / implementation `OPEN`. No parity or superiority claim is made.

## Focused verification

```text
pnpm exec vitest run packages/api/session-controller/tests/commands-create-fork.host.spec.ts packages/api/session-controller/tests/commands-queue-attachment.host.spec.ts packages/api/session-controller/tests/commands-upload-file.host.spec.ts packages/api/session-controller/tests/session-cold.host.spec.ts packages/api/session-controller/tests/session-models.host.spec.ts --reporter=dot --no-file-parallelism
```

Actual output: `Test Files 5 passed (5); Tests 102 passed (102); Duration 4.37s`; exit 0.

Audit-module command:

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py --tb=short --basetemp C:\Users\25011\AppData\Local\Temp\atlas-session-commands-094-ledger
```

Actual output: `41 passed, 5 warnings in 13.98s`; exit 0.

Full scan command:

```text
python core/scripts/dsh_validation_runner.py --cwd D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --log-dir D:\Atlas\tasks\dsh-parity\atomic\runs\T1-SESSION-COMMANDS-094-scan --timeout 480 --cleanup-timeout 10 -- python D:\Atlas\core\scripts\dsh_capability_audit.py --source D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --ledger D:\Atlas\tasks\dsh-parity\atomic --scan
```

Actual runner output: `{"duration_seconds": 269.01600000000326, "leftover_count": 0, "returncode": 0, "status": "PASS", "timed_out": false}`; supervisor exit 0. Reconciliation found 120/120 target decisions, zero missing/duplicate decisions and no digest/reference issues. Global inventory is 413,747 total / 407,330 unresolved and remains `INCOMPLETE`.
