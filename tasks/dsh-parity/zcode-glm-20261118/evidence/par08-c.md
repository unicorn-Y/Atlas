# PAR-08-C — workspace-scoped DSH/Claude skill sources (worker C rework)

- Date: 2026-11-19
- Worktree: `D:/Atlas/.worktrees/zcode-exec06-skill-sources`
- Branch: `zcode/exec06-skill-sources`
- HEAD: `060071ab2ecf86d41cab90e98160183ce126bc69` (unchanged; no commit/push/merge/stash)
- Main checkout, `PROGRESS.md`, `QUEUE.tsv`, other worktrees and real user data/credentials were not written to.

## 1. Root cause confirmed

`core/atlas/server.py` lifespan called `default_skill_sources(workspace=_default_workspace())` once and registered those sources into the single shared `SkillManager`. `run_drive` then resolved every run's Skills through `_server().skill_mgr`, so:

- the default workspace's `.dsh/.agents/.claude` project roots were visible inside every other project's runs;
- a conversation workspace other than the default had no project roots at run time (its own `.dsh/.agents` were never composed);
- same-name project Skills always resolved to the startup default workspace.

This pass keeps one shared manager for workspace-independent roots and composes a per-run view from `run.workspace` at the point the effective workspace is known.

## 2. Changes (worktree, cumulative vs HEAD; this pass is the subset after the PAR-07 state)

`git diff HEAD --stat`: 6 files, **+951 / −26**. New untracked e2e test: **+255**.

| File | Cumulative | This pass |
|---|---|---|
| `core/atlas/server.py` | +9/−1 | removed `workspace=_default_workspace()` from the lifespan source assembly; extended comment: shared manager holds only workspace-independent roots, project roots are composed per run. |
| `core/atlas/skills/__init__.py` | +145/−8 | `PROJECT_SKILL_SOURCE_NAMES`; `project_skill_sources(workspace)`; `default_skill_sources` reuses it; `with_sources(..., drop_sources=())` optional parameter (base manager untouched; cache key includes dropped names). Prior config-override/full ladder wiring retained. |
| `core/atlas/api/run_drive.py` | +124/−15 | (a) `_validate_active_skill_names` keeps shape/cap failure early; (b) content resolution moved after the effective workspace is known; (c) `_workspace_skill_manager(workspace)` builds `base.with_sources(project_skill_sources(workspace), drop_sources=PROJECT_SKILL_SOURCE_NAMES)`; (d) `_resolve_run_skill_instructions` emits `run.failed(category=skill)`; (e) `_resolve_active_skill_instructions(names, *, workspace=None)` uses that view for `get_skill` + `activate`; (f) automation dispatch passes its payload workspace. |
| `core/atlas/cli.py` | +10/−2 | unchanged this pass; PAR-07 config-override wiring retained. `atlas exec` still builds its own manager from `default_skill_sources(workspace=root)`. |
| `config/atlas.example.toml` | +8 | unchanged this pass; prior extension-key comments retained. |
| `core/tests/test_skill_sources_dsh.py` | 655 lines (was 384) | 16 → **22 tests** (+6): project-source helper scope, two-workspace view isolation, stale-project drop, source-policy gate, desktop run-entry two workspaces + no-workspace + base-only, CLI `exec` two workspaces. |
| `core/tests/test_par08_workspace_skill_e2e.py` | new, 255 lines | real uvicorn + `/ws/chat` `run.start` + scripted loopback LLM e2e (not `unit`; marked `integration` + `fake_provider`). |

No new configuration keys. No real user data or credentials touched.

## 3. Scope model

**Shared base manager (server lifespan)** — workspace-independent only:
`atlas`, `library`, `atlas-user` (`ATLAS_SKILLS_HOME`), `hermes` (opt-in), `claude-user`, `user-dsh`, `user-agents`, `runtime`/`custom:*`/`bundled` from `[extensions]`, and later `plugin:*` via `_refresh_extension_sources`. No `claude-project`/`project-dsh`/`project-agents`.

**Per-run view** (`_workspace_skill_manager(run.workspace)`):
- base ladder minus any inherited project-family source (`drop_sources`; base object is never mutated);
- `<workspace>/.dsh/skills` → `project-dsh` (40) when it exists;
- `<workspace>/.agents/skills` → `project-agents` (38) when it exists;
- `<workspace>/.claude/skills` → `claude-project` (30), always declared for a local workspace (absent dir indexes nothing), preserving prior behavior;
- empty / `ssh://` workspace → no project sources at all;
- same-name resolution remains Atlas high-wins: `project-dsh` > `project-agents` > `claude-project` (base rungs interleave as before).

