# Old Memory System Purge — Closeout Record

**Status:** source cleanup and available checks completed; host cleanup and real-model acceptance are pending the user applying the update and restarting Atlas.

**Branch:** `memory-purge`
**Starting base:** `origin/memory-v1` at `ac347b2d6f768aa41794d380b004040fc7fd45cd`
**Purge implementation already present:** `6834eb38e253ef435a77a11df2de5bddcc316d59`
**Taskbook commit:** `a526475a9d7a46b4940b06d3c1fe7e42aae98065`

## Changes in this closeout

- Removed tests for the deleted `remember` tool, `MemoryReflectionBridge`, old injection budgets, goal-knowledge workflows, legacy fact/candidate APIs, and autonomous knowledge loops.
- Updated session migration and long-lived recovery coverage to exercise the retained `session_search` path directly.
- Removed old fact, candidate, goal-knowledge, and knowledge-health endpoints from the route snapshot and refreshed `core/tests/snapshots/routes.json` from the live route builder.
- Removed obsolete memory mock methods from agent, planning, and hook tests. Kept goal scheduling and runtime event checks that do not persist legacy memory.
- Restored the `get_automation_engine` compatibility export in `atlas.server`; deferred shutdown still imports it from that module. This fixes a startup teardown import error introduced by the purge branch.
- Simplified the startup failure test wrapper to use the current `MemoryStore` constructor.

## Verification

| Check | Result |
| --- | --- |
| Required unit command, purge branch: `python -m pytest -q -x -p no:cacheprovider` | 48 passed, then stops at `tests/test_agent_skills.py::test_router_auth_shape`: expected HTTP 200, got 403. The same test fails on `origin/memory-v1`. |
| Same unit command, base `origin/memory-v1` | Stops earlier during collection at `tests/test_f2_observer_smoke.py`: `ModuleNotFoundError: scripts.f2_observer_smoke`. The stale smoke test is absent from the purge branch. |
| Full unit run without `-x` | Not completed. A run stalled after partial progress; a 30-second diagnostic timeout expired while Python was creating its Windows asyncio socket pair. A complete all-tests failure-list comparison is therefore unavailable. |
| `ruff check --select F401,F821,F841` on changed Python files | Passed. |
| Session migration tests | 8 passed. |
| Startup failure resilience tests | 5 passed. |
| Long-lived agent recovery test (explicitly selected) | 1 passed. |
| Changed server run-failure event tests (explicitly selected) | 3 passed. |
| Route snapshot test | Passed. |
| Focused agent/enrichment/run-phase/model/planning group | 86 passed before the known fake-HTTP model-router failure below. |
| `test_model_router.py::test_native_anthropic_route_completes_over_fake_http_endpoint[conversation]` | Fails on both the purge branch and `origin/memory-v1`. |
| `test_c4_hooks.py` | Base: 7 failed, 12 passed. Purge branch: the same 7 failures, 11 passed; the stale goal-knowledge test was removed and the retained prompt-denial test no longer calls removed `extract_memories`. |
| Renderer and Electron TypeScript checks (`tsc --noEmit` for both configs) | Passed. |
| Frontend Vitest | 28 files passed; 188 tests passed. |

The taskbook lists two pre-existing `test_c1_tool_workspace.py` failures (`FixtureConfig.raw` missing). They were not reached by the required `-x` run in this session.

## Host cleanup

No host paths have been moved and no host services or configuration have been changed. The taskbook requires this stage to wait until the user clicks **立即更新** and Atlas restarts.

After that restart, the remaining host work is to check and stop the process owning port 8099 by PID, inspect startup tasks/entries, back up `atlas.toml` and (if still available before schema cleanup) `atlas.db`, and move only the listed legacy paths into `D:\_archive-old-memory-2026-10-14\`. `D:\Atlas\data\memory` is excluded from that move. Startup entries, if any, require the user’s approval before disabling them.

No host archive paths can be listed as moved yet. The legacy Memtensor links have not been checked on the restarted host.

## Real-model acceptance

Not run: Atlas has not yet loaded this branch on the host. The two requested questions, the run-log check for port 8099, and the next-turn `data/memory/我.md` persistence check remain pending the update and restart.

## Push state

At the time of this record, the purge branch changes have not yet been committed or pushed to `memory-v1`. The remote will be fetched again immediately before the push; its last observed `origin/memory-v1` tip was the starting base above.
