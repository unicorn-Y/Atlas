# Atlas Runtime Tests — Known Baseline Issues

Recorded 2026-09-26 by **AI计划** while verifying the local runtime configuration
during P8D. Scope: `core/tests/` on this Windows host
(Python 3.11, pytest 9.1.1, pytest-asyncio 1.4.0 with `asyncio_mode = "auto"`).

Purpose: give P8D (and any successor taskbook) an **executable, measured** test
baseline, and hand the worker a precise root cause for each item instead of a
"it hangs" report.

**None of the items below are caused by local configuration.** Every one was
reproduced with `ATLAS_DATA_DIR` pointing at an empty directory, which makes
`load_config()` fall back to `config/atlas.example.toml` — i.e. the pristine
baseline config, with the local gateway settings completely out of the picture.

---

## 1. How to run the suite (measured — do NOT use a plain `pytest`)

`python -m pytest` over `core/tests/` **does not terminate on this host**
(183 items collected, hangs part-way; see Issue 2). Run it this way instead:

```bash
cd D:/Atlas/core

# 1) Per-file for everything except test_server.py
python -m pytest tests/test_agent.py tests/test_agent_capabilities.py \
  tests/test_config.py  tests/test_models.py tests/test_memory.py \
  tests/test_scheduler.py tests/test_skills.py tests/test_mcp_client.py \
  -q --no-header -p no:cacheprovider

# 2) test_server.py — PER CLASS (never the whole file at once)
for cls in TestRuntimeProtocol TestHealth TestAgentCapabilities TestModels \
           TestConversations TestSearch TestFacts TestKnowledge \
           TestWebSocketProtocol ; do
  timeout 100 python -m pytest "tests/test_server.py::$cls" -q --no-header -p no:cacheprovider
done

# 3) TestMCPServerManagement — PER TEST (one of its five hangs, see Issue 1)
for t in test_list_mcp_servers_empty test_list_tools_exposes_connected_server_tools \
         test_add_server_invalid_transport test_remove_server_404 test_restart_server_404 ; do
  timeout 70 python -m pytest "tests/test_server.py::TestMCPServerManagement::$t" -q --no-header -p no:cacheprovider
done
```

`timeout` is not decoration: without it the suite never returns.

---

## 2. Measured baseline (all numbers below are observed, not inferred)

| File | How | Expected |
|---|---|---|
| `tests/test_agent.py` | per-file | 24 passed |
| `tests/test_agent_capabilities.py` | per-file | 3 passed |
| `tests/test_config.py` | per-file | 6 passed, **1 known failure** (Issue 3) |
| `tests/test_models.py` | per-file | 10 passed |
| `tests/test_memory.py` | per-file | 14 passed, **1 known failure** (Issue 4) |
| `tests/test_scheduler.py` | per-file | 28 passed |
| `tests/test_skills.py` | per-file | 42 passed |
| `tests/test_mcp_client.py` | per-file | 14 passed |
| `tests/test_server.py` (9 classes) | per-class | 35 passed |
| `tests/test_server.py::TestMCPServerManagement` | per-test | 4 passed, **1 known hang** (Issue 1) |

Totals: **183 collected = 180 passed + 2 known failures + 1 known hang.**
A NEW failure or hang beyond these three items fails acceptance.

---

## 3. Issue 1 — `test_list_tools_exposes_connected_server_tools`: the test passes, the process never exits

**Symptom.** This single test never returns — standalone, inside its class, or as
part of the file. Killed by `timeout` at 70–75s (exit 124).

**Evidence (captured with `-s`).** The test body itself completes and the
assertion passes; the hang is *after* the test, in interpreter/lifespan shutdown:

```
2026-09-26 03:38:29 [info] config.loaded       path=...\atlas-base-ws\config\atlas.toml
2026-09-26 03:38:29 [info] mcp.starting        count=1 names=['filesystem']
npm notice run atlas@0.1.0 npx
npm notice run mcp-server-filesystem D:/Atlas
Secure MCP Filesystem Server running on stdio
2026-09-26 03:38:32 [info] mcp.server_initialized  protocol=2025-11-25 server=filesystem
2026-09-26 03:38:32 [info] mcp.server_ready   server=filesystem tools=[...14 tools...]
2026-09-26 03:38:32 [info] skills.scanned     count=11 directory=D:\Atlas\skills
.                                     <-- test body passed
2026-09-26 03:38:32 [info] mcp.server_stopped server=filesystem   <-- teardown ran
                                      <-- and then: nothing. Process never exits.
```

