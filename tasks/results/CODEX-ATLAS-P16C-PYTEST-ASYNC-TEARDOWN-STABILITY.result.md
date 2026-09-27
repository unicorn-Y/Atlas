# CODEX-ATLAS-P16C-PYTEST-ASYNC-TEARDOWN-STABILITY

## Status

Completed. Base HEAD: `6009e6a9478a2ec76de79494a64f54c38ffe6eb7`.

## Root cause and reproduction

`core/tests/test_server.py` isolated the user settings file and scheduler environment, but did not isolate Atlas's cached machine-local configuration or data root. The full suite therefore loaded `D:\Atlas\config\atlas.toml`, whose MCP configuration starts filesystem, git, and Brave Search subprocesses. The configured scheduler could also be enabled in a server lifespan. Those external lifecycles ran inside pytest's async fixture loop and left teardown waiting in `asyncio.Runner._cancel_all_tasks`.

Before the fix, the full file collected 52 tests and reached `test_list_mcp_servers_empty` at 63%, then stalled during async fixture teardown. A `py-spy` dump placed the pytest main thread in `_cancel_all_tasks` / `Runner.close` / pytest-asyncio runner fixture teardown; its subprocess tree included `npx`/Node, `uvx`/`uv`, `mcp-server-git`, and Python. A temporary exact-empty assertion also failed against the old fixture because machine-configured MCP servers appeared in the response. The initial diagnostic attempt that placed its output log under `--basetemp` produced a separate Windows `PermissionError` during pytest cleanup; that was diagnostic contamination and not counted as the reproduced teardown hang.

## Change

- Added an autouse fixture for server tests that redirects `CONFIG_PATH`, `DATA_ROOT`, and `USER_SETTINGS_PATH` into each test's temporary directory, resets the config singleton, disables the scheduler, and configures no auto-start MCP servers.
- Strengthened the empty MCP endpoint assertion to require an empty list.
- After each async client lifespan, assert that the fixture loop has no remaining pending tasks, including task names and coroutine names in any failure.
- Applied the Ruff-required import ordering and line wrapping in the touched test file.
- No production/runtime behavior changed.

## Verification

- Before-fix teardown stall reproduced at 63%; Python stack and child-process tree inspected. Red endpoint assertion confirmed machine-local MCP leakage.
- Minimal empty-MCP test: 5 consecutive runs passed (`1 passed, 51 deselected` each).
- `core/tests/test_server.py`: 3 consecutive runs passed (`52 passed` each; 26.68s, 27.05s, 25.33s).
- P16A bundled Node filesystem MCP live smoke: passed (`1 passed`, 60.37s).
- P16B packaged backend bundled Node filesystem Agent read-file E2E: passed (`1 passed`, 74.32s).
- MCP/Agent/P15E regression selection (`test_mcp_client.py`, `test_agent.py`, `test_agent_capabilities.py`, `test_skill_dependency_distribution.py`, `test_skill_lifecycle.py`, `test_skill_registry.py`, `test_skill_registry_api.py`, `test_skill_discovery.py`, `test_skills.py`): `182 passed` in 35.41s.
- `ruff check core/tests/test_server.py`: passed.
- `git diff --check`: passed.
- After verification, no pytest process from these test runs remained. Other pre-existing host/desktop MCP and Atlas service processes were observed and left untouched.

## Delivery

Commit and remote `main` HEAD verification are recorded by the repository history and final worker closeout.
