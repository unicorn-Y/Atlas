# PAR-07-C — production wiring for DSH skill roots + real precedence ladder (worker C)

- Date: 2026-11-19
- Worktree: `D:/Atlas/.worktrees/zcode-exec06-skill-sources`
- Branch: `zcode/exec06-skill-sources`
- Baseline: `060071ab2ecf86d41cab90e98160183ce126bc69` (060071ab), unchanged; no commit/push/merge performed.
- Scope: close F09 gaps G1 (production-configurable custom/runtime/bundled roots) and G3 (same-name precedence matrix), verify default/workspace/runtime boundaries, and add real tests. Main checkout and main queue read-only; only this receipt file written outside the worktree. `core/atlas/server.py` is in-flight in main, so the wiring is delivered as a minimal candidate in this worktree with explicit merge anchors (section 7).

## 1. Starting state (pre-existing IMPL-5, not authored this pass)

The worktree already carried IMPL-5 (uncommitted vs 060071ab):

- `core/atlas/skills/__init__.py`: DSH source ladder in `SKILL_SOURCE_PRIORITY` (`project-dsh` 40, `project-agents` 38, `runtime` 25, `custom` 22, `user-dsh` 19, `user-agents` 18, `bundled` 5), `<workspace>/.dsh|.agents/skills` and `~/.dsh|.agents/skills` sources, optional `custom_skill_dirs` / `runtime_skills_dir` / `bundled_skills_dir` parameters.
- `core/tests/test_skill_sources_dsh.py`: 5 tests; one assertion was conditional (`if "user-dsh" in sources else True`) and therefore never exercised, and the bundled root in the test used the flat layout while the bundled source is category-layout (the bundled copy was never scanned). Prior baseline receipt: `evidence/exec06-f09-skill-sources-20261118.txt`, `exec06-skill-sources-runs.txt`, `exec06-skill-sources-regression.txt`.

This pass adds G1 wiring + G3 tests and fixes those two test-quality defects.

## 2. Files changed by this pass (worktree-relative; total diff includes IMPL-5)

| File | This pass | Cumulative vs baseline |
|---|---|---|
| `core/atlas/skills/__init__.py` | `+ skill_source_config_overrides()` (~43 lines), `SkillSource`/`default_skill_sources` docstrings clarifying filesystem-vs-virtual runtime; `+110/−3` total incl. IMPL-5 |
| `core/atlas/server.py` | +6: local import + `**skill_source_config_overrides(cfg)` in the lifespan source assembly |
| `core/atlas/cli.py` | +10/−2: `atlas exec` preload path passes the same config overrides |
| `config/atlas.example.toml` | +8: documented `[extensions]` keys (comments only) |
| `core/tests/test_skill_sources_dsh.py` | rewritten/expanded from 5 to **16 tests** (+384/−0) |

`git diff --stat` (whole worktree, incl. IMPL-5): 5 files, +518/−5. `config/atlas.toml` generated during a smoke run was deleted; it is gitignored.

## 3. Production wiring (G1 closed)

### 3.1 Mechanism reused

The existing config point is the raw `extensions.*` convention (no schema registry), already used by `extensions.hermes_skills` in `server.py`. `skill_source_config_overrides(config)` reuses `AtlasConfig.get()` (so atlas.toml + expert overlay + project/session/request layering apply) and maps:

- `extensions.custom_skill_dirs` — one path string or a list of paths → `custom_skill_dirs` (each becomes `custom:<dir-basename>`, priority 22).
- `extensions.runtime_skills_dir` — one path → `runtime_skills_dir` (priority 25).
- `extensions.bundled_skills_dir` — one path → `bundled_skills_dir` (priority 5, category layout).

Missing, blank, and wrongly-typed values are ignored; non-existent paths are filtered by `default_skill_sources`, so a stale config cannot prevent boot or change the default source list.

### 3.2 Entry points

