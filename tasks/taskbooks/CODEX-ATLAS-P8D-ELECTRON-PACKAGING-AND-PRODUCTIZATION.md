# CODEX-ATLAS-P8D-ELECTRON-PACKAGING-AND-PRODUCTIZATION

## Goal
Move Atlas from development desktop app toward a distributable product.

## Scope
- Add Electron packaging configuration.
- Prepare Windows application build flow.
- Add application metadata and icons placeholders where appropriate.
- Verify packaged app startup with existing backend lifecycle.
- Handle production configuration paths.

## Do Not Change
- MemoryOS integration.
- Planner/multi-agent system.
- MCP architecture.
- Runtime protocol.
- Streaming protocol.

## Acceptance
- Production build command documented and working.
- Packaged application launches.
- No secrets included in package artifacts.

### Runtime test baseline (replaces "Existing runtime tests remain passing")

**A plain `pytest` over `core/tests/` never terminates on this host.** Run it
per-file, and run `tests/test_server.py` **per class** (its
`TestMCPServerManagement` class additionally **per test**). Always wrap with
`timeout`. Full measured procedure and root causes:
`docs/KNOWN-BASELINE-ISSUES-2026-09-26.md`.

Measured on this Windows host:

| File / class | How to run | Expected |
|---|---|---|
| tests/test_agent.py | per-file | 24 passed |
| tests/test_agent_capabilities.py | per-file | 3 passed |
| tests/test_config.py | per-file | 6 passed, 1 KNOWN-BASELINE failure |
| tests/test_models.py | per-file | 10 passed |
| tests/test_memory.py | per-file | 14 passed, 1 KNOWN-BASELINE failure |
| tests/test_scheduler.py | per-file | 28 passed |
| tests/test_skills.py | per-file | 42 passed |
| tests/test_mcp_client.py | per-file | 14 passed |
| tests/test_server.py (9 classes) | **per-class** | 35 passed |
| tests/test_server.py::TestMCPServerManagement | **per-test** | 4 passed, 1 KNOWN-BASELINE hang |

Totals over 183 collected: **180 passed + 2 KNOWN-BASELINE failures + 1 KNOWN-BASELINE hang.**

Do NOT regress: any NEW failure or hang beyond the three KNOWN-BASELINE items fails acceptance.

### KNOWN-BASELINE failures (pre-existing, verified NOT caused by local config)

1. `test_config.py::TestAtlasConfigFromData::test_db_path_absolute`
   Windows treats `"/absolute/path/test.db"` as root-relative (no drive letter),
   so it is joined onto the drive root. The pre-change `PROJECT_ROOT / p` code
   produces the byte-identical result `D:\absolute\path\test.db`; the assertion
   is simply not Windows-portable. Out of P8D scope.

2. `test_memory.py::TestMessages::test_message_with_metadata`
   `KeyError: 'metadata'` — `MemoryStore.get_conversation_messages()` does not
   return a `metadata` column although the test expects one. Test runs against a
   tmp_path db, fully isolated from local data. Out of P8D scope.

3. `test_server.py::TestMCPServerManagement::test_list_tools_exposes_connected_server_tools`
   The test body PASSES — the pytest process then never exits (>75s, killed by
   `timeout`, exit 124). It is the only test that lets Atlas' real MCP bootstrap
   run: the `client` fixture enters `lifespan(app)` before the test body's
   `monkeypatch.setattr(server, "mcp_client", …)` takes effect, so Atlas genuinely
   spawns the stdio MCP server through `npx` (a `node.exe` child). The client logs
   `mcp.server_stopped`, but the child handles / stdio pipes are not released, so
   the interpreter cannot exit on Windows. Reproduced with the example baseline
   config → unrelated to local settings. MCP is under "Do Not Change", so fixing
   it is out of P8D scope; run this test standalone and expect the hang.

   `test_add_server_invalid_transport` is NOT itself broken: it passes standalone
   in ~8.1s and hangs only when run after the test above within the same process
   (state accumulation — see `docs/KNOWN-BASELINE-ISSUES-2026-09-26.md` §4).
   Therefore run `TestMCPServerManagement` **per test**, and read
   `tests/test_server.py` **per class** — never as a whole file.

### Local runtime configuration — DO NOT modify or commit

These hold real gateway credentials or app runtime state and are intentionally
outside version control / outside the installer:

- `config/atlas.toml`                        (gitignored; local dev gateway)
- `data/user-settings.json`                  (gitignored; runtime-selected model)
- `%APPDATA%\Atlas\config\atlas.toml`        (packaged-app runtime config, pre-provisioned)
- `config/atlas.example.toml` must remain credential-free — it IS packed into the
  installer via `extraResources`, and acceptance requires no secrets in artifacts.
