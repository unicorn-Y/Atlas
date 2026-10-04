# ATLAS-H1-H8 lifespan + startup-critical-path spec

> Author: Lane J (H8 启动速度), 2026-10-05. For the server.py lane (lifespan) and the
> agent/tools lanes (import chain). H8 lane does NOT edit `core/atlas/server.py`,
> `core/atlas/api/**`, `core/atlas/agent/**`, or `core/atlas/tools/**`.
>
> CAVEAT: `server.py` was mid-refactor (H5-final extraction, 3503 → 749 lines) while this
> spec was written. Line numbers below are from that working state
> (`git diff` against `2562124`); treat the quoted snippets, not line numbers, as the anchor.

## 0. Goal (taskbook §10.2 / A12)

Backend cold start to `GET /api/health` → `{"status": "ok"}` **≤ 5 s** on the host with the
fake-model config. Measured evidence lives in `artifacts/h8-startup/` (`before.json`,
`after*.json`, `logs-before/`, `logs-after/`).

| phase (process start → health ok) | before (wave-2 tree, 2562124) | current tree (H5-final in flight) |
|---|---|---|
| python + cli boot | ~0.3 s | ~0.3 s |
| `import atlas.server` | 4.6 s median (importtime 3.9 s) | ~3.0 s |
| lifespan startup (before uvicorn binds) | ~3.2–3.9 s | ~3.4 s |
| **cold start median (3 runs)** | **8.06 s** | **6.9 s** (test_startup_time.py: 6.89–6.92) |

Phase timeline from a preserved server log (`artifacts/h8-startup/logs-before/cold-start-0.log`,
1-second log granularity): ~3 s imports → `model_manager.init` → `memory.init` → **DBOS init +
38 SQLite migrations (~1 s)** → `mcp.no_servers_configured` → **skills.scanned (~1 s)** →
**capabilities/plugins/channels/automation (~2 s)** → `Application startup complete`.

Conclusion: the remaining critical path after the H5-final import win is (1) the lifespan body
that runs entirely before uvicorn binds the port, and (2) ~0.9 s of avoidable import chain
(§3). Both must land for A12.

## 1. §10.2 spec for the server lane: split the lifespan

### S1 — component registry (new `core/atlas/api/startup_components.py`, server lane)

```python
"""Startup component states for /api/health (H8 §10.2)."""
from __future__ import annotations
import asyncio, structlog

log = structlog.get_logger(__name__)

class StartupComponents:
    """Per-component lifecycle state: starting → ready | failed.

    `wait_ready()` lets request paths that genuinely need a deferred component
    await it (bounded); everything else keeps working while components start.
    """
    def __init__(self) -> None:
        self._states: dict[str, str] = {}
        self._events: dict[str, asyncio.Event] = {}

    def mark(self, name: str, state: str) -> None:      # "starting" | "ready" | "failed"
        self._states[name] = state
        self._events.setdefault(name, asyncio.Event()).set()
        (log.error if state == "failed" else log.info)("startup.component", component=name, state=state)

    def snapshot(self) -> dict[str, str]:
        return dict(self._states)

    async def wait_ready(self, name: str, timeout: float = 30.0) -> bool:
        event = self._events.setdefault(name, asyncio.Event())
        try:
            await asyncio.wait_for(event.wait(), timeout)
        except asyncio.TimeoutError:
            return False
        return self._states.get(name) == "ready"
```

Mount it on `AppServices` (e.g. `services.startup = StartupComponents()`), created in
`create_app` so `/api/health` can always reach it.

### S2 — lifespan split (server.py `lifespan`, currently lines 155–~600)

Split the body into:

* **Critical (must run before `yield`)** — everything cheap or needed by `/api/health`,
  `/ws/chat` and the first conversation request:
  `model_mgr`, `memory.init()`, `usage_ledger.init()`, `projects.init()`, `manager.init()`,
  `import atlas.engine.local_runtime_adapter` (W6 HERMES_HOME pin), the runtime constructors
  (`LocalExecutionRuntime`, `CuaBackend`, `ComputerUseRuntime`, `CapabilityBus`,
  `BrowserUseAdapter`, `AgentBackendHost`, `WebRuntime`), skill registry + capability
  registration loop (lambdas only — keep), `custom_tools`, `checkpoints`, `orchestrator`
  construction, notification bus, services binding block (the `for service_name in (...)`
  loop and the `services.persistent_agents / group_*` fixes), and the plugin-runtime
  *construction*. Register every component as `"starting"`.