- Server: `core/atlas/server.py` lifespan, immediately after `skill_mgr = SkillManager()`. It already read `extensions.hermes_skills`; the new kwargs are added to the same `default_skill_sources(...)` call. One shared `SkillManager`; plugin dirs still join later via `run_drive._refresh_extension_sources()` → `replace_skill_sources("plugin:", ...)`.
- CLI: `core/atlas/cli.py` `atlas exec` (`exec_command`, around line 1816). The CLI only assembles sources when a preload set exists (`--skills`, agent collection, or project `active_skills`); that path now applies the same config overrides so a preloaded skill living in a custom/runtime root resolves.
- Inspected but unchanged: `core/atlas/config.py` (plain dotted `get`), `core/atlas/plugins/runtime.py` + `core/atlas/api/run_drive.py` (plugin `skills/` dirs are `plugin:*` sources at priority 60), `core/atlas/api/extension_packages_router.py` + `core/atlas/skills/market.py` (extension packages register read-only catalogs / install into the shared Atlas skills root, so they are not the DSH `custom` root). `core/atlas/api/agent_skills_router.py:352` still builds a bare `SkillManager()` for usage stats (pre-existing inconsistency, untouched).

### 3.3 Server-path smoke (no uvicorn lifespan, since server.py is in-flight in main)

Ran `atlas.server.get_config()` + `atlas.server._default_workspace()` with `ATLAS_DATA_DIR` pointing at a temp dir whose `data/user-settings.json` set `default_workspace` and whose `config/atlas.toml` set all three extension roots. Same-name skill in project `.dsh`, runtime, custom, bundled:

```
workspace: C:\Users\...\Temp\tmp.C4ZIhTIqig\ws
names: ['atlas', 'bundled', 'library', 'claude-user', 'user-agents', 'claude-project', 'project-dsh', 'runtime', 'custom:custom-root']
server_winner: ('project-dsh', 'project dsh copy')
EXIT 0
```

A separate real-TOML smoke (`load_config(path)` + helper + `default_skill_sources`) produced:

```
overrides: {'custom_skill_dirs': ['.../custom-root'], 'runtime_skills_dir': '.../runtime-root', 'bundled_skills_dir': '.../bundled-root'}
names: ['atlas', 'bundled', 'library', 'claude-user', 'claude-project', 'runtime', 'custom:custom-root']
winner: ('runtime', 'runtime copy', 'SKILL.md')
default_names: ['atlas', 'library', 'claude-user', 'claude-project']   # empty config, absent dirs
EXIT 0
```

## 4. Precedence ladder (G3 closed)

The conditional assertion was removed. `test_custom_runtime_and_bundled_roots_follow_the_ladder` now creates the `user-dsh` root and asserts unconditionally `runtime > custom > user-dsh`. The bundled copy is written as `<bundled>/packaged/<skill>/SKILL.md` (category layout), so it is actually scanned.

New coverage, all through a real `SkillManager.scan_skills_sync()` + `get_skill()`:

1. `test_same_name_precedence_walks_the_whole_dsh_ladder` — one same-name skill in all seven roots; asserts the exact `SKILL_SOURCE_PRIORITY` values, strict descending order, and that `SkillManager` resolves `project-dsh` with the expected description/path.
2. `test_adjacent_dual_source_same_name_prefers_higher_priority` — 6 parameterized cases (`project-dsh-beats-project-agents` … `user-agents-beats-bundled`). Each registers exactly two same-name sources and asserts the higher rung wins, including the `bundled` category layout.
3. Existing project/user precedence tests retained, also via `SkillManager`.