**Existing policy/opt-out semantics retained (no new keys):**
- `ignore_project_config` still excludes the project's `active_skills` from the run's selected names (`_resolve_project_skill_scope` untouched);
- `skill-source-policy.json` `load.local=false` / per-name override still blocks activation in the scoped view (`activate()` gate), covered by a new test;
- lifecycle `revoked/blocked/quarantined/removed` gate unchanged;
- explicit client-selected Skills still use `activate()` (user invocation), so `disable-model-invocation` keeps its existing meaning for the model-facing `use_skill` path; `user-invocable` still only affects slash-trigger matching.

Views are memoized by the X18 cache (base ladder + extra sources + dropped names), bounded at 8, and keep the per-view `_ensure_fresh` disk fingerprint. Because `project_skill_sources()` is recomputed on every call, a `.dsh/skills` directory created later produces a new scope key and is picked up; the shared *base* source list itself is still fixed at boot.

## 4. Normal-entry verification matrix (exact names/sources/winners)

### 4.1 Desktop run entry — `atlas.server._handle_run_start` (production run assembly; `_execute_run` args captured)

Fixtures: workspace A = `<tmp>/ws-a` with `shared` in `.dsh/skills` (body `A DSH BODY`) and `.agents/skills` (`A AGENTS BODY`), plus `only-a` (A UNIQUE BODY); workspace B = `<tmp>/ws-b` with `.dsh/shared` (B DSH BODY) and `.agents/only-b` (B UNIQUE BODY); base manager carries `base-only`.

| Case | Selected | Result |
|---|---|---|
| A run | `shared, only-a` | `shared` winner source `project-dsh`, content `A DSH BODY` (`.agents` copy not used); `only-a` content `A UNIQUE BODY`; `kwargs["workspace"] == str(ws-a)` |
| B run | `shared, only-b` | `shared` winner source `project-dsh`, content `B DSH BODY`; `only-b` content `B UNIQUE BODY`; A's skills absent |
| B run requests A-unique | `only-a` | no run registered; `run.failed category=skill detail="Skill not found: only-a"` |
| no workspace | `only-a` | `run.failed category=skill detail="Skill not found: only-a"` (no project roots) |
| no workspace | `base-only` | resolves content `BASE BODY`; `run.workspace is None`; project skills still invisible in the shared manager |

### 4.2 CLI `atlas exec` (two workspaces, same name)

```
atlas exec go --workspace <ws-a> --skills shared --json
atlas exec go --workspace <ws-b> --skills shared --json
```
Both exit 0; `skills.preloaded` reports `{"name": "shared", "source": "project-dsh", "scope": "explicit"}`; the orchestrator receives body `A cli body` / `B cli body` respectively. Proves CLI keeps its own file-based wiring scoped to the command workspace.

### 4.3 Real backend e2e — uvicorn + WebSocket + FakeLLM

`tests/test_par08_workspace_skill_e2e.py` boots a real isolated `atlas.server:app` on a random port with `user-settings.json` `default_workspace = ws-a` (the exact leakage scenario) and drives `run.start` over `/ws/chat` with a scripted OpenAI-compatible loopback model:

- A run: model request payload contains `A DSH BODY` and `A UNIQUE BODY`; does **not** contain `A AGENTS BODY`, `B DSH BODY` or `B UNIQUE BODY`.
- B run: payload contains `B DSH BODY` and `B UNIQUE BODY`; does **not** contain A's bodies.
- B run + `only-a`: final event `run.failed`, `category=skill`, `detail="Skill not found: only-a"`.
- Backend log evidence (`par08-c-e2e-backend.txt`): the shared boot scan is **12 skills / 4 sources** even though the configured default workspace ws-a contributes 4 project skills (no project roots in the base manager); each per-run view scans **14 skills / 7 sources** (base 4 + `claude-project` + `project-dsh` + `project-agents`); a duplicate-name event replaces `.agents/shared` with `.dsh/shared`; activations are `shared` + `only-a` for A and `shared` + `only-b` for B.

The e2e uses a self-contained backend harness because the shared `test_c6_lsp_e2e.IsolatedBackend` config (`provider="openai"` without an explicit model `base_url`) routes the request to `api.openai.com` and returns 401 on this checkout; the pre-existing LSP e2e fails the same way at baseline (`par08-c-lsp-baseline.txt`). The custom config uses `provider="custom"` + explicit `base_url`, so the real kernel reaches the fake model.

### 4.4 Direct scope smoke (run_drive view functions, no pytest)

`par08-c-scope-smoke.txt`:

```
base manager visible: ['base-only']
A shared -> ('project-dsh', 'A dsh', '.../ws-a/.dsh/skills/shared')
A unique -> ('project-dsh', 'A only', '.../ws-a/.dsh/skills/only-a')
A resolved: [('shared', 'A DSH BODY'), ('only-a', 'A ONLY BODY')]
B shared -> ('project-dsh', 'B dsh', '.../ws-b/.dsh/skills/shared')
B unique -> ('project-agents', 'B only', '.../ws-b/.agents/skills/only-b')
B resolved: [('shared', 'B DSH BODY'), ('only-b', 'B ONLY BODY')]
cross-workspace: Skill not found: only-a
no-workspace: Skill not found: only-a
no-workspace base: [('base-only', 'BASE BODY')]
base manager after runs: ['base-only']
```

