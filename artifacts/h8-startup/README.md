# H8 启动速度 — before/after evidence (lane J)

Measured with `core/scripts/startup_probe.py` (cold-start method identical to the H0
baseline harness in `core/scripts/baseline_metrics.py`; fake-model config pointing at a
closed loopback port; 3 subprocess starts; health poll every 50 ms).

## Numbers (host: Windows 11, 32 logical cores; Python 3.14 venv)

| metric | before (commit 2562124 + wave-2 tree) | after (this tree) |
|---|---|---|
| cold start samples (s) | 8.184 / 8.062 / 7.410 | 7.492 / 6.946 / 6.902 |
| **cold start median (s)** | **8.062** | **6.946** |
| `import atlas.server` median (s) | 4.635 (min 4.235) | 3.437 (min 3.434) |
| importtime total (us) | 3,906,559 | 2,977,984 |
| independent check: `test_startup_time.py` medians | — | 6.918 / 6.890 (two runs) |

Load context: measured while the ZCode crew ran concurrently (H5-final was actively
extracting server.py during the "after" pass). Absolute values are noisy under load;
medians of 3 are reported, consistent across both methods.

## Attribution (important)

* The before→after delta (−1.1 s cold, −1.2 s import) is from the **H5-final lane's
  server.py extraction landing concurrently**, not from lane J: lane J's Python-side
  finding is that `core/atlas/engine/**` is already lazy post-H1/H3 (hermes imports are
  function-local; engine contributes ~2 ms to the import phase).
* The remaining gap to the §10 budget (≤ 5 s) is quantified and spec'd in
  `tasks/results/ATLAS-H1-H8-lifespan-spec.md`:
  lifespan body ~3.4 s still runs before uvicorn binds (DBOS + 38 migrations, MCP start,
  skills scan, plugins, channels/automation), plus ~0.9 s of deferrable mcp-chain imports
  via `atlas/agent/__init__.py` (out of lane J's ownership).
* Lane J's landed changes are Electron-side (no fixed 15 s kill, 120 s progress-aware cap,
  50-line log tail on real failure, parallel spawn with the window, renderer「启动中」+
  auto re-init) and the test/probe harness (`test_startup_time.py` integration gate,
  `startup_probe.py`, `backendProcess.test.ts`).

## Files

* `before.json` / `after.json` — probe reports (source commit, samples, importtime tops)
* `logs-before/` / `logs-after/` — preserved server logs per cold start + `importtime.txt`
* `../results/ATLAS-H1-H8-lifespan-spec.md` — the lifespan + import-chain spec
