# T1-SCHEDULE-PAGE-WIRING-074A

Status: `DONE_SCOPED` for the selected production page and activation source units. This is source mapping, not Atlas schedule parity.

## Scope and source boundary

- Pinned DSH checkout: `D:\ENGINE-V3-UPSTREAM-20261011\deepseek-harness`, head `d743267388641bc76f17c45ce8b4c231aed1d32c`.
- Mapped 130 semantic units in five bounded source selections: `TaskManagerPage.tsx` (48), client `index.ts` (75), node `index.ts` (3), package manifest export defaults (2), and only the `ui-schedule` ID/name pair in `cordis.patch.yml` (2).
- `TaskDetail.tsx` is deliberately separated into the next source batch because it has 356 indexed semantic obligations. The stylesheet and page/detail behavior test files are not covered by this batch.

## Mapped behavior

- The page receives a Host catalog observable and injected retry/new-session/detail actions. It keeps search, status filter, and selected task as separate local state; filters against prompt, Session ID and task name; sorts by scheduled time; displays host-relative time and an explicit rule zone when it differs.
- Loading/error feedback and the three empty states are catalog-aware. Selection reconciles only after an authoritative `ready` catalog read. Escape closes the detail only if a modal confirmation or a consuming dropdown has not already taken the key. Focus returns to the selecting row, or the page heading when that row disappeared.
- Rows expose active/inactive state, frequency and active next-run time, and bind accessible detail ids. Choosing a row resets the selected detail tab to `rule`. The page has no task-creation form; both creation actions start a Session.
- Browser `apply` registers dictionaries and one shared Host catalog backed by `remote.schedule.catalog/delete`, `schedule/changed`, and connection reset. Deletions report through a shared toast source. Update forwards compare-and-update and forces a catalog read newer than the request ordinal for accepted or stale/conflict outcomes. History uses the remote history API; original Session navigation checks current Session/workspace metadata before opening.
- Client slots activate the main Tasks page, the right-sidebar task tab and title with per-tab/per-Session bindings, the settled schedule-create turn-tail card, a per-Session header catalog, and shared-catalog Session row mark/hover. The selected web Cordis entry activates package `@deepseek-ai/dsh-client-ui-schedule` as `ui-schedule`. The node `apply()` is intentionally empty; the manifest exposes distinct root and `./client` JS/type entrypoints and declares web platform injection dependencies.
- Each of the 130 source decisions links to a named source capability and interaction edge. Capability rows preserve implementation status `OPEN`.

## Verification

The actual ledger unit module was collected and run from `D:\Atlas\core`:

```text
python -m pytest -q --collect-only -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py
38 tests collected in 0.30s

python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py
38 passed, 5 warnings in 12.80s
```

A bounded direct check against the existing pinned source index returned:

```json
{"pinned_head":"d743267388641bc76f17c45ce8b4c231aed1d32c","selected_semantic_units":130,"selected_mapped":130,"selected_files_digest_match":5,"missing_references":0,"global_total":413747,"global_unresolved":410904,"per_file":{"packages/bundle/web-app/cordis.patch.yml":2,"packages/client/ui-schedule/package.json":2,"packages/client/ui-schedule/src/client/TaskManagerPage.tsx":48,"packages/client/ui-schedule/src/client/index.ts":75,"packages/client/ui-schedule/src/index.ts":3}}
```

An attempted full `scan` did **not** complete: TypeScript AST extraction exhausted the Node subprocess's ~4 GiB heap and exited 1 after about 87 seconds. Its stderr reported `Ineffective mark-compacts near heap limit`. No success is inferred from that failed scan. The selected-file digest/reference check and ledger unit tests passed independently. No DSH application tests, Atlas schedule runtime, desktop page, or real model were exercised.

## Remaining obligations

- Task 1 still has 410,904 unresolved source units, including the full `TaskDetail.tsx` (356 units), stylesheet, page/detail tests, browser/E2E consumers, shared schedule service/controller, runtime installation and platform behavior.
- Atlas schedule page implementation, API wiring, visible desktop behavior and all parity/superiority gates remain open.