### 4.5 Virtual runtime provider status

Not implemented in this package, unchanged from PAR-07: every source is a real directory (`SkillSource.root`, scan by `rglob`, activation reads `skill.path`). There is no provider identity/rank/`get()` handle and no in-memory synthesis. The `runtime` source remains a filesystem root only. DSH "runtime provider" parity (prior G2) stays open.

## 5. Commands and exit codes

All from `D:/Atlas/.worktrees/zcode-exec06-skill-sources/core`; Python 3.11.16; logs in `D:/Atlas/tasks/dsh-parity/zcode-glm-20261118/evidence/`.

| Command | Result | Exit |
|---|---|---|
| `python -m pytest tests/test_skill_sources_dsh.py -q -p no:cacheprovider --no-header --basetemp=.tmp/par08-unit-final2` | 22 passed (3.72s) | 0 |
| `python -m pytest tests/test_par08_workspace_skill_e2e.py -o addopts= -q -p no:cacheprovider --no-header` | 1 passed (11.43s) | 0 |
| 15-file skill gate (same list as PAR-07: `test_skill_sources_dsh.py`, `test_skills.py`, `test_skills_market.py`, `test_skills_change_contract.py`, `test_skills_hot_reload.py`, `test_skill_scope_cache.py`, `test_introspect_skill_sources.py`, `test_c4_wiring.py`, `test_c4_plugin_e2e.py`, `test_c4_skills_commands.py`, `test_skill_lifecycle.py`, `test_skill_registry.py`, `test_skill_registry_api.py`, `test_skill_discovery.py`, `test_skill_discovery_catalog.py`) | **166 passed, 2 failed** (25.82s) | 1 |
| same gate with the two known baseline failures `--deselect`ed | **166 passed, 2 deselected** (24.07s) | 0 |
| `test_c6_server_routes.py` (excluding 2 unrelated baseline failures) + `test_backend_parity_wave2.py::test_run_start_reuses_profile_and_assigns_worktree` + `test_server.py::TestAgentCapabilities::test_active_skill_run_context_uses_registry_activation_content` + `test_run_resume.py` + `test_w5_s29_session_mentions.py` | 37 passed, 3 deselected (10.48s) | 0 |
| `python -m py_compile` on all changed Python files | `COMPILE_OK` | 0 |
| `python -m ruff check tests/test_skill_sources_dsh.py tests/test_par08_workspace_skill_e2e.py` | All checks passed | 0 |
| `python -m ruff check atlas/skills/__init__.py atlas/api/run_drive.py atlas/server.py` | still reports pre-existing E501/BLE001/UP037 in untouched baseline lines (same class as before this pass); no new rule class introduced in new test files | n/a |
| `git apply --check` of the cumulative product patch against `D:/Atlas` (server, skills, run_drive, cli, example.toml) | clean | 0 |
| `git apply --check` of the new/updated test patches against `D:/Atlas` | clean | 0 |

Evidence logs: `par08-c-unit.txt`, `par08-c-unit-v.txt`, `par08-c-regression.txt`, `par08-c-regression-deselect.txt`, `par08-c-runstart.txt`, `par08-c-e2e.txt`, `par08-c-e2e-backend.txt`, `par08-c-scope-smoke.txt`, `par08-c-baseline-fail.txt`, `par08-c-compile.txt`, `par08-c-ruff-tests.txt`, `par08-c-ruff-product.txt`, `par08-c-lsp-baseline.txt`.

## 6. Baseline / environment failures (not caused by this diff, not claimed green)

1. `tests/test_skills_market.py::test_atlas_hub_state_forced_under_data_dir` — `ModuleNotFoundError: No module named 'tools'` at line 444. Environment-only: the Hermes checkout is not on `sys.path`. Prior receipt `par07-c.md` §6.1 proved the same failure at baseline by restoring the three product files; this pass only touched skill-source/run paths.
2. `tests/test_c4_plugin_e2e.py::test_installed_plugin_crosses_real_runtime_paths` — plugin `PreToolUse` hook blocked by the fail-closed review gate (`Hook「…」尚未通过信任审查…`) instead of returning the hook's text. Same pre-existing hook-trust failure documented in `par07-c.md` §6.1; `core/atlas/runtime/hooks.py` is untouched here.
3. Exploratory (outside the 15-file gate): `test_c6_server_routes.py::test_review_intercept_rewrites_run` fails on a changed review tool allow-list (`ReportFindings` vs `local_file`), and `test_new_queue_events_reach_wire_unchanged` fails because a test hook lacks the `bridge_event_alias` keyword. Neither path is touched by this diff; they were excluded from the targeted run rather than "fixed".
4. The shared LSP e2e (`test_c6_lsp_e2e.py`) fails at baseline on this checkout with a 401 because its `provider="openai"` model entry resolves to `api.openai.com` (see `par08-c-lsp-baseline.txt`); the PAR-08 e2e therefore uses its own config.

