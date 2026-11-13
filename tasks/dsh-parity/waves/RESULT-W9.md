# W9 result

## Rows

- **X2 — PARTIAL.** Skill, command, hook and newly connected MCP contributions have reverse-order disposers. Disposers support async callbacks; `load_all`, `reload`, and `set_enabled(False)` await them. A fake async MCP client verified that reload disconnects the old contribution before reconnecting. A real plugin MCP server lifecycle was not exercised in a live Atlas process, so this is not CLOSED.
- **X4 — PARTIAL.** Added ordered config row composition with row-id replacement, before/after insertion, deletion, and a JSON preview helper. Existing patch row-id behavior remains covered. The helpers are not connected to profile/bundle persistence or an `atlas --dump-config` CLI command, so profile/bundle end-to-end behavior remains open.
- **X8 — PARTIAL.** Added a `PluginRealm` facade that filters capability discovery and invocation to selected `plugin:<name>` sources. The facade is not persisted as child rows in `AgentPresetStore` and is not constructed/wired by Agent run setup; preset-level isolation remains open.

## Changed files

- `core/atlas/plugins/runtime.py`
- `core/atlas/plugins/patch_layer.py`
- `core/atlas/api/plugins_router.py` (await async plugin disable cleanup)
- `core/tests/test_plugin_reload_idempotent.py`
- `core/tests/test_plugin_disable_withdraws.py`
- `core/tests/test_plugins.py`
- `core/tests/test_plugin_patch_layer.py`
- `core/tests/test_plugin_realm.py`
- `docs/parity/DSH-GAP-LEDGER.md`

## Test evidence

RED for X2 before implementation:

```text
tests/test_plugin_reload_idempotent.py::test_async_mcp_contribution_is_disposed_on_reload FAILED
AssertionError: assert [] == ['demo-mcp']
1 failed, 6 passed
```

RED for X4 before implementation:

```text
test_config_layers_replace_and_insert_by_row_id_in_declared_order FAILED
AttributeError: module 'atlas.plugins.patch_layer' has no attribute 'merge_config_layers'
test_dump_config_preview_returns_serialized_effective_config FAILED
AttributeError: module 'atlas.plugins.patch_layer' has no attribute 'dump_config_preview'
2 failed, 25 passed
```

Final plugin-focused verification (from `core/`):

```text
$files = Get-ChildItem tests -Filter 'test_plugin*.py' | ForEach-Object { $_.FullName }
python -m pytest @files tests/test_plugins.py -q -p no:cacheprovider
...........................................................              [100%]
59 passed, 5 warnings in 8.93s
```

Warnings are existing FastAPI `on_event` and Pydantic class-config deprecations emitted by imported API modules.

## Live model evidence (port 8829)

The backend started successfully on `http://127.0.0.1:8829` and reported `Application startup complete` / `Uvicorn running`. The required live check did not complete a model turn:

```text
python scripts/dsh_live_ws_check.py 8829 "Reply with exactly the word: OK"
[event] run.started
[event] run.phase
[terminal] run.failed data={"category": "runtime", "detail": "TypeError: int() argument must be a string, a bytes-like object or a real number, not 'NoneType' (run log: .../99fd281b-d98f-4716-89a8-c04e99602617.jsonl)"}
[reply] ''
[result] terminal=run.failed chars=0
```

The server was stopped after the check. No model reply was observed. This failure has not been proven related to W9; consequently there is no live-model pass claim.