Atlas mapping verified: `project-dsh` 40 > `project-agents` 38 > `runtime` 25 > `custom` 22 > `user-dsh` 19 > `user-agents` 18 > `bundled` 5 (> `atlas` 10 / `library` 11 / `atlas-user` 12 / `hermes` 15 / `claude-user` 20 / `claude-project` 30 / `plugin` 60 interleaved per Atlas's high-wins mapping). This is a relative-order inversion of DSH's lower-wins numeric ranks, not a numeric copy.

## 5. Boundaries verified (G2 distinction)

- **Absent-directory default**: `test_absent_dsh_roots_leave_the_source_list_unchanged` asserts `[atlas, library, claude-user, claude-project]` with a workspace, and `[atlas, library, claude-user]` without one. `test_extension_config_absent_or_invalid_values_change_nothing` asserts `{}`/invalid config produces the identical list.
- **Workspace boundary**: `test_project_sources_do_not_escape_the_workspace`. A sibling workspace's `.dsh|.agents/skills` and a nested `<workspace>/nested/.dsh|.agents/skills` are never discovered; only `<workspace>/.dsh/skills` and `<workspace>/.agents/skills` are project roots. The test checks both source roots and actual `SkillManager` resolution.
- **Filesystem runtime vs virtual provider**: `test_runtime_root_is_a_filesystem_source_only`. Missing path and a plain file at the configured path add no `runtime` source (gate is `is_dir()`), a real directory adds a `Path`-rooted source, and only on-disk `SKILL.md` rows appear. `SkillSource` is directory-backed (`root: Path`, scan by `rglob`, activation reads `skill.path`); there is no provider identity/rank/`get()` handle. A future virtual runtime provider (DSH's `runtime provider`) is **not implemented** and would need a source type or manager provider that does not assume `root`/`path`. Prior gap G2 remains open by design.
- **Invocation policy** on new sources retained (`disable-model-invocation` / `user-invocable` test).

## 6. Exact commands, exit codes, counts

All from `D:/Atlas/.worktrees/zcode-exec06-skill-sources/core` (Python 3.11.16, pytest with default `-m unit`).

```
python -m pytest tests/test_skill_sources_dsh.py -q -p no:cacheprovider --no-header
```
→ **16 passed**, 5 warnings, **EXIT 0** (4.30s). Collection: 10 tests + 6 parameterized pairs. New test file passes `ruff check` clean.

Main regression gate (15 skill-related files: `test_skill_sources_dsh.py`, `test_skills.py`, `test_skills_market.py`, `test_skills_change_contract.py`, `test_skills_hot_reload.py`, `test_skill_scope_cache.py`, `test_introspect_skill_sources.py`, `test_c4_wiring.py`, `test_c4_plugin_e2e.py`, `test_c4_skills_commands.py`, `test_skill_lifecycle.py`, `test_skill_registry.py`, `test_skill_registry_api.py`, `test_skill_discovery.py`, `test_skill_discovery_catalog.py`):

```
python -m pytest <15 files> -q -p no:cacheprovider --no-header
```
→ **160 passed, 2 failed**, 5 warnings, **EXIT 1** (28.30s). Both failures are pre-existing/baseline (section 6.1).

Same command with the two baseline failures deselected:
→ **160 passed, 2 deselected**, **EXIT 0** (final rerun 15.66s).

Compile/parse check:
```
python -m py_compile atlas/skills/__init__.py atlas/server.py atlas/cli.py tests/test_skill_sources_dsh.py
python - <<'PY'  # ast.parse each edited file
```
→ `COMPILE_OK`, all three files parsed, **EXIT 0**.

Entry smoke:
```
python -c "import atlas.server; print('server import ok')"   # EXIT 0
python -m atlas.cli run --help                                # EXIT 0 (option listing)
```
(The server import auto-created gitignored `config/atlas.toml` from the example; deleted afterwards.)

### 6.1 Baseline/environment-only failures (reported separately, not caused by this diff)

1. `tests/test_skills_market.py::test_atlas_hub_state_forced_under_data_dir`
   - Isolated run: **1 failed**, `ModuleNotFoundError: No module named 'tools'` at `tests/test_skills_market.py:444`, **EXIT 1**.
   - Environment-only: `D:/hermes-agent` exists but its package root is not on `sys.path`; the test imports `tools.skills_hub`. Reproduces at baseline (prior receipt `exec06-skill-sources-regression.txt`: 1 failed / 47 passed, same traceback).
2. `tests/test_c4_plugin_e2e.py::test_installed_plugin_crosses_real_runtime_paths`
   - **1 failed**: plugin `PreToolUse` hook is blocked by the fail-closed review gate (`Hook「…」尚未通过信任审查…`) instead of returning the hook's `"禁止运行检查"`.
   - Verified pre-existing at baseline by temporarily restoring the three product files (`skills/__init__.py`, `server.py`, `cli.py`) to HEAD, backing them up, running the single test (**EXIT 1**, same message), then restoring the edits (diff stat re-verified). Unrelated to skill sources; main's `core/atlas/runtime/hooks.py` is itself in-flight.

Exploratory skill-adjacent sweep (not part of the gate; files outside the 15 above): **148 passed, 5 failed, 1 skipped**, plus `test_c4r_lifecycle.py` timing out at 90/120s after 4 passed / 3 failed. The failures are the same hook-trust gate (`test_c4r_lifecycle`) and external-import assertions about a rotated secret and history wording (`test_c4_external_import`); none touch the changed skill-source code paths. Not claimed as baseline-diffed beyond the same failure class.

## 7. Merge notes — `core/atlas/server.py` is in-flight in main

Main checkout `D:/Atlas/core/atlas/server.py` is `M` (+150/−19; hunks `+235,139`, `848`, `1148`). Its `default_skill_sources` block is byte-identical to this worktree's baseline but shifted: main lines 464–477 (`skill_mgr = SkillManager()` at 464, `hermes_skills = …` at 468, `for source in default_skill_sources(` at 469).

This pass's server hunk is `@@ -326,12 +326,18 @@` in the worktree, mapping to ~main 469–483. It sits **between** main's first modified hunk (ends ~373) and its second (starts ~848), so a 3-way merge / `git apply --3way` should apply with offset; no textual overlap. If main's block moves again, re-anchor by search string `hermes_skills = cfg.get("extensions.hermes_skills")`.

Two insertion points in main:

1. After the E2 comment line ending `… plugin_runtime exists.` (main line 467) insert a blank line and:
```python
        from atlas.skills import skill_source_config_overrides
```
2. Inside the `default_skill_sources(` call, after the `hermes_skills_dir=(...)` argument's closing `),` (main line ~475) insert:
```python
            **skill_source_config_overrides(cfg),
```

No other server hunks touched. `core/atlas/cli.py`, `config/atlas.example.toml`, `core/atlas/skills/__init__.py` are clean in main (verified `git status --short`), so those hunks apply directly. `core/tests/test_skill_sources_dsh.py` is a new file (worktree index shows `A`); it must be added explicitly when porting. Main has 170 dirty items; none of the other files in this diff are among them. Main was not written to.

## 8. Remaining risks / not verified

- **Source list is frozen at assembly time.** Creating `.dsh|.agents/skills`, the runtime root, or editing `[extensions]` after server boot does not add a source until restart: `_ensure_fresh` re-fingerprints registered roots but does not re-run `default_skill_sources`. DSH's dynamic discovery is not matched. A restart/reload path would be a separate change.
- **Relative config paths** resolve against the process CWD, exactly like `extensions.hermes_skills`; `~` is expanded. Use absolute paths in production. On Windows, TOML basic strings need forward slashes (`C:/…`) or doubled backslashes (the smoke caught `C:\…` as a TOML escape error — config authoring, not product).
- **`runtime` is filesystem-only.** No virtual provider identity/rank/`get()` handle, no code execution from the source; DSH `runtime provider` parity (G2) remains open.
- **Priority is an Atlas high-wins mapping, not DSH numeric ranks.** The seven DSH rungs are ordered correctly relative to each other, but Atlas/Claude/Hermes/library/plugin sources interleave by their existing priorities; this is intentional for backward compatibility (`project-dsh` 40 > `claude-project` 30 > `runtime` 25 > `custom` 22 > `claude-user` 20 > `user-dsh` 19 > `user-agents` 18). The 6 adjacent-pair tests cover the DSH chain; non-DSH combinations are not exhaustively matrixed.
- **`custom:` source names derive from the directory basename.** Two configured dirs with the same basename in one process get `:<index>` suffixes (`custom:skills:2`), stable only for that config order. The API/introspection exposes these names.
- **No UI/config surface** for the new keys beyond `config/atlas.example.toml` comments; no settings API validation. A typo is silently ignored by design (boot safety), so the user gets no diagnostic.
- **No full uvicorn lifespan boot and no real model/UI run.** Verification is unit tests + programmatic server-path/config-file smokes. Per `AGENTS.md`, this is not claimed as "真机真模型" validation.
- The server-path smoke read the real `~/.agents/skills` / `~/.claude/skills` (read-only; no writes) because production `default_skill_sources` uses `Path.home()` unless `user_home` is passed. This confirms real user roots are picked up when present.
- Hook-trust baseline failures leave the 15-file skill gate at 2 failed unless those pre-existing tests are fixed/deselected; they are unrelated to this diff.