* **Deferred (run as `asyncio.create_task(self._deferred_startup(...))` right before
  `yield`, each wrapped so a failure marks the component `"failed"` and never kills the
  server — H6 style `log.exception` + visible recovery notice)**:
  1. `durable.start()` + DBOS instance fetch (lines 175–184) → component `dbos`
  2. `mcp_client = MCPClient(); await mcp_client.start()` (lines 192–193) → component `mcp`
  3. `await skill_mgr.scan_skills()` (line 215) → component `skills` (keep `SkillManager()`
     + source registration critical so the registry object exists)
  4. `plugin_runtime.load_all(...)` + `_refresh_extension_sources()` (lines ~417) → `plugins`
  5. `HermesRuntime(...).startup_registrations()` (H3/H5 seam) → `engine_registrations`
  6. channel stack: `ChannelManager`, `register_builtin_channels`, `GatewayBridge`,
     `set_channel_manager`, `await channel_manager.start()` (lines ~460–563) → `channels`
  7. `heartbeat_service`, `automation_engine.start_async(dbos)` + heartbeat reconcile
     (lines ~505–520) → `automation` (gated on the `dbos` component being ready)
  8. `scheduler` start (`cfg.scheduler_enabled`) → `scheduler`
  9. `telegram_service` fallback poll start (lines ~545–552) → `telegram`
  10. group service/orchestrator wiring → `groups`
  11. `register_init_routes` / `register_review_tools` / `register_review_routes`
      (already try/except-degradable) → `extensions`

  Ordering inside the task must preserve the W10 documented dependencies (automation needs
  the DBOS instance; gateway needs `manager`; `await components.wait_ready("dbos")` where the
  code today uses `dbos_instance`).
* **Shutdown** must `await` the deferred task (with a timeout, e.g. 10 s) before tearing
  down in the existing reverse order, so a shutdown during startup cannot race the
  singletons.

### S3 — gating request paths that need deferred components

Per §10.4 (“前端在 MCP 等组件未就绪时照常可用”) the default is: handlers keep working, and
only genuinely MCP-dependent paths gate. Concretely:

* run-start (`_handle_run_start` / orchestrator run path): before the first turn,
  `ok = await services.startup.wait_ready("mcp", timeout=10)`; on `False` proceed degraded
  (turn runs without MCP tools) and emit the existing `run.recovery.notice` envelope with a
  “MCP 仍在启动” message. Do NOT 503 conversation/chat flows.
* `/api/tools` (MCP tool list): return the current (possibly empty) list plus
  `"components": {"mcp": "starting"}`-style hint if cheap; otherwise leave as-is (empty list
  while starting is acceptable).
* Everything else: unchanged.

### S4 — `/api/health` `components` field (api/health_router.py, `health()`)

```python
@router.get("/api/health")
async def health(...) -> ...:
    ...
    startup = getattr(app.state.services, "startup", None)
    components = startup.snapshot() if startup else {}
    payload = {
        "status": "ok" if all(state == "ready" for state in components.values()) else "starting",
        "components": components,   # {"dbos": "starting", "mcp": "ready", ...}
        ...existing fields unchanged...
    }
```

Contract (already consumed by `frontend/src/main/backendProcess.ts` since this wave):
`status === "ok"` only when every registered component is `ready`; any other response is
treated as “contact, not ready” and shown as startup progress. Failure to reach the
backend at all stays “no contact”. **The desktop never kills the backend for slowness
within the 120 s cap** (H8 §10.3, landed in `backendProcess.ts`).

Required test (taskbook §10 测试 “health components 字段测试”) — add to
`core/tests/test_health_components.py`:

