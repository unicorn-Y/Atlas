# MEMORY-V1 Package A (S0) evidence

**Status: PARTIAL; S0 remains `IN_PROGRESS`.** The harness repair, configuration checks, runtime freeze gates and retained-feature regression selection below passed. Full Atlas and MemoryOS suite baselines, the complete legacy fake-model script review, and A's own real-model smoke were not completed in this package pass. The controller owns the independent real-model evidence and will update `CURRENT.json`; this file does not change it.

## A-owned changes

Atlas changes:

- `core/tests/unified_memory/harness.py`: removed the scenario/keyword-driven `_synthesize_scripted_response` path that queried product memory and pushed a predetermined answer into the fake provider. Loopback HTTP requests now set `trust_env=False`. The Atlas child inherits the per-test `MEMORYOS_DATA_ROOT` and `MEMORYOS_DB_PATH` as well as `ATLAS_DATA_DIR`. Application receipts are selected only from this run's `application_receipt` events and their `read_id`s, queried from the manifest's `memoryos_db`; no recent receipt from another run is used. `applied_preference` now comes from matching receipt `applied_items`, and missing evidence is `UNVERIFIED`. `fabricated_fact` is `None` with `fabricated_fact_status=UNVERIFIED`; no fixed `False` verdict remains.
- `core/tests/unified_memory/test_bootstrap.py`: added isolated-env and loopback-proxy assertions plus a run/read-id-bound receipt-summary regression. The module is marked `fake_provider` because it exercises real Atlas/MemoryOS processes and WebSocket flow against the fake loopback provider; it is not product-effect evidence.
- `scripts/unified_memory/cutover.py`: the desktop preference fixture reports persistence only after a successful observe response. Its chat wrapper no longer fabricates `applied_preference` from the stored preference or a fallback string.
- `core/atlas/config.py`: added readers for `memory.unified.service_dir` (default `D:\MemoryOS`), `memory.v1.recall_timeout_seconds` (default `1.0`) and `memory.v1.observer_daily_token_budget` (default `50_000`). No user settings file was read or written.
- `core/atlas/api/models_settings_router.py` and `core/tests/test_models_routes.py`: expose `memory_model` in the existing settings API, validate against configured model IDs, persist it in the same settings store as `compression_model`, and test round-trip/clear/rejection with the existing test fixture's temporary settings path.
- `core/atlas/memory/v1_features.py` and `core/atlas/memory/windows_sources.py` had A-owned changes before this pass. They were present in the pre-edit snapshot and were not overwritten here; the passive-capture gate remains a pre-existing diff.
- `core/pyproject.toml`: registered the `fake_provider` marker only; default test selection was not changed.
- `core/tests/test_bootstrap_memory_v1_config.py`: new default, explicit-empty-list and invalid-feature-list checks.

MemoryOS changes handed back to the controller for integration:

- `service/unified/v1_features.py` and `service/app.py`: request-scoped freeze policy; no header means all §2 features remain frozen, a valid JSON list selects the frozen features, malformed/unknown values return 400, and middleware state is reset in `finally`.
- `service/unified/api.py`: freezes multimodal association and strategy-update maintenance entry points. Raw media upload, metadata/content reads and erasure remain available.
- `service/unified/retrieval.py`: skips graph association expansion when either `associations` or `graph_retriever` is frozen; ordinary recall remains available. The remaining `_unwrap_payloads` use only rejects candidate/low-confidence records and is retained as a safety filter.
- `service/unified/maintenance.py`: freezes SELF_PROBE/PROBE dispatch.
- `service/unified/utility.py`: freezes feedback, outcomes and learning projections. Real `/applications` read/context-hash validation and receipt persistence stay available while utility-profile creation and `applied_count` evolution are skipped when utility is frozen.
- `tests/unified_memory/memory_v1_test_support.py` is a test-only helper. It emits the smallest explicit opt-in feature set for retained tests. `test_v1_freeze.py` verifies default closure, valid/invalid headers, request reset after success and exception, normal recall, disabled graph execution, media evidence storage, and a real observe→recall→applications receipt without utility profile evolution.
- Existing preserved feature tests now opt in only within their test clients/fixture: `test_associative_recall.py`, `test_conditional_utility.py`, `test_grounded_probe.py`, `test_experience_distillation.py`, `test_multimodal.py`, `test_prediction_feedback.py`, `test_strategy_operations.py`, and `test_transfer_gate.py`. Their business assertions and selection were preserved.
- `tests/unified_memory/test_legacy_import.py` contains the separately authorized minimal import fix: it explicitly loads this checkout's HTTP helper by file path, preventing the `tests.unified_memory.conftest` collision. It was not edited further during this pass.