## 7. Merge anchors — main `server.py` / `run_drive.py` are in flight

Main checkout status: 170 dirty items; `core/atlas/server.py` and `core/atlas/api/run_drive.py` are modified. Main was read-only for `git apply --check`; no writes.

- **server.py**: the `skill_mgr = SkillManager()` block is at main 464–477 and is byte-identical to this worktree's HEAD baseline (main's in-flight hunks are at `+235,139`, `848`, `1148` and do not touch it). Anchors:
  - `skill_mgr = SkillManager()` (main 464);
  - `for source in default_skill_sources(` (main 469);
  - remove `workspace=_default_workspace(),` (main 470);
  - keep/insert `from atlas.skills import skill_source_config_overrides` above `hermes_skills = cfg.get(...)` and `**skill_source_config_overrides(cfg),` inside the call (PAR-07 merge note; final block in this worktree server.py 325–344).
  - The cumulative product patch applies cleanly to main (`git apply --check` exit 0), so a 3-way apply should land it.
- **run_drive.py** anchors (main line numbers; main's own hunks start at 2030 and 3000+, no textual overlap):
  - import at main 47 `from atlas.skills import SkillManager, plugin_skill_sources` → the new import block;
  - automation dispatch call at main 770 → pass `workspace=str(payload.get("workspace") or "") or None`;
  - skill validation/resolution block at main 1736–1748 → validation only + `active_skill_instructions = []` + `skills_resolved = False`;
  - SSH branch: after main 2223–2226 (`run.workspace = str(workspace)` / `await memory.update_conversation(conv_id, workspace=run.workspace)`) insert the `_resolve_run_skill_instructions` call + prepend + `skills_resolved = True`;
  - local branch: after main 2290 (`log.warning("run.workspace_persist_failed"...)`) and before `if context_files and not run.workspace:` insert the same block;
  - no-workspace paths: immediately before main 2440 `run.user_input = content` (after the `rules.loaded`/trust branch) insert the `if not skills_resolved:` block;
  - replace main 2545+ `_resolve_active_skill_instructions` with `_workspace_skill_manager`, `_validate_active_skill_names`, `_resolve_run_skill_instructions`, and the workspace-aware `_resolve_active_skill_instructions` (worktree 2575–2686). The function is re-exported through `atlas.server`; the additive `workspace=` keyword keeps existing callers/tests working.
  - Main's new sandbox/remote-workspace block at main 2154–2170 shifts lines but not the anchor strings.
- **Tests**: `core/tests/test_skill_sources_dsh.py` is a new file in main (apply as add); `core/tests/test_par08_workspace_skill_e2e.py` is new (integration/fake_provider; run explicitly with `-o addopts=`). Main has no same-name files.

No `core/atlas/api/run_drive.py`/`server.py` main content was copied or edited; the patch checks were read-only.

## 8. Not verified / remaining boundaries

- **Skill list API / UI**: `skills_router` list/search/get endpoints still use the shared workspace-independent manager; project skills are therefore not in the global catalog list or picker. Only run-time resolution is scoped. A workspace-aware list endpoint (and frontend use of it) is a separate change; the acceptance gap only required run resolution.
- **Agent `use_skill` tool**: the orchestrator holds the shared manager, so a project skill not selected via `active_skills` is not reachable through the model's `use_skill` tool. Per-run `skill_manager` injection into the orchestrator was not implemented.
- **Worktree runs**: skill existence is resolved after the effective workspace (including a newly created worktree) is known. A missing/invalid skill name therefore fails after worktree/metadata setup; shape/cap errors still fail before any workspace branch.
- **No-workspace turns**: automation passes a payload workspace when present; group-member turns and other workspace-less call sites resolve base sources only (no project roots), as specified.
- **No full Electron UI / packaged-client run**; the real-backend e2e covers the desktop WebSocket run path with a fake model. No real model was called, so this is not `真机真模型` evidence.
- **Virtual runtime provider** remains unimplemented (filesystem-only), as in §4.5.
- The server base source list is still assembled once at boot (creating a new configured runtime/custom/bundled root after boot needs a restart); per-run project roots are recomputed per call as described in §3.
- `test_c6_server_routes` and the LSP e2e have unrelated baseline failures as reported in §6; they are not claimed as part of a green gate.