```python
import pytest
from httpx import ASGITransport, AsyncClient  # match the existing health-test style

pytestmark = pytest.mark.unit

@pytest.mark.unit
async def test_health_reports_component_states_and_flips_to_ok():
    # in-process app with the lifespan: before deferred startup completes,
    # status == "starting" and components contains dbos/mcp/channels entries;
    # after wait_ready completes (or after marking), status flips to "ok".
    ...
    body = (await client.get("/api/health")).json()
    assert body["components"]["mcp"] in {"starting", "ready", "failed"}
    assert body["status"] in {"starting", "ok"}
```

(Write it against the real app fixture the server lane already uses for lifespan tests;
the contract to assert is: every `components` value ∈ {starting, ready, failed}, and
`status == "ok"` ⟺ all components ready.)

### S5 — DBOS migrations only on version change (capabilities/durable/dbos_backend.py + lifespan)

Evidence: every cold start re-applies **38** DBOS SQLite system-database migrations
(`logs-before/cold-start-*.log`), part of the ~1 s DBOS block.

`durable.start()` currently constructs `DBOS(...)` and launches the process-global instance
(see `dbos_backend.py` lines ~86–137). Change:

1. Persist `{atlas_version, dbos_schema_version}` after a successful start, e.g. in
   `get_config().db_path.parent / "dbos.sqlite"` (table `atlas_meta`) or a sidecar JSON.
2. On start: if the recorded `atlas_version` equals the running one AND `DBOS` reports the
   system schema already initialized, skip the migration step (DBOS exposes the applied
   migration list through its system DB; alternatively compare a stored
   `max(applied_migration)` against the code-known count before calling the launcher).
3. Version mismatch / missing record → run migrations as today, then update the record.
4. Keep `durable.start()` semantics otherwise (process-global singleton, dispatcher, recovery)
   unchanged, and keep the automation engine's reuse of `_dbos_global_instance` intact.

Expected saving: ~0.5–1.0 s on warm starts (the common case); first-run behavior unchanged.

### S6 — expected result

With S1–S5 (plus §3 O1) and the H5-final import win:

| path | projected |
|---|---|
| imports (post H5-final, no O1) | ~3.0 s |
| imports (with O1 mcp-chain deferral) | ~2.1 s |
| critical lifespan (constructors + small DB inits) | ~0.3–0.5 s |
| uvicorn bind → health 200 | ~0.05 s |
| **cold start median** | **~2.5–3.5 s** ✔ ≤ 5 s (A12) |

`core/tests/test_startup_time.py` (integration, landed this wave) already asserts the 5 s
budget with the harness identical to `baseline_metrics.py`; it fails today (6.89–6.92 s
median) and should flip to green when this spec lands. No weakening of that budget.

## 2. §10.3/§10.4 Electron side — landed this wave (for context, no action)

* `frontend/src/main/backendProcess.ts`: no fixed 15 s kill; waits while the process is alive
  and health makes progress, total cap `STARTUP_MAX_WAIT_MS = 120_000`; process exit/spawn
  error → immediate failure carrying the **last 50 log lines**; progress events
  (`probing/starting/ready/failed` + per-component detail) via `onProgress`; paced polling
  (250 ms) even when health answers fast (hot-loop fix).
* `frontend/src/main/electron.ts`: backend spawns in parallel with `createWindow()`;
  progress forwarded on the `backend:startup-progress` IPC channel; real failure still
  shows the error dialog (now including the log tail) and quits.
* `preload/index.cts` + `shared/ipc.ts`: `atlasDesktop.onBackendStartupProgress()`.
* Renderer (`App.tsx`, `useAtlasStore.ts`): `backendStarting`/`startupDetail` state drives
  「后端启动中」on the composer status, sidebar subtitle and connection chip; on `ready`,
  if the first `initialize()` landed in mock mode it re-runs `initialize()` automatically.
* Tests: `frontend/src/main/backendProcess.test.ts` — 5 tests (external attach, slow 30 s
  start not killed, progress detail, immediate exit failure with 50-line tail, 120 s cap).
  Full frontend suite: 160 passed.