## Tests and raw logs

All commands below used `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8`. Test data roots and pytest temp/cache paths were isolated under `%TEMP%`; MemoryOS commands removed `PYTHONPATH`. No package was installed into either venv.

Atlas bootstrap/config command, cwd `D:\Atlas\core`:

```powershell
$runRoot = Join-Path $env:TEMP 'memory-v1-s0-a-rerun-20261007-02'
New-Item -ItemType Directory -Force -Path $runRoot | Out-Null
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
$env:ATLAS_DATA_DIR=Join-Path $runRoot 'atlas-data'
$env:MEMORYOS_DATA_ROOT=Join-Path $runRoot 'memoryos-data'
$env:MEMORYOS_DB_PATH=Join-Path $env:MEMORYOS_DATA_ROOT 'db\memoryos.sqlite3'
$log=Join-Path $runRoot 'atlas_bootstrap_config.stdout.log'
& 'D:\Atlas\core\.venv\Scripts\python.exe' -m pytest -q --basetemp (Join-Path $runRoot 'pytest-temp') tests\unified_memory\test_bootstrap.py tests\test_bootstrap_memory_v1_config.py 2>&1 | Tee-Object -FilePath $log
$code=$LASTEXITCODE
"EXIT=$code LOG=$log"
```

Result: **14 passed, 0 failed/skipped/xfail, exit 0, 23.23s**. One `PytestCacheWarning` reported concurrent access to the default Atlas `.pytest_cache`; the suite used its own basetemp and passed. Raw log: `C:\Users\25011\AppData\Local\Temp\memory-v1-s0-a-rerun-20261007-02\atlas_bootstrap_config.stdout.log`.

The first attempt omitted an isolated `--basetemp`; it completed 14 tests but exited 1 during pytest temp cleanup (`PermissionError` for shared `pytest-current`) while another pytest process was active. It is not acceptance evidence. Raw log: `C:\Users\25011\AppData\Local\Temp\memory-v1-s0-a-rerun-20261007-01\atlas_bootstrap_config.stdout.log`. The corrected isolated command above exited 0.

Atlas model settings command, cwd `D:\Atlas\core`:

```powershell
$runRoot = Join-Path $env:TEMP 'memory-v1-s0-a-rerun-20261007-atlas-model01'
New-Item -ItemType Directory -Force -Path $runRoot | Out-Null
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
$env:ATLAS_DATA_DIR=Join-Path $runRoot 'atlas-data'
$env:MEMORYOS_DATA_ROOT=Join-Path $runRoot 'memoryos-data'
$env:MEMORYOS_DB_PATH=Join-Path $env:MEMORYOS_DATA_ROOT 'db\memoryos.sqlite3'
$log=Join-Path $runRoot 'atlas_memory_model.stdout.log'
& 'D:\Atlas\core\.venv\Scripts\python.exe' -m pytest -q --basetemp (Join-Path $runRoot 'pytest-temp') -o ('cache_dir=' + (Join-Path $runRoot 'pytest-cache')) tests\test_models_routes.py -k memory_model_setting 2>&1 | Tee-Object -FilePath $log
$code=$LASTEXITCODE
"EXIT=$code LOG=$log"
```

