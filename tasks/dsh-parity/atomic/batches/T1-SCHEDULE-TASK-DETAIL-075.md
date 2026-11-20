# T1-SCHEDULE-TASK-DETAIL-075

Status: `DONE_SCOPED` for the production `TaskDetail.tsx` source obligations. This maps DSH source behavior only; it does not prove Atlas schedule parity.

## Scope

- Pinned source: `D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness`, head `d743267388641bc76f17c45ce8b4c231aed1d32c`.
- Mapped all 356 indexed semantic units in `packages/client/ui-schedule/src/client/TaskDetail.tsx` to 11 capability groups and four provider/consumer edges.
- Read-only semantic dependencies include `TaskManagerPage/useTaskDetail`, the Schedule Remote/catalog contracts, timing/cron/format helpers, Session/workspace metadata and UI primitives. No source files in the pinned DSH checkout were changed.
- The 43-test detail suite (corrected by direct declaration count in batch 076), the 158-case page suite, CSS, and the referenced helper source files are separate source obligations and are not closed by this row.

## Production behavior map

- The shared `useTaskDetail` owner resets the draft, tab and deletion confirmation when selected task ID changes. It prefers the authoritative catalog row, but retains an owner-reported draft when a save is pending/failed or confirmed deletion is waiting for refreshed catalog state.
- `TaskDetail` reads current sessions/workspaces, gates original-session navigation on `sessionLinkState`, omits the redundant link when already hosted inside the same Session, and uses `ResizeObserver` to compact the linked-session control while preserving accessible names and keyboard focus. The panel itself receives focus without scrolling when task identity changes.
- Draft state is keyed by `sessionId + taskId`. Submission generations and mounted/current-identity checks prevent an old async update response from overwriting the task now shown. Refresh merge preserves changed draft fields, accepts untouched fields from the refreshed record, treats weekly/weekdays as one Host rule, and makes inactive tasks read-only. Confirmed delete is retained until catalog acknowledgement; a missing authoritative row calls `onDeleted`.
- Save locally validates trimmed title (1–120 chars), non-empty prompt, ISO date round-trip, time shape, minimum 60-second interval, and parsed cron. It sends the complete expected timing snapshot and only includes content/timing fields that changed. Rejected/throwing requests show a generic unknown error; typed Host error codes go through `timingError` with conflict/not-found overrides. History uses the injected loader; retry stays owned by the catalog source.
- Rule choices are weekly, weekdays, daily, elapsed every second/minute/hour, once, and cron. A new elapsed rule seeds at 3,600 seconds; interval labels preserve exact whole-hour/minute representation and the saved value remains seconds. ISO weekdays are Monday-first; weekdays is Monday–Friday. Weekly rules retain edited weekday sets across a detour through a rule kind without weekdays. Clock-time rule changes carry the shown local time/zone when appropriate; weekly weekday seeding uses the occurrence in that zone. Invalid zone/date parsing has a UTC calendar fallback at `zonedWeekday`.
- The timing serializer maps once→`at`, interval→`every_seconds`, clock rules→daily/weekly with trimmed zone and seconds, and cron→expression/zone. Cron editor has monthly/weekly/daily/hourly/minutely/raw shapes, five-minute default step, date/weekday selections and bounded steppers. The native schedule package entry is type-only in the browser and the UI uses the Schedule client contract.
- The capability split is exact by source line ranges: props/defaults; owner state; session/layout; draft refresh reconciliation; recurrence transitions; save/delete; tabs and detail view; rule conversion/validation; concurrent draft merge; rule editor; cron editor. All 356 decisions bind to pinned digests and existing ledger atom/edge references; implementation status remains `OPEN`.

## Verification

The bounded selected-source integrity check returned:

```json
{"pinned_head":"d743267388641bc76f17c45ce8b4c231aed1d32c","file_digest_match":true,"task_detail_units":356,"task_detail_mapped":356,"missing_references":0,"global_total":413747,"global_unresolved":410548}
```

Ledger tests were explicitly collected and run from `D:\Atlas\core`:

```text
python -m pytest -q --collect-only -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py
38 tests collected in 0.30s

python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py
38 passed, 5 warnings in 12.59s
```

The global AST `scan` remains unverified after the separate batch 074A run failed closed at the TypeScript subprocess's ~4 GiB heap limit. This batch did not retry that scan. No DSH component tests, Atlas schedule runtime, browser, or real model were executed.

## Remaining obligations

- 410,548 source semantic units remain unresolved globally. In this family, tests, styles, `TaskDetail` dependencies and browser/platform consumers remain open.
- Atlas Schedule implementation and cross-component superiority have not been established.
