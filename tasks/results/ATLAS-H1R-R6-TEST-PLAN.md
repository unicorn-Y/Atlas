# H1R R6 layered test plan

This is a static inventory and execution plan. Pytest was not run while preparing it.
`core/pyproject.toml` sets `norecursedirs = ["live"]`: the live scenario's workspace inputs
are not Atlas backend tests, while the root-level `test_live_full_run*.py` modules remain
collectable as live tests.

## Inventory

The inventory walks every `core/tests/**/test_*.py` file and applies the current
`tests/conftest.py` policy, without importing tests or invoking pytest collection:

| Lane | Files with test definitions (lanes can share a file) | Test function definitions |
|---|---:|---:|
| unit | 165 | 1,741 |
| integration | 19 | 190 |
| desktop | 1 | 1 |
| live | 3 | 15 |
| Total | 188 matching filenames | 1,947 |

There are 185 non-live matching files (including two files without test definitions) and
1,932 non-live test function definitions; 183 non-live files contain test functions.
`test_autonomous_knowledge_e2e.py` and `test_prompt_cache_atlas.py` have no `test_*`
definitions but remain in collection so import/collection failures stay visible. The live
scenario input `tests/live/01-fix-python-test/workspace/test_calc.py` has three functions and
is intentionally bad (`calc.add` subtracts); none is an Atlas backend test. Pytest's
`norecursedirs = ["live"]` excludes this fixture directory without deleting, skipping, or
reclassifying any backend test. The three root-level `test_live_full_run*.py` modules remain
collectable as `live`. Source-tree counts including the excluded fixture are 189 matching
filenames and 1,950 function definitions. Lane file counts can overlap when a module has
tests in more than one lane. Definition counts are not collected item counts; parametrized
tests expand at runtime and JUnit output is authoritative. The only desktop case is the real
Windows clipboard/window/input regression in `test_computer_use.py`; conftest adds one retry
to that lane.

The integration list explicitly includes `test_run_usage_aggregation_e2e.py`,
`test_session_migration.py`, and `test_hermes_session_sync.py`. They exercise the native
HTTP fake-server parent/child path or real Atlas MemoryStore and Hermes SessionDB persistence,
including migration and atomic publication. `test_live_harness_regressions.py` remains unit:
it tests the harness with fakes and does not call a model provider.

Machine-readable file/function inventory: `tasks/results/ATLAS-H1R-R6-TEST-INVENTORY.json`.

## Gate commands

Run `core/scripts/run_h1r_r6_gates.ps1` from an idle, exclusive test lane. It runs the unit
timing gate, unit-plus-integration timing gate, desktop lane, and full frontend Vitest suite
serially by default. `-Gates` can select a subset; the summary is atomically updated after
each finished lane so a first unit-only run can be inspected before starting the next lane.
It stops at the first failure unless `-ContinueOnFailure` is explicitly supplied. Backend
pytest runs use `-n auto --dist loadscope`, an external lane-specific basetemp, per-test
timeout 300 seconds, short failure output, and the 30 slowest-test report. Raw logs/JUnit
remain disposable under `artifacts/h1r-r6/`; the machine-readable inventory and this plan are
the reviewable preparation artifacts.

```powershell
Set-Location D:\Atlas-h1-core-hardening
& .\core\scripts\run_h1r_r6_gates.ps1 -Gates unit `
  -HermesRoot D:\hermes-agent-h1r-closeout `
  -OutputDirectory D:\Atlas-h1-core-hardening\artifacts\h1r-r6 `
  -BasetempRoot $env:TEMP\atlas-h1r-r6-final
```

After the unit gate passes and its summary is reviewed, run the remaining lanes using the same
output and basetemp roots. The script keeps the first lane's completed summary entry:

```powershell
& .\core\scripts\run_h1r_r6_gates.ps1 -Gates unit-integration,desktop,frontend `
  -HermesRoot D:\hermes-agent-h1r-closeout `
  -OutputDirectory D:\Atlas-h1-core-hardening\artifacts\h1r-r6 `
  -BasetempRoot $env:TEMP\atlas-h1r-r6-final
```

The required wall-clock checks are unit ≤180 seconds and unit+integration ≤600 seconds.
Desktop runs separately because it touches the real Windows desktop; its test receives the
configured single retry. Unit+integration and desktop together cover all non-live backend
layers. The frontend stage runs `npm.cmd test -- --reporter=dot` from `frontend/`.

After the script completes, pass the recorded unit+integration and frontend measurements to
the existing R8 baseline writer to populate the `test_times` section of
`tasks/results/ATLAS-H1-after.json`:

```powershell
Set-Location D:\Atlas-h1-core-hardening
& .\core\.venv\Scripts\python.exe .\core\scripts\baseline_metrics.py `
  --repo-root D:\Atlas-h1-core-hardening `
  --python D:\Atlas-h1-core-hardening\core\.venv\Scripts\python.exe `
  --hermes-root D:\hermes-agent-h1r-closeout `
  --output tasks/results/ATLAS-H1-after.json `
  --backend-test-log artifacts/h1r-r6/unit-integration.log `
  --backend-junit-xml artifacts/h1r-r6/unit-integration.xml `
  --backend-test-elapsed-seconds <unit-integration-seconds> `
  --backend-test-exit-code <unit-integration-exit-code> `
  --backend-full-hermes-root D:\hermes-agent-h1r-closeout `
  --frontend-test-log artifacts/h1r-r6/frontend.log `
  --frontend-test-elapsed-seconds <frontend-seconds> `
  --frontend-test-exit-code <frontend-exit-code>
```

Record the unit and desktop timings, all four exit codes, JUnit totals, and the measured
threshold result in the R8 result report. Do not infer a pass from a started process, partial
log, or static test-definition count.
