# H10.2 fix-proof — Lane M (real-model defect fixes D1/D2/D3)

Date: 2026-10-05 (early morning). Re-run of the H10.2 live suite after the
three real-model defect fixes, with BOTH pre-fix harness accommodations removed.

## Result

`ATLAS_LIVE=1 -m live core/tests/test_live_model_smoke.py` → **3 passed in
87.14s** (first attempt, no reruns), plus a manual live D2 failure probe
(`04-d2-live-failed-turn`, exit 1 with `run.failed`).

## What is proven (per defect)

- **D1 router wire model (H10.2-DEFECT-1)** — the scratch live root was
  rebuilt with the HOST-SHAPED custom entry verbatim:
  `litellm_model = "openai/deepseek-v4.1-flash"` (the pre-fix suite had to
  strip the prefix as a documented accommodation; the builder accommodation
  is deleted). Evidence: `runs/01-write-file/stderr.log` (and 02/03) now
  shows `🤖 AI Agent initialized with model: deepseek-v4.1-flash` — the BARE
  wire id — where the pre-fix evidence (`../runs/00-probe-defect1-2-stderr.log`)
  showed the prefixed id that the relay 404'd. All three scenarios completed
  with real provider usage (e.g. 01: 10361/73 tok, 1 file changed). The
  `wire_model` derivation itself is additionally proven by
  `04-d2-live-failed-turn`: a custom entry
  `litellm_model = "openai/nonexistent-model-d2probe"` reached the relay as
  `Model "nonexistent-model-d2probe"` (bare) and was rejected by the RELAY —
  not by a prefix mismatch.
- **D2 failure reported as success (H10.2-DEFECT-2)** — manual live probe
  `runs/04-d2-live-failed-turn/`: `atlas run --model live-badwire` (a
  nonexistent relay model, real endpoint, real 404s) now ends
  `run.failed {category: model, detail: HTTP 404: Model
  "nonexistent-model-d2probe" is not supported...}`, NO `run.completed`,
  summary `result: failed`, **CLI exit 1**. Pre-fix the same shape of run
  emitted recovery notices then `run.completed` and exit 0
  (`../runs/00-probe-defect1-2-stream.jsonl`). Fake-provider regression
  cover: `core/tests/test_cli_headless.py::
  test_run_reports_permanent_model_failure_as_failed_exit_1` and the
  run_phases unit tests in `core/tests/test_agent_run_phases.py`.
- **D3 workspace cwd leak (H10.2-DEFECT-3)** — all three scenarios launched
  the CLI with `cwd=<live root>` (deliberately NOT the workspace), and
  scenario 01's prompt names NO absolute path ("在工作区创建文件
  hello.txt…"). Evidence: `runs/01-write-file/stream.jsonl` shows the write
  resolved to
  `…\live-root\workspaces\write-fe3b60cb\hello.txt` (inside `--workspace`),
  and the launch dir stayed clean (suite asserts `not (live.root /
  "hello.txt").exists()`). Pre-fix evidence for contrast:
  `../runs/01-probe-defect3-record.json` (file landed in
  `D:/Atlas-h1-core-hardening/`). Fake-provider regression cover:
  `core/tests/test_cli_headless.py::
  test_run_relative_write_lands_in_workspace_not_launch_dir` and
  `core/tests/test_engine_workspace_cwd.py` (seam-level).

## Configuration actually used (verified, redacted)

- Endpoint: `https://cnapi.pleasure.cc.cd:8443/v1` — deepseek
  ChatCompletions-compatible relay (host channel; scratch copy built by
  `../build_live_root.py` reading the host config read-only).
- Model: `deepseek-v4.1-flash`, custom entry `provider="openai"`,
  `litellm_model="openai/deepseek-v4.1-flash"` (host shape, prefix KEPT).
- API key: copied in-process into the scratch data root only; every artifact
  redacted on write; post-run scan of this directory: 14 files, 0 key hits,
  0 `sk-*` shapes.
- Data root (scratch, isolated): `C:/Users/25011/AppData/Local/Temp/h1-k-ws/live-root`.
- Scratch workspaces: `live-root/workspaces/*`; every scenario CLI ran with
  `cwd=<live-root>` (see each `runs/*/meta.json`).

## Commands

Rebuild the live root (host-shaped config; no secrets printed):
```
core/.venv/Scripts/python.exe D:/Atlas-h1-core-hardening/artifacts/h10-live-smoke/build_live_root.py
```