**Root cause (probable, pending worker confirmation).** This is the only test that
lets Atlas' genuine MCP bootstrap run. Atlas spawns the stdio MCP server through
`npx` (see the two `npm notice` lines → a `node.exe` child), and the `client`
fixture enters `async with lifespan(app)` so the spawn happens at fixture time —
**before** the test body's `monkeypatch.setattr(server, "mcp_client", mcp)`, which
only swaps the module-level reference and cannot prevent the real spawn. The client
logs `mcp.server_stopped`, but the child process handles / stdio pipes are not fully
released, so the pytest process cannot exit on Windows.

**Suggested fix.**
- In the MCP client shutdown path, explicitly `terminate()`/`kill()` the child,
  `await proc.wait()`, and close stdin/stdout/stderr — or manage it with
  `anyio.open_process(...)` as a context manager.
- Independently: this test stubs `mcp_client` anyway, so the real spawn is
  unnecessary for what it asserts. Disabling MCP bootstrap under test (e.g. an env
  flag honoured by the lifespan) removes the dependency entirely.

---

## 4. Issue 2 — sequential whole-file runs accumulate state and hang later

**Symptom.** `pytest tests/test_server.py` hangs on the 26th/27th test
(`TestMCPServerManagement::test_add_server_invalid_transport`). Excluding that class
outright, the same command hangs on the 32nd
(`TestWebSocketProtocol::test_run_start_emits_agent_events`).

**Evidence it is accumulation, not the tests themselves.** Running
`TestWebSocketProtocol` **as a class** gives `7 passed in 9.07s`, and
`test_run_start_emits_agent_events` also passes standalone in 9.38s. The same two
tests only hang once ~31 other tests have run in the same process.

**Root cause.** The `client` fixture does `async with lifespan(app)` per test while
`app` is a **module-level singleton** in `atlas.server`; the MCP server, memory store
and scheduler are therefore re-initialised and torn down ~40 times in one process.
After enough cycles the next lifespan entry (or the sync `starlette` `TestClient`
used inside `test_run_start_emits_agent_events`) blocks.

**Suggested fix.** Make the app/lifespan per-test (factory fixture) instead of
reusing the module singleton, and/or make MCP bootstrap a no-op unless explicitly
enabled during tests.

---

## 5. Issue 3 — `test_config.py::test_db_path_absolute` is not Windows-portable

```
assert cfg.db_path == Path("/absolute/path/test.db")
AssertionError: WindowsPath('D:/absolute/path/test.db') != WindowsPath('/absolute/path/test.db')
```

`"/absolute/path/test.db"` has no drive letter, so `Path.is_absolute()` is `False`
on Windows and the path is joined onto the drive root. **Proof it predates the local
configuration change:** the pre-change code (`PROJECT_ROOT / p`) produces the
byte-identical result `D:\absolute\path\test.db`; the assertion is simply not
portable, and the test uses neither the config file nor local data.

**Suggested fix.** Use `tmp_path` (a genuinely absolute path on any platform), or
`pytest.skip` on Windows.

---

## 6. Issue 4 — `test_memory.py::TestMessages::test_message_with_metadata` raises `KeyError: 'metadata'`

```
async def test_message_with_metadata(self, store): ...
>   meta = json.loads(msgs[0]["metadata"])
E   KeyError: 'metadata'
```

`MemoryStore.get_conversation_messages()` does not return a `metadata` column,
although the test writes metadata via `save_message(..., metadata={...})` and expects
to read it back. The test runs against a `tmp_path` database, fully isolated from
local data.

**Suggested fix.** Either have `get_conversation_messages()` return the column, or
drop the assertion if the column is intentionally omitted.

---

## 7. Cleared by this pass (do not re-investigate)

- Every test file other than the four items above passes on this host.
- No baseline failure or hang is attributable to `config/atlas.toml`,
  `data/user-settings.json`, or the local gateway switch to
  `http://127.0.0.1:8045/v1` (all reproduced against the example baseline config).
