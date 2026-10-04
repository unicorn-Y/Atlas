# H0.1 host source preservation

The pre-existing host source changes were committed unchanged at
`a2c200c8f4668a0bf24800cc09add7d0e99766fd` on
`wip/host-uncommitted-2026-10-04`. GitHub's branch head was independently
checked with `git ls-remote` and matched the local commit. This is a preservation
checkpoint, not a claim that these changes have been accepted for main.

| Preserved file | Existing change |
|---|---|
| `core/atlas/api/skills_market_router.py` | Cancels an in-flight market search when the HTTP client disconnects. |
| `core/atlas/desktop_entry.py` | Adds the search-worker entry point and preloads the shared Hermes utility module before serving. |
| `core/atlas/engine/hermes_runtime.py` | Normalizes MCP transports/Node launchers and unregisters server-owned Hermes registry scopes. |
| `core/atlas/engine/local_runtime_adapter.py` | Serializes Hermes local-runtime imports and preloads shared host modules. |
| `core/atlas/engine/tool_registry.py` | Tracks and removes stale Atlas copies of MCP tools by scope. |
| `core/atlas/models/__init__.py` | Reports gateway configuration precedence and exports both OpenAI endpoint environment names. |
| `core/atlas/server.py` | Adds gateway source metadata, persists MCP configuration, clears removed MCP scopes, cancels market searches on shutdown, and reports disabled services as 503. |
| `core/atlas/skills/market.py` | Runs market searches in owned subprocesses with cancellation, limits, and tree cleanup. |
| `core/atlas/skills/market_search_worker.py` | Adds the subprocess search-worker implementation. |
| `core/atlas/tools/mcp_client.py` | Gives transport scopes an owning task and adds bounded startup diagnostics and shutdown cleanup. |
| `core/tests/fakes/fake_mcp_server.py` | Extends the fake MCP fixture used by lifecycle/configuration tests. |
| `core/tests/test_c1_lifecycle_runtime.py` | Expects bare gateway model IDs instead of routing-prefixed `openai/` IDs. |
| `core/tests/test_c1_lifecycle_subtask.py` | Matches the child model's bare gateway wire ID. |
| `core/tests/test_desktop_entry.py` | Adds desktop entry-point regression coverage. |
| `core/tests/test_desktop_shutdown.py` | Adds desktop backend shutdown coverage. |
| `core/tests/test_hermes_mcp_config.py` | Tests MCP transport/launcher normalization. |
| `core/tests/test_local_models_adapter.py` | Tests local-runtime import synchronization. |
| `core/tests/test_market_search_worker.py` | Tests the owned search-worker implementation. |
| `core/tests/test_mcp_lifecycle_shutdown.py` | Tests MCP transport lifecycle/shutdown behavior. |
| `core/tests/test_mcp_server_hermes_sync.py` | Tests MCP configuration and registry synchronization. |
| `core/tests/test_mcp_startup_diagnostics.py` | Tests bounded MCP startup diagnostics. |
| `core/tests/test_models.py` | Tests gateway precedence/source metadata. |
| `frontend/scripts/build-backend.mjs` | Collects the Hermes source root, dynamic runtime modules and package metadata for packaging. |
| `frontend/src/main/backendProcess.ts` | Raises the old startup timeout to 45s, prefers the project venv, retries health probes, and uses the desktop entry point. |
| `frontend/src/main/backendProcess.test.ts` | Adds backend Python-selection/launch regression coverage. |
| `frontend/src/main/electron.ts` | Corrects development navigation matching and adds renderer/load recovery. |
| `frontend/src/main/electron.navigation.test.ts` | Tests Electron navigation/recovery behavior. |
| `frontend/src/renderer/components/ForkTree.tsx` | Avoids a branches request for an empty active conversation ID. |
| `frontend/src/renderer/components/ForkTree.regression.test.ts` | Tests the empty-conversation branches case. |
| `frontend/src/renderer/components/x2/ComputerStatusSection.tsx` | Renders string or structured computer-driver metadata. |
| `frontend/src/renderer/components/x2/ComputerStatusSection.regression.test.tsx` | Tests structured computer-driver rendering. |
| `frontend/src/renderer/services/x2Api.ts` | Extends the computer-driver response type. |
| `design/atlas-glass-prototype.html` | Preserves the existing standalone UI prototype. |
| `arx.html` | Preserves the existing standalone HTML artifact. |
| `lite.html` | Preserves the existing standalone HTML artifact. |
| `ddg.json` | Preserves the existing JSON artifact. |

Generated build/profile artifacts (roughly 8 GB), runtime `engine/` data,
channel SQLite sidecars and generated skill/evolution state remain untouched
in `D:\Atlas`. They are not source edits, and no runtime credentials or
conversation databases were uploaded. Main implementation uses the separate
worktree `D:\Atlas-h1-core-hardening`.

Potential overlaps are retained for the user to decide: the WIP's 45s fixed
startup timeout differs from H8's progress-aware 120s contract; its provider
environment writes conflict with H3's prohibition on runtime environment
mutation; its MCP and local-runtime lifecycle changes overlap H1/H3 work.
The WIP's UI/prototype and packaging changes are not automatically applied to
the hardening implementation.