Doctor gate:
```
PYTHONIOENCODING=utf-8 PYTHONPATH="D:/Atlas-h1-core-hardening/core;D:/hermes-agent-h1-core" \
ATLAS_DATA_DIR=<live-root> HERMES_HOME=<live-root>/engine ATLAS_API_TOKEN=fixproof \
core/.venv/Scripts/python.exe -m atlas.cli doctor --json
# ok:true, models HTTP 200
```

Suite (evidence lands here, redacted on write):
```
cd D:/Atlas-h1-core-hardening
PYTHONIOENCODING=utf-8 PYTHONPATH="D:/Atlas-h1-core-hardening/core;D:/hermes-agent-h1-core" \
ATLAS_LIVE=1 ATLAS_LIVE_SMOKE_ROOT="C:/Users/25011/AppData/Local/Temp/h1-k-ws/live-root" \
ATLAS_LIVE_EVIDENCE_DIR="D:/Atlas-h1-core-hardening/artifacts/h10-live-smoke/fix-proof/runs" \
ATLAS_DATA_DIR="C:/Users/25011/AppData/Local/Temp/h1-k-ws/live-root" \
./core/.venv/Scripts/python.exe -m pytest core/tests/test_live_model_smoke.py -m live -q \
  --basetemp="C:/Users/25011/AppData/Local/Temp/h1-m-live"
# 3 passed in 87.14s
```

D2 live probe (manual, after the suite; scratch config temporarily carried an
extra `live-badwire` entry — removed afterwards by rebuilding the live root):
```
atlas.cli run -p "在工作区创建文件 d2probe.txt" \
  --workspace <live-root>/workspaces/d2probe --model live-badwire \
  --output-format stream-json --timeout 240
# exit 1; run.failed{category: model}; no run.completed
```

## Per-run record

| run | exit | wall s | result | usage in/out tok | changes | notes |
|---|---|---|---|---|---|---|
| 00-doctor | 0 | 3.2 | ok:true, models HTTP 200 | — | — | prefixed host-shaped config |
| 01-write-file | 0 | 31.8 | completed | 10361 / 73 | files 1 (+1/-0) | bare wire model on the agent; write INSIDE workspace; no absolute path in prompt |
| 02-read-answer | 0 | 28.3 | completed | (see meta/stream) | files 0 | magic number answered |
| 03-approval-deny | 3 | 23.5 | completed (turn), exit 3 by approvals_denied | (see meta/stream) | files 0 | denied write never landed |
| 04-d2-live-failed-turn | 1 | (manual) | **failed** | null | files 0 | real relay 404 → run.failed, exit 1 |

## Fix summary (one line each)

1. **D1** `core/atlas/models/router.py`: `RouteSpec.wire_model` — the router
   derives the bare/native id (explicit `native_model` wins, else the first
   litellm path segment is stripped); `hermes_agent_kwargs()` and
   `complete()` send `wire_model` to the Hermes transport; `RouteSpec.model`
   keeps the registry's litellm-style id for litellm-style consumers.
2. **D2** `core/atlas/agent/run_phases.py`: a Hermes terminal failed-turn
   verdict (`failed=true`, not `interrupted`) on the engine result is
   surfaced as `{"type": "error", category "model"}` and suppresses the
   success finalizer, so `run_drive` emits `run.failed` and the CLI exits 1.
3. **D3** `core/atlas/engine/hermes_runtime.py`: local workspaces are
   registered through the fork's public seams —
   `tools.terminal_tool.record_session_cwd(conversation_id, workspace)` and
   `agent.runtime_cwd.set_session_cwd(workspace)` pinned in the turn worker
   thread (reset in `finally`) — plus `run_conversation(task_id=
   conversation_id)` so the records are findable (gateway parity). ssh://
   workspaces keep their terminal-scope policy and stay out of local records.

## Files (Lane M)

- `core/atlas/models/router.py` — D1.
- `core/atlas/engine/hermes_runtime.py` — D3 (cwd seams + task_id).
- `core/atlas/agent/run_phases.py` — D2 (failure emission; finalizer skip).
- Tests: `core/tests/test_model_router.py` (+4), `core/tests/test_agent_run_phases.py`
  (+4), `core/tests/test_cli_headless.py` (+2, `_run_cli` cwd param),
  `core/tests/test_engine_workspace_cwd.py` (new, 5 tests),
  `core/tests/test_live_model_smoke.py` (accommodations removed),
  task_id=None added to the strict `run_conversation` doubles in
  `core/tests/test_engine_model_wiring.py` / `test_hermes_runtime.py` /
  `test_runtime_resources.py`, aux wire-model assertions re-pinned to the
  bare wire id in `test_engine_model_wiring.py` / `test_models_routes.py`.
- Harness: `artifacts/h10-live-smoke/build_live_root.py` (host-shaped config
  restore), this directory (`fix-proof/`).
