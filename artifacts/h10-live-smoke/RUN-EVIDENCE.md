# H10.2 real-model smoke — evidence manifest (Lane K)

Date: 2026-10-04/05 (evening run). Suite: `core/tests/test_live_model_smoke.py` (3 live scenarios + doctor probe).
Result: **3 passed in 94.87s** (`ATLAS_LIVE=1 -m live`, first attempt, no reruns needed).

## Configuration actually used (verified, redacted)

- Endpoint: `https://cnapi.pleasure.cc.cd:8443/v1` — deepseek ChatCompletions-compatible relay (host channel; taken read-only from the host install config `D:/Atlas/config/atlas.toml` into a scratch copy).
- Model: `deepseek-v4.1-flash` (custom model entry, provider `openai`, ChatCompletions).
- API key: copied in-process into the scratch data root only; redacted from every artifact (scan: 20 files, 0 key hits, 0 `sk-*` shapes, 0 bearer headers).
- Data root (scratch, isolated): `C:/Users/25011/AppData/Local/Temp/h1-k-ws/live-root` (built by `build_live_root.py`; never the repo, never the host install).
- Scratch workspaces: `live-root/workspaces/*` (all scenario runs ran with subprocess `cwd=<workspace>`).

## Commands

Build the live root (no secrets printed):
```
core/.venv/Scripts/python.exe C:/Users/25011/AppData/Local/Temp/h1-k-ws/build_live_root.py
```

Doctor connectivity check (gate; must pass before scenarios):
```
PYTHONIOENCODING=utf-8 PYTHONPATH="D:/Atlas-h1-core-hardening/core;D:/hermes-agent-h1-core" \
ATLAS_DATA_DIR=<live-root> HERMES_HOME=<live-root>/engine ... \
core/.venv/Scripts/python.exe -m atlas.cli doctor --json
```

Suite:
```
cd D:/Atlas-h1-core-hardening
PYTHONIOENCODING=utf-8 PYTHONPATH="D:/Atlas-h1-core-hardening/core;D:/hermes-agent-h1-core" \
ATLAS_LIVE=1 ATLAS_LIVE_SMOKE_ROOT="C:/Users/25011/AppData/Local/Temp/h1-k-ws/live-root" \
ATLAS_LIVE_EVIDENCE_DIR="D:/Atlas-h1-core-hardening/artifacts/h10-live-smoke/runs/suite-1" \
ATLAS_DATA_DIR="C:/Users/25011/AppData/Local/Temp/h1-k-ws/live-root" \
./core/.venv/Scripts/python.exe -m pytest core/tests/test_live_model_smoke.py -m live -q \
  --basetemp="C:/Users/25011/AppData/Local/Temp/h1-k"
# 3 passed in 94.87s
```

Gate behavior (verified): without `ATLAS_LIVE=1` the module is deselected by default
(`-m unit` addopts); `ATLAS_LIVE=1` without `-m live` raises UsageError (conftest policy).

## Per-run record (from evidence `meta.json` + summary lines)

| run | exit | wall s | result | usage in/out tok | cached | changes | approvals_denied |
|---|---|---|---|---|---|---|---|
| 00-doctor | 0 | 3.2 | ok:true, models HTTP 200 | — | — | — | — |
| 01-write-file | 0 | 34.1 | completed | 10645 / 83 | 0 | files 1 (+1/-0) | 0 |
| 02-read-answer | 0 | 28.7 | completed | 10161 / 2 | 0 | files 0 | 0 |
| 03-approval-deny | 3 | 28.6 | completed (turn), CLI exit 3 by approvals_denied | 10120 / 136 | 0 | files 0 | 1 |

Total billable ≈ 30.9k input + 0.2k output tokens (deepseek flash; far below the $5 budget).

Scenario outcomes on disk:
- `01`: `workspaces/write-771f40eb/hello.txt` == `ATLAS-LIVE-SMOKE-OK\n` (exact).
- `02`: summary message contains the seeded magic number; workspace unmodified.
- `03`: `workspaces/approve-*/` empty — denied write never landed; `approval.required` + `approval.responded{deny}` events present.

## Defect evidence (real-model-only; NOT fixed by this lane)

1. **H10.2-DEFECT-1 router wire model**: `runs/00-wire-model-probe.json` — relay 404s the
   litellm-prefixed id the router passes on chat_completions routes
   (`openai/deepseek-v4.1-flash` → HTTP 404 model_not_found; bare `deepseek-v4.1-flash` → 200).
   Repro stream: `runs/00-probe-defect1-2-stream.jsonl`.
2. **H10.2-DEFECT-2 permanent model failure reported as success**: same repro — engine emits
   recovery notices then `run.completed`, CLI exit 0, empty message, all-null usage after a
   non-retryable HTTP 404.
3. **H10.2-DEFECT-3 workspace cwd leak**: `runs/01-probe-defect3-record.json` +
   `runs/01-probe-defect3-stream.jsonl` — model wrote to the CLI process launch dir
   (`D:/Atlas-h1-core-hardening/hello.txt`) despite `--workspace` pointing at the scratch dir;
   static root cause: `core/atlas/engine/hermes_runtime.py:968` → fork `agent_init.py:2434`
   (`agent.session_cwd`) is never wired into the engine prompt's `resolve_agent_cwd()`
   (fork `agent/prompt_builder.py:1046`, `agent/runtime_cwd.py:105`) → falls back to `os.getcwd()`.

The two accommodations the harness makes because of these defects (documented, not product
fixes): scratch config uses the bare wire model id (DEFECT-1); scenarios launch the CLI with
`cwd=<workspace>` and name the workspace absolute in the prompt (DEFECT-3).

## Files

- `core/tests/test_live_model_smoke.py` — the live-marked suite (owned deliverable).
- `runs/00-doctor.*` — redacted doctor report + stderr (host-shaped config, prefixed model).
- `runs/00-wire-model-probe.json`, `runs/00-probe-defect1-2-*.jsonl/.log` — DEFECT-1/2 evidence.
- `runs/01-probe-defect3-record.json`, `runs/01-probe-defect3-*.jsonl/.log` — DEFECT-3 evidence.
- `runs/suite-1/<00-doctor|01-write-file|02-read-answer|03-approval-deny>/{meta.json,stream.jsonl,stderr.log}`
  — full per-run evidence (redacted on write).
- `redact_evidence.py` — evidence redactor; `build_live_root.py` — scratch live-root builder
  (secret-free; reads the host config read-only at build time).
