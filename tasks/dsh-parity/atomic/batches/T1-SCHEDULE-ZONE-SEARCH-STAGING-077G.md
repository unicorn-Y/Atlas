# T1-SCHEDULE-ZONE-SEARCH-STAGING-077G

Status: `DONE_SCOPED` for the pinned zone-search and staged-edit source block only.

## Scope and mapped behavior

- Pinned DSH head `d743267388641bc76f17c45ce8b4c231aed1d32c`.
- Source `packages/client/ui-schedule/tests/task-manager-page.client.spec.tsx:2122-2371`, 114 semantic units.
- Test shape: 13 direct `it(...)` and five `it.each(...)` declarations with ten data rows.
- Depends on 077F interval/time-zone map.

Five groups record exact assertions for hidden IANA ID/localized label/UTC-offset search and deduplicated labels; current/system zone ordering and marking; stored zones outside minimal inventory fallback; selection/no-op/staged-edit/Cancel/Escape behavior; localized zone search and one-shot target/payload interpretation; and separate whole-second date/time display.

## Integrity and validation

```json
{"pinned_head":"d743267388641bc76f17c45ce8b4c231aed1d32c","digest_match":true,"units":114,"mapped":114,"duplicates":0,"missing_units":0,"missing_refs":0,"direct_it":13,"it_each":5,"unresolved_before":409268}
```

From `D:\Atlas\core`:

```text
python -m pytest -q --collect-only -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py
38 tests collected in 0.30s

python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py
38 passed, 5 warnings in 12.93s
```

Only audit-tool tests ran. DSH tests and Atlas UI/runtime did not run.

## Remaining obligations

- Global source ledger: 413,747 total / 409,154 unresolved after this mapping.
- Remaining TaskDetail card tests and all runtime parity/superiority are open. Record: `tasks/dsh-parity/atomic/batches/T1-SCHEDULE-ZONE-SEARCH-STAGING-077G.md`.
