# T1-SCHEDULE-RUNTIME-INTERVAL-ZONE-077F

Status: `DONE_SCOPED` for interval and time-zone test-source obligations only.

## Scope and behavior groups

- Pinned DSH head: `d743267388641bc76f17c45ce8b4c231aed1d32c`.
- Source: `packages/client/ui-schedule/tests/task-manager-page.client.spec.tsx:1872-2121`; 92 semantic units.
- Test shape: five direct `it(...)` declarations and six `it.each(...)` declarations. Their parameter rows are 3 + 2 + 2 + 2 + 2 + 2 = 13 variants.
- Dependency: 077E interval/date/time source map.

Mapped obligations cover fractional-hour conversion to whole seconds and unit display; refusal below the interval floor and for nonnumeric values; local rejection of malformed stored dates/clocks; timezone edits interpreted and committed as the expected absolute target; and IANA zone menu ordering, system-zone marking, UTC/recent inventory, selection promotion and query reset.

## Integrity and validation

```json
{"pinned_head":"d743267388641bc76f17c45ce8b4c231aed1d32c","digest_match":true,"units":92,"decisions":92,"mapped":92,"duplicates":0,"missing_units":0,"missing_refs":0,"direct_it":5,"it_each":6,"unresolved_before":409360}
```

From `D:\Atlas\core`:

```text
python -m pytest -q --collect-only -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py
38 tests collected in 0.31s

python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py
38 passed, 5 warnings in 12.77s
```

Ledger-tool tests passed; DSH tests and Atlas UI/runtime were not executed.

## Remaining obligations

- Global source ledger after this slice: 413,747 total / 409,268 unresolved.
- Later TaskDetail/card scenarios, actual test execution and Atlas parity/superiority remain open. Record: `tasks/dsh-parity/atomic/batches/T1-SCHEDULE-RUNTIME-INTERVAL-ZONE-077F.md`.
