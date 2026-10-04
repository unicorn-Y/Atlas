# H10.1 lane timing — takeover session (Lane D)

Date: 2026-10-04. Working tree: `D:\Atlas-h1-core-hardening` @ b7b3b6a (clean; other lanes
concurrently editing source during all measurements).

Interpreter: `core/.venv/Scripts/python.exe` (shared with host checkout via junction —
tracebacks print `D:\Atlas\core\.venv\...`).
Standard invocation (both roots verified):

```
PYTHONIOENCODING=utf-8 PYTHONPATH="D:/Atlas-h1-core-hardening/core;D:/hermes-agent-h1-core" \
  ./core/.venv/Scripts/python.exe -m pytest core/tests [-m <lane>] [-n 8] -q \
  --basetemp="C:/Users/25011/AppData/Local/Temp/h1-h10"
```

From `core/`: same command with `tests` as the path. rootdir resolves to `core/` in both
cases (inifile `core/pyproject.toml`, `addopts = "-m unit"` applied — see the deselected
counts below).

IMPORTANT CAVEAT: five H1 lanes ran pytest concurrently on this 8-CPU host during these
measurements. Timings are pessimistic; H11 should re-measure on a quiet host before
accepting the A14 budget.

## 1. Collection (goal 1 + 2)

### Start-of-session snapshot (2116 total; baseline was 2040)

| lane | from repo root | from core/ | wall (collect-only) |
|---|---|---|---|
| unit (default, addopts) | 1952/2116, 164 deselected | 1952/2116, 164 deselected | 19.7s / 19.1s |
| integration (-m integration) | 163/2116 | 163/2116 | 19.6s / 18.3s |
| desktop (-m desktop) | 1/2116 | 1/2116 | 21.6s / 18.3s |
| live (-m live) | 0 (exit 5, all deselected) | 0 (exit 5) | 15.0s / 18.0s |
| all (`-m "unit or integration or desktop or live"`) | 2116/2116, 0 errors | — | 19.7s |

### Final snapshot (~2h later, other lanes kept adding tests)

| lane | from repo root | from core/ | wall (collect-only) |
|---|---|---|---|
| unit (default) | 1980/2144, 164 deselected | 1980/2144, 164 deselected | 16.9s / 14.1s |
| integration | 163/2144 | 163/2144 | 15.5s / 14.6s |
| desktop | 1/2144 | — | 14.5s |
| live | 0 (exit 5) | — | 15.4s |
| all | 2144/2144, 0 errors | — | 17.7s |

Drift vs the 2040 baseline (1876 unit / 163 integration / 1 desktop): integration and
desktop are unchanged; unit grew 1876 → 1980 (+104) from tests added by the other four
lanes during the session (snapshot at session start: +76, final: +104). Sums are exact in
both snapshots: 1952+163+1 = 2116; 1980+163+1 = 2144.

## 2. Run timing (goal 2), xdist -n 8 (8 workers / 8 CPUs, busy host)

| lane | tests | result | pytest time | end-to-end wall | log |
|---|---|---|---|---|---|
| unit | 1952 | 1910 passed, 35 failed, 4 skipped, 3 errors | 788.84s (13:08) | 13m11s | run-unit-xdist.log |
| integration | 163 | 117 passed, 41 failed, 5 skipped | 276.21s (04:36) | 4m39s | run-integration-xdist.log |
| layer tests (test_pytest_layers.py) | 6 | 6 passed | 0.21s (root) / 0.26s (core) | <1s | layer-tests-from-{root,core}.log |
| unit failures, serial rerun | 38 | 28 failed, 10 passed | 510.33s (08:30) | 8m36s | run-unit-failures-isolated.log |
| integration failures, serial rerun | 41 | 40 failed, 1 passed | 563.93s (09:23) | 9m25s | run-integration-failures-isolated.log |

Budget status vs taskbook A14 (unit ≤ 3 min, unit+integration ≤ 10 min): NOT met on this
host under 5-lane concurrent load — unit 13:08, unit+integration ≈ 17:47. Collection is
~15-20s of each lane. Re-measure on a quiet host at H11 before judging the budget; the
per-test throughput is dominated by CPU contention from the parallel lanes.

## 3. Failure ledger (protocol: only failures reproduced twice are reported)

### Unit lane — reproduced in xdist run AND serial isolated rerun (28)