Result: **2 passed, 19 deselected, exit 0, 12.20s**. Deselects are the existing non-A tests in that file. The fixture monkeypatches `USER_SETTINGS_PATH` to a `tmp_path`. Raw log: `C:\Users\25011\AppData\Local\Temp\memory-v1-s0-a-rerun-20261007-atlas-model01\atlas_memory_model.stdout.log`.

MemoryOS freeze, retained opt-in and legacy-import command, cwd `D:\MemoryOS`:

```powershell
$runRoot = Join-Path $env:TEMP 'memory-v1-s0-a-rerun-20261007-mos03'
New-Item -ItemType Directory -Force -Path $runRoot | Out-Null
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
$env:ATLAS_DATA_DIR=Join-Path $runRoot 'atlas-data'
$env:MEMORYOS_DATA_ROOT=Join-Path $runRoot 'memoryos-data'
$env:MEMORYOS_DB_PATH=Join-Path $env:MEMORYOS_DATA_ROOT 'db\memoryos.sqlite3'
$base=Join-Path $runRoot 'pytest-temp'
$log=Join-Path $runRoot 'memoryos_freeze_optin_legacy.stdout.log'
& 'D:\MemoryOS\service\.venv\Scripts\python.exe' -m pytest -q --basetemp $base -o ('cache_dir=' + (Join-Path $runRoot 'pytest-cache')) tests\unified_memory\test_v1_freeze.py tests\unified_memory\test_associative_recall.py tests\unified_memory\test_conditional_utility.py tests\unified_memory\test_grounded_probe.py tests\unified_memory\test_experience_distillation.py tests\unified_memory\test_multimodal.py tests\unified_memory\test_prediction_feedback.py tests\unified_memory\test_strategy_operations.py tests\unified_memory\test_transfer_gate.py tests\unified_memory\test_legacy_import.py 2>&1 | Tee-Object -FilePath $log
$code=$LASTEXITCODE
"EXIT=$code LOG=$log"
```

Result: **88 passed, 0 failed/skipped/xfail, exit 0, 20.23s**. Composition: 5 new freeze tests, 9 legacy-import tests, and 74 preserved feature tests. Two warnings are Starlette/httpx deprecations; no pytest cache warning. Raw log: `C:\Users\25011\AppData\Local\Temp\memory-v1-s0-a-rerun-20261007-mos03\memoryos_freeze_optin_legacy.stdout.log`. The service venv already contained pytest; no dependency installation was performed.

Before the legacy helper repair, a clean `D:\MemoryOS` run with `PYTHONPATH` unset produced **2 failed / 7 passed** from an import of Atlas's `D:\Atlas\core\tests\unified_memory\conftest.py`; original log: `C:\Users\25011\AppData\Local\Temp\memory-v1-s0-a-baseline-20261007\memoryos_test_legacy_import_clean_env.log`. The 9-item fixed run is included in the 88-pass command above.

An intermediate opt-in run produced **77 passed / 1 failed** because the transfer-gate `/learning` route needs the same four projections (`utility`, `experience_distiller`, `prediction`, `learning_gate`), not only `learning_gate`. The opt-in list was corrected without changing assertions; the final command above passed. Raw intermediate log: `C:\Users\25011\AppData\Local\Temp\memory-v1-s0-a-rerun-20261007-mos02\memoryos_freeze_optin_regressions.stdout.log`.

The Atlas harness test process exercised actual isolated service processes and WebSocket transport with `fake-loopback`; it is **fake-provider infrastructure evidence only**, not evidence of model or memory quality. A did not run a real-model request. The controller reported a separate real `deepseek-v4.1-flash` ModelRouter smoke and will independently audit that evidence; no unavailable-credential claim is made here.

## Baseline snapshot and concurrent work

Before editing, A's owned-file state was snapshotted at `C:\Users\25011\AppData\Local\Temp\memory-v1-s0-a-baseline-20261007\`. It contains Atlas/MOS status, targeted patch snapshots, the pre-existing `windows_sources.py` patch and the legacy import logs. Existing A-owned changes to `core/atlas/memory/windows_sources.py` and untracked `core/atlas/memory/v1_features.py` were present before this pass and remain distinct from the new changes listed above.

