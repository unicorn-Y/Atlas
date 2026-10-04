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

---

# Lane N — O1/O2 import deferral evidence (2026-10-04)

Landed spec §3 O1 (`core/atlas/agent/__init__.py`: the four `atlas.tools.*`
imports are now `TYPE_CHECKING`-only with PEP 562 module `__getattr__`
re-exports + `_default_web_extractor()` for the one runtime default) and O2
(`core/atlas/tools/__init__.py`: PEP 562 lazy `MCPClient`/`ToolInfo`
re-export — required because `atlas.agent.results` eagerly imports
`atlas.tools.output_limits`, which executed the package `__init__` and pulled
the whole mcp chain).

## `import atlas.agent` component (the O1 target)

| metric | before | after |
|---|---|---|
| importtime cumulative (us) | 2,534,079 | 1,215,186 (**−1.32 s**) |
| subprocess wall, median of 3 (s) | 2.310 (2.041/2.31/2.475) | 1.208 (1.192/1.208/1.297) (**−1.10 s**) |
| mcp/tools modules loaded | 125 | 4 (only `atlas.tools`, `output_limits`, `output_truncate`, `web`) |
| `mcp.*` modules loaded | 107 | 0 |

Raw dumps: `importtime-agent-before.txt` / `importtime-agent-after.txt`;
pristine+lazy file copies used for the A/B wall measurement in
`o1-orig-backup/`. The deferred chain still imports on demand
(`from atlas.agent import MCPClient` pulls 115 mcp modules lazily).

## Server cold path (probe runs, 3 starts each, same harness as above)

| metric | o1-before.json | o1-after.json |
|---|---|---|
| `import atlas.server` median (s) | 3.825 | 3.926 |
| cold start median (s), health ok x3 | 6.326 | 7.072 |

Load context: concurrent H1 crew lanes (server/api + models/engine/cli) were
active for both passes; medians of 3 are within noise. Attribution of the flat
cold-start number: on this tree `server.py:100-106` **eagerly imports the same
four heavy modules** (`atlas.tools.computer_use/local_execution/mcp_client/web_extract`),
so the server import graph pays the mcp chain (1.17 s cumulative in
`logs-o1-after/importtime.txt`) regardless of the agent package. Before O1 the
chain entered via `atlas.agent` (1.60 s cum, 1.08 s mcp nested); after O1
`atlas.agent` is 0.44 s and the chain enters via server.py instead — net cold
path unchanged until the **server lane** applies the same deferral there
(`MCPClient` construction is already slated for the deferred `mcp` component,
spec §1 S2 item 2). O1's −1.1…−1.3 s is banked for every other entry point
that imports `atlas.agent`/`atlas.tools` submodules without the server module.

Gate: `core/tests/test_h8_lazy_tool_imports.py` (2 unit tests: hermetic
subprocess probe asserts no eager mcp/tools import + all lazy names resolve +
AttributeError contract; public `__all__` surfaces unchanged).

* `../results/ATLAS-H1-H8-lifespan-spec.md` — the lifespan + import-chain spec
