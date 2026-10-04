# ATLAS-H1-CORE-HARDENING execution ledger

2026-10-04, controller: Codex; workers: gpt-6-luna, high.

- Synced main to `9adfeb88acfd260b566ca75ef64bf6b8a6ccfbb1`; previous local CURRENT was stale.
- H0.1: preserved 36 source/test/prototype files, unchanged, in `wip/host-uncommitted-2026-10-04` at `a2c200c`; pushed successfully.
- Generated desktop build artifacts, live runtime databases, caches and engine home remain untouched in `D:\Atlas`. They are not source changes and are not uploaded to GitHub.
- Implementation runs on clean main in `D:\Atlas-h1-core-hardening`; immutable measurement checkout is `D:\Atlas-h1-baseline` at `9adfeb8`. Host files are retained in place.
- H0.2 accepted measurement script: controller independently reproduced seven helper tests (0.18s). Before JSON is in `tasks/results/ATLAS-H1-baseline.json`. Owner backend_verify now implements H4 routing.
- H5 owner: contract_review (server, new API modules, AppServices, route snapshot).
- H10.1 structure: frontend_verify completed markers, default unit selection, xdist/retry dependencies and live gate. Controller independently reproduced six lane tests, exit 0, 6 passed (0.17s). Collection accounts for all 2040 tests: 1876 unit, 163 integration, one desktop; live fixtures are still pending H10.2. Full lane timing remains pending runtime hardening.
- Frontend baseline: clean checkout, 155 tests passed, wall time 5.9s; no frontend application implementation changes.
- H5 snapshot review found FastAPI lazy included routers omitted by the initial flatten helper. Actual baseline runtime count is 391 HTTP and three WebSocket routes, independently revalidated through effective route contexts. Snapshot completeness is being repaired against the frozen baseline before further acceptance. AppServices and actual runtime state classes are moving to per-app dependencies; production lifecycle DI and server size are not yet accepted.
- H0.2 measured cold start 10.1746/10.1577/9.0467 seconds (median 10.1577), 22 successful real AIAgent/FakeLLM turns with 22 constructions and 22 MCP registrations. A real five-second model HTTP wait caused 197 loop iterations and 0.0625 process CPU seconds. RSS after 20 further turns rose 249856 bytes. Probe teardown closed resources successfully.
- The full pre-change backend run recorded 2009 passed, nine failed, nine skipped, controller wall 1970.7611 seconds. It used the host Hermes editable source with three pre-existing dirty files, separately identified from the clean Hermes fork used for runtime metrics. Two non-Git failure cases were caused by the controller choosing a pytest temp directory within a Git checkout: an external-temp rerun passed both (6.66s). Raw full-suite failure counts remain unchanged.
- A new worker spawn was rejected by the runtime thread limit after H10.1 delivery. The completed worker was reactivated as H1 owner, preserving three concurrent workers. H1 owns the clean Hermes fork and Atlas Hermes adapter/tool registration; H5 retains exclusive server/API ownership.
- Controller H7 channel bridge implementation shares the desktop approval future, processes admitted/deduplicated channel control replies while the normal drain is blocked, and handles allow/deny/timeout/desktop-first receipts. Permission defaults and binding/profile overrides persist through the existing configuration/profile stores. Focused new and adjacent tests: 58 passed (2.25s), lint passed. Production server/API wiring and a real FakeLLM write scenario are still pending. An adjacent existing 400ms backoff test failed once in a 76-test batch (four starts instead of five); isolated rerun passed (0.62s). This is not hidden as an all-green batch.
- H1/H4/H5 and controller H7 are in progress. No overall H1–H11 completion is claimed.

Pending: H5 complete snapshot/mechanical split/production DI, H1/H4/H6/H8/H9/H10.1 performance, H3, H2, H7 production wiring, H10.2, H11, final gates and main push.
