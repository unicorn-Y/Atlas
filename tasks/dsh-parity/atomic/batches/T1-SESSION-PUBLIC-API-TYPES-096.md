# T1-SESSION-PUBLIC-API-TYPES-096 — public facade and request/event contracts

Status: DONE_SCOPED for pinned source mapping; the package-wide suite retains one environment-blocked symlink case.

## Scope

- Pinned DSH head: `d743267388641bc76f17c45ce8b4c231aed1d32c`.
- Mapped all 201 indexed semantic units: 107 from `src/index.ts` and 94 from `src/types.ts`.
- Two atoms separate the public remote-service composition root from its public request/result/event types; four edges cover facade construction, catalogs/workspace, commands and history/live/control streams.
- Read-only Atlas comparison: `core/atlas/api/application.py`, `app_services.py`, `runtime_ws_router.py` and `conversations_router.py`. No Atlas production code changed.

## Public facade

`SessionController` composes the Agent, command, history, catalog, workspace, and client/Host transport services from its Context, injected internals, and resolved Config. The config path applies the bounded list-work-slice default. The public service delegates identity inspection, list/search, create/model selection/default model/catalog, workspace capability/open/application listing, rename/fork/prompt/attachment/queue/cancel, history page/follow, projections and Host control stream operations. Method failures preserve each underlying typed result instead of flattening them into one facade error.

## Public contract types

`types.ts` defines branded session/request/cursor identities; ordinary and subagent addresses; observation/projection state; model selection/reasoning/catalog and skill catalog; list/search values and result/snippet bounds; each command request/result pair; workspace operations; durable event/header/surface metadata; page/follow requests and records; assistant attempt/baseline/frame; and control baseline/projection-update/frame unions. The types preserve optional fields and discriminated outcomes needed by Host and Client consumers.

## Consumer verification

Full package command:

```text
pnpm exec vitest run packages/api/session-controller/tests --reporter=dot --no-file-parallelism
```

Actual output: `Test Files 1 failed | 41 passed (42); Tests 1 failed | 957 passed | 1 skipped (959); Duration 31.62s`; exit 1. The single failure was `media-references.host.spec.ts > SessionMediaReferences /api/file > reads files and symlink targets outside the default cwd without a workspace registry`: Node `symlink()` failed with `EPERM` before the test reached its symlink assertions. The other 957 tests passed and one test was skipped. No system symlink privilege or global setting was changed, and this is not reported as an all-green package suite.

Audit-module command:

```text
python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py --tb=short --basetemp C:\Users\25011\AppData\Local\Temp\atlas-session-public-api-096-ledger
```

Actual output: `41 passed, 5 warnings in 13.96s`; exit 0.

## Atlas comparison and limits

This is a DSH API facade/type map plus DSH package consumer evidence. It does not prove equivalent Atlas route injection, websocket serialization, SDK types or renderer behavior. Both atoms/four edges remain `PARTIAL` / implementation `OPEN`; no parity/superiority claim is made. The platform-specific symlink test limitation is retained as an open verification item.

## Full source scan

Full scan command:

```text
python core/scripts/dsh_validation_runner.py --cwd D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --log-dir D:\Atlas\tasks\dsh-parity\atomic\runs\T1-SESSION-PUBLIC-API-TYPES-096-scan --timeout 480 --cleanup-timeout 10 -- python D:\Atlas\core\scripts\dsh_capability_audit.py --source D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness --ledger D:\Atlas\tasks\dsh-parity\atomic --scan
```

Actual runner output: `{"duration_seconds": 270.4219999999914, "leftover_count": 0, "returncode": 0, "status": "PASS", "timed_out": false}`; supervisor exit 0. Reconciliation found 201/201 target decisions, zero missing/duplicate decisions and no digest/reference issues. Global inventory is 413,747 total / 407,046 unresolved and remains `INCOMPLETE`.