The shared worktree also contains B/C/controller edits. In particular, changes to Atlas `run_phases.py`, `unified_memory_router.py`, `unified_client.py`, `unified_facade.py`, `automation/engine.py`, `memory/__init__.py`, lifecycle/observer files and `CURRENT.json`, plus unrelated pre-existing MemoryOS recovery artifacts, were not authored, reverted, staged or committed by A. A did not change `CURRENT.json` or `VENDORED.md`; no commit or push was performed by A.

## Red-line review and remaining gaps

- No test was deleted, skipped, xfailed, threshold-lowered or made to return an expected answer. The only pytest registry change adds the `fake_provider` marker; default selection is unchanged.
- No second settings store, scheduler, model configuration or fact store was created. Model selection reuses the existing model settings store and validates configured model IDs. `memory_model` tests use the isolated existing store fixture.
- All test subprocess roots were isolated under `%TEMP%`. No access was made to `D:\Atlas\data`, `D:\MemoryOSData`, `user-settings.json`, or production config files. Local HTTP clients in the changed bootstrap/tests disable environment/registry proxies; real provider routing is not globally changed.
- A did not edit the taskbook-forbidden Atlas files (`run_phases.py`, the Atlas memory package entry, unified routers/client/facade, or automation engine), or MemoryOS `formation.py`/`consolidation.py`. A changed only freeze gates in MemoryOS `api.py` and `retrieval.py` under the controller's temporary authorization, plus `app.py` middleware wiring; these files and diffs have now been handed back to the controller for integration.
- `media_understanding`, `skill_evolution`, and `targeted_learning` have no separate MemoryOS runtime HTTP route in the current checkout; raw media evidence storage stays available. `passive_capture` is represented by the pre-existing Atlas source gate. The S0 route tests cover the current callable paths, not hypothetical absent endpoints.
- Follow-up S4 contract gap observed but intentionally not expanded in S0: `/applications` validates real `read_id` and `context_hash`, but the current implementation does not verify that every submitted `applied_item` belongs to that read receipt/current record revision. Receipt storage is preserved; profile evolution is frozen.
- Legacy script review identified `gen_manifest.py`'s `fake-model` values as synthetic fixture data; `repair_baseline.py` has an old pending-work documentation string mentioning the removed harness function. `learning_trial.py` explicitly uses `fake-model`/`fake-model-b` for a 648-trial simulation and was not run or counted as product-effect evidence. These legacy artifacts were not rewritten in this partial pass.
- Full repository test collection and full-suite baseline counts were not run by A. Controller independent checks reported 74 preserved MemoryOS feature tests passing and five freeze tests passing; the combined A command is the 88-pass run above. A's S0 package therefore remains partial pending full baseline/evidence review and controller acceptance.

## S1 Regression Repair Pass (2026-10-07)
- **Status**: DONE_PENDING_REVIEW
- Fixed 11 regressions:
  - `core/atlas/agent/run_phases.py`: added `_is_unified_reads_enabled` to handle `AsyncMock` returning coroutines, safely closing them; moved defensive check for unexpected coroutines in memories before personal relevance filtering.
  - `core/atlas/api/unified_memory_router.py`: removed status override in proxy route, letting 503 ServiceUnavailable cleanly propagate.
  - `core/atlas/memory/__init__.py`: updated `_has_fact_key` to check local db if unified fact is absent.
  - `core/atlas/memory/windows_sources.py`: allowed passive capture when explicit controller is provided.
  - `core/tests/unified_memory/test_legacy_migration.py`: added `list_records` to `FakeUnifiedFacade`.
- Test results:
  - 5 regression test suites: 74 passed, 10 deselected, 0 failed.
  - Lifecycle & unified reads tests: 17 passed, 0 failed.