## 3. OUT-OF-OWNERSHIP import-chain spec (goal 1 leftovers; measured, not edited)

`python -X importtime -c "import atlas.server"` (before H5-final): total 3.9 s —
atlas bodies 1.13 s, `mcp_types` 0.61 s, `mcp` 0.27 s, fastapi 0.26 s, tenacity 0.14 s,
apscheduler 0.13 s, pydantic 0.12 s, langchain_core in-tree share of 0.44 s standalone.
Standalone costs measured this wave: `import mcp.client.sse` 1.43 s;
`atlas.tools.computer_use` 1.52 s; `atlas.tools.local_execution` 1.42 s;
`atlas.tools.web_extract` 1.57 s (each pulls the mcp chain via `atlas.tools.__init__`);
`langchain_core.messages` 0.44 s; `dbos` 0.94 s (lifespan-time import — fixed by S2.1).

### O1 — defer the tools/mcp imports in `core/atlas/agent/__init__.py` (agent lane) — saves ~0.9 s

`atlas/agent/__init__.py` lines 80–83 (working tree):

```python
from atlas.tools.computer_use import ComputerUseRuntime
from atlas.tools.local_execution import LocalExecutionRuntime
from atlas.tools.mcp_client import MCPClient
from atlas.tools.web_extract import extract_web
```

Every server import of any `atlas.agent.*` submodule pays the mcp chain because importing a
submodule executes `atlas/agent/__init__.py` first. The symbols are used only in
annotations (lines 289, 291–292) and one default (`extract_web`, line 317), and the module
has `from __future__ import annotations`. Change:

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:  # annotations are strings; runtime imports become lazy
    from atlas.tools.computer_use import ComputerUseRuntime
    from atlas.tools.local_execution import LocalExecutionRuntime
    from atlas.tools.mcp_client import MCPClient
    from atlas.tools.web_extract import extract_web
```

and for the one runtime default:

```python
self._web_extractor = web_extractor or _default_web_extractor()
...
def _default_web_extractor():
    from atlas.tools.web_extract import extract_web
    return extract_web
```

Keep `MCPClient`/`LocalExecutionRuntime`/`ComputerUseRuntime`/`extract_web` importable from
`atlas.agent` for any legacy importer via PEP 562 if needed:

```python
_LAZY = {"MCPClient": "atlas.tools.mcp_client", ...}
def __getattr__(name: str): ...
```

Verification: `core/scripts/startup_probe.py --skip-cold` before/after; target −0.9 s.

### O2 — make `core/atlas/tools/__init__.py` lazy (tools lane) — safety net

Currently `atlas/tools/__init__.py` eagerly does
`from atlas.tools.mcp_client import MCPClient, ToolInfo`, so touching any `atlas.tools.*`
submodule (e.g. `atlas.agent.results` → `atlas.tools.output_limits`) pulls mcp. PEP 562
`__getattr__` re-export keeps `from atlas.tools import MCPClient` working (tests use
`from atlas.tools import mcp_client` submodule imports — unaffected).

### O3 — api router import bodies (`atlas/api/application.py`, integrations_router → apscheduler ~0.13 s; memory_router 89 ms self; workspace_router 65 ms …) — H5-final lane, optional

Total ~0.6 s of pure `atlas.*` module-body cost plus apscheduler. Do NOT chase this before
A9 (route snapshot 394 ops identical) — lazy router inclusion was already a review finding
once. Only worth revisiting if, after O1 + S1–S6, cold start is still > 5 s.

### O4 — `atlas/cli.py` module-level `rich` import (~0.11 s) — H9 lane, optional

`from rich.console import Console` at import time; the `serve`/`run` paths could construct
the console lazily. Minor.

## 4. Measurement harness (owned by H8 lane, reusable)

* `core/scripts/startup_probe.py` — cold start (same method as `baseline_metrics.py`,
  preserved logs) + `import atlas.server` wall time + importtime breakdown → JSON.
* `core/tests/test_startup_time.py` — the §10 gate (integration, 5 s median budget).
* `artifacts/h8-startup/` — `before.json`, `after.json`, raw logs, this spec's context.
