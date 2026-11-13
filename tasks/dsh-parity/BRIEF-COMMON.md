# DSH Parity Worker Brief (shared)

You are an implementation worker on Atlas (`D:\Atlas`), a local-first personal AI
assistant: Python FastAPI backend (`core/atlas/`), Electron+React desktop
(`frontend/`). Atlas is being brought to parity with DeepSeek-Harness (DSH) and
beyond. The gap ledger is `docs/parity/DSH-GAP-LEDGER.md` — read the rows your
brief names, they carry `path:line` evidence for both sides.

## Non-negotiable rules

1. **Never rewrite the `messages` table semantics.** `messages` is read by 16
   mixins, FTS triggers, compaction, rewind, fork, export and migration. Add
   alongside it, never replace it.
2. **`SessionDB._execute_write` is the only transaction boundary.** It holds a
   non-reentrant `threading.Lock` (`atlas_state.py:598`) and runs `BEGIN
   IMMEDIATE`. Calling `_execute_write` again from inside its callback DEADLOCKS.
   Opening a second `SessionDB` inside a live transaction blocks ~21s then raises
   `database is locked`. If you must write inside a callback, use the cursor it
   gives you.
3. **Three event-name sources must move together:** `core/atlas/api/event_names.py`,
   `frontend/src/renderer/services/runtimeEvents.ts` (`known` set), and
   `frontend/src/types/runtime.ts` (`AgentEventType`). A name missing from the
   second is silently dropped at runtime. Run
   `python -m pytest -q tests/test_event_contract.py` after touching any of them.
4. **New router must be added to the tuple in `core/atlas/api/application.py`
   (~line 135).** Otherwise the module imports fine and the route does not exist.
5. **New service must be added to `AppServices`** (`core/atlas/api/app_services.py`)
   and filled in `server.py` lifespan, or a code path silently gets `None`.
6. **Tests need `@pytest.mark.unit`** (or `@pytest.mark.integration`); `pytest`
   runs with `addopts = "-m unit"` and silently deselects unmarked tests.
7. **Do not touch:** `origin_guard` (never loosen), `data/memory/**` (the user's
   real memory, separate git repo), `config/atlas.toml` / `data/user-settings.json`
   (contain real secrets), anything outside your assigned files.
8. **Do not reformat or reorganise files you were not assigned.** The tree has
   long-standing uncommitted work; only your own additions are yours.

## Verification you must run before claiming done

```bash
cd core
python -m pytest -q -p no:cacheprovider <your test files>
python -m pytest -q -p no:cacheprovider tests/test_event_contract.py   # if you touched events
```
Report the exact command and its output. "Tests pass" without pasted output is
not evidence. If a test you did not write fails, check whether it also fails at
`git stash` baseline before blaming your change.

## Known-failing at baseline (do NOT try to fix, do NOT count as your regression)

- `tests/test_route_snapshot.py` (2 failures: 852 live routes vs 839 frozen)
- `tests/test_c4_plugin_e2e.py` (1: hook trust message wording)
- `tests/test_atlas_mcp_config.py::test_compaction_agent_pins_bare_wire_id_from_host_shaped_config`
- `tests/test_session_migration.py` (7: `ModuleNotFoundError: atlas_state`)
- `tests/test_mcp_client.py`, `tests/test_mcp_lifecycle_shutdown.py` (several: Node pin, mock shapes)
- Running the whole suite in one process can hang after the summary (known);
  run files in small groups with `timeout`.

## Deliverable

Work only in the worktree you were given. Commit your changes on your branch with
a descriptive message. Then write `tasks/dsh-parity/RESULT-<your-batch>.md`
listing: files changed, tests added (names), exact test output, and anything you
could NOT do with the reason. Do not claim a capability works if you did not run
it.
