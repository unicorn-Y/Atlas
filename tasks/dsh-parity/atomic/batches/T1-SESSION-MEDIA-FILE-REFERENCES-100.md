# T1-SESSION-MEDIA-FILE-REFERENCES-100 — Media and file references

Status: `DONE_SCOPED` for pinned DSH source mapping and the executable host evidence recorded below. This is not Atlas parity, Task 1 completion, or a superiority result.

## Scope and dependencies

- Pinned DSH head: `d743267388641bc76f17c45ce8b4c231aed1d32c`.
- `packages/api/session-controller/src/media-references.ts`: 19 indexed semantic units.
- `packages/api/session-controller/src/file-references.ts`: 11 indexed semantic units.
- Direct tests: `tests/media-references.host.spec.ts`, `tests/file-references.host.spec.ts`.
- Dependencies: prior upload/receipt and public Session contracts; composed Cordis `connection`, `fs`, `attachments`, `fileReferences`, and `typert` services; Session-resolved Agent identity; filesystem byte-limit/error contracts.
- No Atlas product source was edited. Atlas route/provider parity remains an open paired-runtime obligation.

## Behavior and source obligations

`SessionMediaReferences` registers authenticated-connection `GET` and `HEAD /api/file` through a Cordis effect. The handler validates a non-empty absolute path with no NUL, resolves through the composed filesystem, selects MIME from the resolved display path with an octet-stream fallback, and carries private/no-store, nosniff, and sandbox CSP headers. HEAD stats without content reads, rejects missing/non-file/over-limit targets and only returns a length when known. GET uses bounded `readBytes` with the request abort signal, returns the complete body, and does not implement Range. Typed filesystem errors map to HTTP statuses; unexpected provider errors propagate. Disposal unregisters the route.

`SessionFileReferences` injects the composed `fileReferences` provider and `typert` service, exposes the `fileReferences` namespace, and returns `ctx.fileReferences.list(agent, query, signal)` directly. The host test verifies identity preservation for the resolved Agent, query, AbortSignal, and resulting candidate list.

All 30 source-index units have digest-bound `MAPPED` decisions. Two capability records group the media route and file-reference adapter. Three interaction edges record media route lifecycle, response safety, and Agent-scoped provider delegation. The source scan independently reconciled 30/30 target IDs, 30 unique decisions, zero duplicate target decisions, and zero target digest mismatches.

## Verification

Full focused command:

```text
pnpm exec vitest run packages/api/session-controller/tests/media-references.host.spec.ts packages/api/session-controller/tests/file-references.host.spec.ts --reporter=dot --no-file-parallelism
```

Actual output: `Test Files 1 failed | 1 passed (2); Tests 1 failed | 21 passed | 1 skipped (23); exit 1`. The single failure is `reads files and symlink targets outside the default cwd without a workspace registry`; Windows returned `EPERM` at `symlink()` setup before the symlink assertion. This remains unverified. The FIFO test is platform-skipped on Windows. No privilege or OS setting was changed.

Rerun excluding only the symlink case:

```text
pnpm exec vitest run packages/api/session-controller/tests/media-references.host.spec.ts packages/api/session-controller/tests/file-references.host.spec.ts --reporter=dot --no-file-parallelism -t "^(?!.*reads files and symlink targets outside the default cwd without a workspace registry)"
```

Actual output: `Test Files 2 passed (2); Tests 21 passed | 2 skipped (23); exit 0` (994ms). This confirms the non-symlink assertions, not the omitted symlink behavior.

Audit command:

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py --tb=short --basetemp C:\Users\25011\AppData\Local\Temp\atlas-session-media-file-100-ledger
```

Actual output: `41 passed, 5 warnings in 14.09s`; exit 0.

Full source scan:

```text
python core/scripts/dsh_validation_runner.py --cwd D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --log-dir D:\Atlas\tasks\dsh-parity\atomic\runs\T1-SESSION-MEDIA-FILE-REFERENCES-100-scan --timeout 480 --cleanup-timeout 10 -- python D:\Atlas\core\scripts\dsh_capability_audit.py --source D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --ledger D:\Atlas\tasks\dsh-parity\atomic --scan
```

Actual runner output: `{"duration_seconds":270.5780000000086,"leftover_count":0,"returncode":0,"status":"PASS","timed_out":false}`; supervisor exit 0. Scanner output: 413,747 semantic units / 406,817 unresolved, `INCOMPLETE`. The unresolved global source surface is not closed by this batch.

## Open obligations

- The symlink target test has not reached its assertion on this Windows host because symlink creation is denied (`EPERM`).
- The corresponding Atlas authenticated `/api/file` route and desktop consumer have not been exercised as a paired runtime path.
- Atlas file-reference discovery, workspace authorization, and cancellation have not been paired with the DSH Agent-scoped Remote contract.
- Task 1 global source inventory and Task 2 production OLDNEW runtime fixes remain open; no parity or superiority claim is made.
