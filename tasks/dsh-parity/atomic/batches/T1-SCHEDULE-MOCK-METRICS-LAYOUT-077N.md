# T1-SCHEDULE-MOCK-METRICS-LAYOUT-077N

Status: `DONE_SCOPED` for mock metrics/layout test-source assertions only.

## Scope

- Pinned DSH head `d743267388641bc76f17c45ce8b4c231aed1d32c`.
- Source: `packages/client/ui-schedule/tests/task-manager-page.client.spec.tsx:3714-3923`, 113 semantic units and six direct test declarations.
- Dependency: name/instruction and metrics test-source map 077M.

Five groups record mock notice layout, empty state and heading level, catalog column/heading/search/row metrics, title typography compared with the Plugins page, and detail-card/l4 edge plus breakpoint gutter assertions. These are mock/style assertions. No production visual output was measured.

## Integrity and validation

```json
{"pinned_head":"d743267388641bc76f17c45ce8b4c231aed1d32c","digest_match":true,"units":113,"mapped":113,"duplicates":0,"missing_units":0,"missing_refs":0,"direct_it":6,"it_each":0,"unresolved_before":408522}
```

From `D:\Atlas\core`:

```text
python -m pytest -q --collect-only -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py
38 tests collected in 0.30s

python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py
38 passed, 5 warnings in 12.84s
```

The audit-tool tests ran; the DSH UI and Atlas UI did not.

## Remaining obligations

- Global ledger: 413,747 total / 408,409 unresolved after this mapping.
- This source does not prove production metrics flow or visual parity. Deletion, timing picker and runtime comparisons remain open. Record: `tasks/dsh-parity/atomic/batches/T1-SCHEDULE-MOCK-METRICS-LAYOUT-077N.md`.