| cluster | count | evidence / probable owner |
|---|---|---|
| test_takeover_x2_bridge.py | 7 | `RuntimeError: FastAPI app is missing its AppServices container` (core/atlas/api/dependencies.py:14) — H5 per-app DI mid-flight |
| test_k1_daily_paths.py | 12 | daily-path harness over real WS backend + FakeLLM; `AssertionError: agent_event ...` — churn from H1/H5 runtime/server edits; load-sensitive (150s timeouts) |
| test_k1_daily_paths_x2x4x5.py | 4 | same harness (3 were ERRORs in xdist, FAILURES serial) |
| test_route_snapshot.py | 1 | frozen route snapshot != live routes — H5 is actively adding routers (memory/records/scheduling_router.py untracked) |
| test_model_router.py | 1 | native anthropic route test — H4 owns core/atlas/models/* (modified in worktree) |
| test_lint_gate.py | 1 | "no baseline scope grows" — H6 owns exception-scope baseline; source is mid-edit |
| test_channels_manager.py | 1 | backoff ladder `assert 4 >= 5` timing assertion; ledger already flagged this class once (passed isolated then, failed twice under load now) — controller-H7/channels owner |
| test_c6_main_chain.py | 1 | assertion in edit/review/fix chain — legacy C-lane churn |

Xdist-only unit failures (passed on serial rerun — NOT reported as lane failures, but
evidence they are not xdist-safe): test_devices_router.py (8), test_backend_parity_wave3.py
(1), test_local_execution.py (1).

### Integration lane — reproduced in xdist run AND serial isolated rerun (40 of 41)

| cluster | count | evidence |
|---|---|---|
| test_c1_websocket_acceptance.py | 25 | `AssertionError: {'type': 'agent_event', ...}` mid-run — H1/H5 runtime/server churn |
| test_server_agents_wiring.py | 9 | `RuntimeError: FastAPI app is missing its persistent-agent service` — H5 wiring mid-flight |
| test_server.py | 4 | WS protocol failure-reflection tests (3) + ask_user/process (1 of 2 passed on retry) |
| test_c6_lsp_e2e.py | 1 | LSP diagnostics ws event |
| test_gateway_integration.py | 1 | group handoff between persistent agents |

Xdist-only integration failure (passed on serial rerun, not reported):
test_server.py::TestBackendParityWave1::test_process_endpoints_read_output_kill_and_404.

None of the above files are in H10.1 ownership; all reproduced twice per protocol and are
handed to the owning lanes via the ledger.

## 4. Lane-definition tests (goal 3)

`core/tests/test_pytest_layers.py` — the six lane-policy tests the controller reproduced —
run from BOTH roots: **6 passed** each time (0.21s from root, 0.26s from core/).
Coverage: desktop lane + flaky(reruns=1), explicit desktop marker, unmarked → unit default,
live skipped without ATLAS_LIVE=1, live selectable with opt-in, cross-component module →
integration.

## 5. Gates (goal 1, live)

- `ATLAS_LIVE=1` without `-m live` → exit 4, `ERROR: ATLAS_LIVE=1 is only allowed with an
  exclusive -m live selection` (live-misuse-takeover.log).
- `-m live` without `ATLAS_LIVE` → 0 collected, 2144 deselected, exit 5
  (live-exclusive-takeover.log). No live tests exist yet (H10.2 pending).

## 6. Desktop lane decision

`-m desktop` collects exactly 1 test
(test_computer_use.py::test_real_desktop_observe_input_clipboard_and_window_management,
auto-tagged + flaky(reruns=1) by conftest). It was NOT executed in this session: the
taskbook requires desktop to run separately (真实桌面，单独跑) and five lanes were running
concurrently — a real desktop/clipboard/window automation test would endanger the other
lanes' runs and the user's session. Collect-only verification only; run timing must be
taken in a quiet window with the same command (`-m desktop`, no xdist needed for 1 test).

## 7. Collection-defect status (handover item)

The reported open defect (`from conftest import _apply_test_lane` → ModuleNotFoundError)
does NOT reproduce at b7b3b6a: the fix landed in commit 0a89089 as a mechanism — the helper
is injected through the conftest-provided `_lane_policy` fixture
(core/tests/conftest.py:92) instead of a module import, which is rootdir- and
importmode-independent (with `core/tests/__init__.py` present, conftest imports as
`tests.conftest`, so a top-level `conftest` module does not exist and must not be
imported). `grep "from conftest import|import conftest" core/tests` → no matches. Full
collection from repo root and from core/ both finish with 0 errors (this file's sections 1
and 5).
