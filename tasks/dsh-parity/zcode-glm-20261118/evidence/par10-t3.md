# PAR-10-T3 — workspace-scoped Skill runtime for `use_skill` and the Skills API

- Date: 2026-11-19
- Worktree: `D:/Atlas/.worktrees/zcode-par10-skill-runtime`
- Branch: `zcode/par10-skill-runtime`
- HEAD: `060071ab2ecf86d41cab90e98160183ce126bc69` (unchanged; no commit/push/merge/stash)
- Source tree: `D:/Atlas/.worktrees/zcode-exec06-skill-sources`, branch `zcode/exec06-skill-sources`, HEAD `060071ab…` (same base; writer stopped)
- Main checkout, `PROGRESS.md`, `QUEUE.tsv`, other worktrees and real user Skills/credentials were not written to.

## 1. Baseline and source hashes

Source tree was clean of unexpected changes and its PAR-08 state was the PAR-08-C receipt plus an untracked e2e file:

```
git status --short (source): M config/atlas.example.toml, M core/atlas/api/run_drive.py,
  M core/atlas/cli.py, M core/atlas/server.py, M core/atlas/skills/__init__.py,
  A core/tests/test_skill_sources_dsh.py, ?? core/tests/test_par08_workspace_skill_e2e.py
git diff HEAD --stat (source): 6 files, +951 / -26  (+255 new e2e test)
```

sha256 of the files moved in (source == candidate except `server.py`/`run_drive.py`, which carry the PAR-10 additions below):

| File | sha256 (PAR-08 source) | sha256 (PAR-10 candidate) |
|---|---|---|
| `core/atlas/skills/__init__.py` | `d20e16d5644bf48f1c192a18ffdbb47dcbe6e82155438d253d1d819ac2c4e020` | same |
| `core/atlas/server.py` | `735a9321119ac17dcab429d4b2036c88dd889b4c9b93e0dcd48da8443dc2b30e` | `5a861a11f43ef37099e1717f44efcc01f116fab86ba2552ea842505f58ff8516` |
| `core/atlas/api/run_drive.py` | `16498f8edd22c5f87733db75ac32c50c9feefe97bba5be5bb78af26760b68340` | `0fd5282d40cccb6bf6ed2c58b9fcc6a8774340acfb32178567ddc051d7f2f678` |
| `core/atlas/cli.py` | `404f9f5e613a329caa1e46ae8b8c9c1cc51c7ce79f14f1e133e2135c2d4dfb8c` | same |
| `config/atlas.example.toml` | `824a4217c5f147e07b3eedd5d3e37358356f227ecc83b5de744ee5f7fce7ff2c` | same |
| `core/tests/test_skill_sources_dsh.py` | `5a829ee4eac051023782fc9f030bdb4cf5bda2e03b7c4080e7324523b988fe8b` | same |
| `core/tests/test_par08_workspace_skill_e2e.py` | `db48de37cdaa5698344d9c20fa4c3014c8ca004a3a8fccd1c5b2dceb30f6df8b` | same |

Candidate cumulative diff: **12 tracked files, +432 / −65**, plus the 2 copied test files and 2 new PAR-10 tests:

```
backend-adapter/src/client.ts                |   6 +-
backend-adapter/tests/client.test.ts         |  16 +
config/atlas.example.toml                    |   8 +
core/atlas/agent/__init__.py                 |  30 +-
core/atlas/agent/run_phases.py               |  22 +-
core/atlas/api/run_drive.py                  | 148 ++++++++++++++--
core/atlas/api/skills_router.py              |  68 +++++----
core/atlas/cli.py                            |  12 +
core/atlas/server.py                         |  18 +-
core/atlas/skills/__init__.py                | 153 ++++++++++++++-
frontend/src/renderer/App.tsx                |  10 +
frontend/src/renderer/store/useAtlasStore.ts |   6 +-
```

Test files in the candidate: `test_skill_sources_dsh.py` 655, `test_par08_workspace_skill_e2e.py` 255, `test_par10_skill_runtime.py` 201 (new, 4 unit tests), `test_par10_skill_runtime_e2e.py` 181 (new, 2 integration tests).

## 2. Injection model — one run, one Skill view, no shared mutation

`use_skill`, `skill_search`, the model-facing skill index, preset-skill activation and plugin-realm checks all read `agent._skills`. That attribute is now a property:

- fallback: `self._skills_base` (the shared, workspace-independent `SkillManager`);
- override: a `ContextVar[Any | None]` (`atlas.agent._RUN_SKILL_MANAGER`), read by the property.

`AgentOrchestrator.run(..., skill_manager=...)` → `RunRequest.skill_manager` → `atlas.agent.run_phases.execute_run` sets the ContextVar around the whole run (lease + phases) and resets it in `finally`. Consequences:

- ContextVars are task-local. Every desktop run is its own `asyncio.create_task` (`run_drive._handle_run_start`), so concurrent runs cannot see each other's view; the unit test interleaves two `use_skill` calls in two tasks and checks each body.
- No global temporary replacement of `_skills`; the shared manager's `_sources`/`_index` are never mutated. Existing direct assignment (`orchestrator._skills = manager`, used by tests/adapters) still works through the property setter and changes only the fallback.
- Subtask tasks created inside a run inherit the same ContextVar by context copy (orchestrator-role subtasks); leaf workers keep `use_skill` denied and skip the skill index as before.
- Scope composition itself is unchanged from PAR-08: `_workspace_skill_manager(workspace)` = base ladder minus any inherited `project-dsh`/`project-agents`/`claude-project` plus this workspace's `.dsh` (40) / `.agents` (38) / `.claude` (30), memoized; empty or `ssh://` workspace adds no project root. The function gained an optional `base=` keyword so callers that resolved a manager via dependency injection scope that instance (router), while run paths still use the server singleton.
- `disable-model-invocation`, `user-invocable`, lifecycle (`revoked/blocked/quarantined/removed`), `skill-source-policy.json` load gate and dependency preflight are unchanged: `use_skill` still calls `activate_for_model`, explicit run Skills still call `activate`.

Run drive now passes `skill_manager=_workspace_skill_manager(workspace)` in both run entry points (`_execute_run` production assembly and `_collect_orchestrator_text` for automation/heartbeat/group turns), so the model tool surface and the pre-resolved `active_skills` content come from the same view.

## 3. Skills API / Desktop list

`core/atlas/api/skills_router.py` now accepts an optional `workspace` query parameter on the list/search/detail/activation entries and resolves the manager through `_workspace_skill_manager(services, workspace)`:

- `GET /api/skills?workspace=…`
- `GET /api/skills/{name}?workspace=…`
- `GET /api/skills/{name}/dependencies?workspace=…`
- `GET /api/skills/{name}/activate?workspace=…`
- `GET /api/skills/search/{query}?workspace=…`

Per-app `AppServices.skill_mgr` wins over the server singleton (same rule as before). Omitting `workspace` keeps the workspace-independent catalog, so existing callers/tests are unchanged.

Desktop wiring: `BackendAdapter.getSkills(workspace?)` appends `?workspace=`; the renderer store's `refreshSkills(workspace?)` forwards it; `App.tsx` re-queries only when the active conversation workspace (or new-conversation draft workspace) changes. That list drives the `/skill` slash entries, the `$` skill picker and `$name` resolution, so a project conversation lists its own project Skills and a workspace-less conversation lists only the base catalog. No event names or event payload shape changed, so the three event sources (`event_names.py`, `runtimeEvents.ts`, `types/runtime.ts`) needed no edit.

## 4. Two-workspace verification matrix

Fixtures (real directories):
- A = `<fixture>/ws-a`: `.dsh/skills/shared` body `A SHARED BODY`, `.agents/skills/shared` body `A AGENTS BODY`, `.dsh/skills/only-a` body `A ONLY BODY`.
- B = `<fixture>/ws-b`: `.dsh/skills/shared` body `B SHARED BODY`, `.agents/skills/only-b` body `B ONLY BODY`.
- Base/global: the checkout's 12 `atlas` Skills (`arxiv`, `blocked-page-recovery`, `coding-discipline`, `comfyui`, `competitor-news-monitor`, `github-code-review`, `github-issues`, `github-pr-workflow`, `pdf`, `systematic-debugging`, `telegram-integration`, `verify`), plus a `base-only` fixture in the unit test.
- The isolated backend's configured `default_workspace` is `ws-a` — the leakage scenario.

| Entry | Workspace | Observation | Evidence |
|---|---|---|---|
| `use_skill("shared")` via `/ws/chat` run.start, fake LLM | A | tool result `A SHARED BODY`; not `A AGENTS BODY`, not B bodies; model's skill-index message lists `only-a`, not `only-b` | `par10-t3-e2e.txt` (test 1) |
| `use_skill("shared")` | B | tool result `B SHARED BODY`; index lists `only-b`, not `only-a` | `par10-t3-e2e.txt` |
| `use_skill("only-b")` | B | loaded `B ONLY BODY` (no `active_skills` selection; project Skill reachable through the model tool) | `par10-t3-scope-smoke.txt` |
| `use_skill("only-a")` | B | structured error `Unknown skill: only-a`; run still completes (recoverable tool error) | e2e + smoke |
| `use_skill("base-only")`, no scoped view | none | `BASE BODY` through the shared manager (no-workspace regression) | `test_par10_skill_runtime.py` |
| Skill index prompt | A / B | each model request contains only its workspace's project names; no cross-workspace bodies | e2e assertions |
| `GET /api/skills?workspace=A` | A | `shared` → source `project-dsh`, `only-a` → `project-dsh`; no `only-b`; 12 base + 2 project = 14 rows | `par10-t3-http-probe.txt` |
| `GET /api/skills?workspace=B` | B | `shared` → `project-dsh`, `only-b` → `project-agents`; no `only-a` | same |
| `GET /api/skills/shared/activate?workspace=A` | A | `A SHARED BODY` (not the `.agents` copy) | same |
| `GET /api/skills/shared/activate?workspace=B` | B | `B SHARED BODY` | same |
| `GET /api/skills/only-a?workspace=B` | B | 404 `Skill not found: only-a` | same |
| `GET /api/skills` (no workspace) | none | exactly the 12 base `atlas` Skills; no `shared`, `only-a`, `only-b` | same |
| `GET /api/skills/search/only-a?workspace=A` | A | exactly `["only-a"]` | e2e |
| Backend logs | A then B | boot scan **12 skills / 4 sources** (configured default ws-a contributes nothing); per-run views **14 skills / 7 sources**; duplicate event replaces `.agents/shared` with `.dsh/shared`; activations `shared` then `only-b` | `par10-t3-e2e-backend.txt` |
| Shared manager after all runs | — | still no project Skills; orchestrator fallback still the base manager | `par10-t3-scope-smoke.txt` |

Winner/precedence observed: same-name `shared` resolves to `project-dsh` (priority 40) over `project-agents` (38) in both workspaces; `only-b` is lower-priority `project-agents`; `only-a` is `project-dsh`. No workspace sees the other workspace's project roots.

## 5. Commands, exit codes and evidence logs

All commands from `D:/Atlas/.worktrees/zcode-par10-skill-runtime`; Python 3.11.16. Test runs use `--basetemp=.tmp/<name>` (created in the worktree; `_tmp`/`.tmp` are gitignored) and `-p no:cacheprovider`. Logs live in `D:/Atlas/tasks/dsh-parity/zcode-glm-20261118/evidence/`.

| Command | Result | Exit | Log |
|---|---|---|---|
| `python -m py_compile` on 7 changed product files + both new PAR-10 tests | COMPILE_OK | 0 | `par10-t3-compile.txt` |
| `test_skill_sources_dsh.py test_par10_skill_runtime.py test_agent_skill_model_invocation.py test_agent.py::TestUseSkill` | **31 passed** | 0 | `par10-t3-unit.txt` |
| 15-file PAR-08 skill gate + `test_par10_skill_runtime.py`, with the 2 known baseline failures deselected (`test_atlas_hub_state_forced_under_data_dir`, `test_installed_plugin_crosses_real_runtime_paths`) | **170 passed, 2 deselected** | 0 | `par10-t3-gate.txt` |
| Same gate without deselects | 168 passed, **2 baseline failures only** | 1 | (not claimed green; same two as PAR-08 §6) |
| `test_par08_workspace_skill_e2e.py test_par10_skill_runtime_e2e.py -o addopts=` (real uvicorn + `/ws/chat` + FakeLLM, 2 tests / 3 runs) | **3 passed** | 0 | `par10-t3-e2e.txt`, `par10-t3-e2e-backend.txt` |
| `test_run_resume.py` + `test_backend_parity_wave2.py::test_run_start_reuses_profile_and_assigns_worktree` + `test_w5_s29_session_mentions.py` + `test_server.py::TestAgentCapabilities::test_active_skill_run_context_uses_registry_activation_content` (`-o addopts=`) | **24 passed** | 0 | `par10-t3-run.txt` |
| `test_c6_server_routes.py` (all, unit gate) | 14 passed, 2 known baseline failures (`test_review_intercept_rewrites_run`, `test_new_queue_events_reach_wire_unchanged`); pytest process lingered after the summary and was stopped by a 300s `timeout` wrapper (shell exit 124) | — | inline |
| `test_agent.py` full | 6 passed, 7 failures; the same 7 fail in the source tree (`TestExecuteTools` ctx fixture missing `conversation_id`, `TestConcurrentRunIsolation`); `TestUseSkill` passes | baseline | inline |
| `npx vitest run --root .` (frontend) | **81 files / 368 tests passed** | 0 | `par10-t3-frontend-full.txt`, `par10-t3-frontend.txt` |
| `npx vitest run --root .. backend-adapter/tests/client.test.ts` | **24 passed** (incl. new workspace-query case) | 0 | `par10-t3-adapter.txt` |
| `npx tsc -p .tmp/tsconfig.par10.json --noEmit` (renderer; maps `@atlas/backend-adapter` to this worktree's source because the ancestor checkout's `node_modules` points at main's adapter) | clean | 0 | `par10-t3-tsc.txt` |
| `.tmp/par10_scope_smoke.py` (manager/use_skill matrix) | expected rows, base unmutated | 0 | `par10-t3-scope-smoke.txt` |
| `.tmp/par10_http_probe.py` (real uvicorn, HTTP list/activate/detail) | expected rows / 404 | 0 | `par10-t3-http-probe.txt` |
| `python -m ruff check` on both new Python tests | All checks passed | 0 | inline |

Baseline/environment failures, not introduced or claimed green:

1. `tests/test_skills_market.py::test_atlas_hub_state_forced_under_data_dir` — `ModuleNotFoundError: No module named 'tools'` (Hermes checkout not on `sys.path`); same at PAR-08 baseline.
2. `tests/test_c4_plugin_e2e.py::test_installed_plugin_crosses_real_runtime_paths` — plugin `PreToolUse` hook blocked by the fail-closed hook-trust gate; `runtime/hooks.py` untouched.
3. `tests/test_c6_server_routes.py::{test_review_intercept_rewrites_run,test_new_queue_events_reach_wire_unchanged}` — pre-existing review allow-list / hook keyword mismatch reported by PAR-08 §6.3.
4. `tests/test_agent.py` full-file `TestExecuteTools`/`TestConcurrentRunIsolation` failures reproduce in the source tree with the same code (verified there), so they are baseline, not PAR-10.
5. One flake was observed only when two pytest processes ran concurrently: `test_skills_market.py::test_update_all_and_provenance_round_trip` failed once, passes alone and in the serial gate rerun. No product file in that path was touched; serial evidence is the one recorded.

## 6. Not covered / remaining boundaries

- No real model was called: the desktop path is the real uvicorn `/ws/chat` run.start path with a scripted loopback OpenAI-compatible provider. No packaged Electron/UI run; the Desktop list is covered by the adapter+store+App wiring and the same HTTP endpoint the UI calls, not by a rendered window.
- `GET /api/skills` returns the workspace view but the settings/market pages (`/api/skills/market/*`, `ExtensionCatalogPanel`, `SkillsMarketPage`) still list globally; they are installation management surfaces, not the run skill picker. `agent_skills_router` collections are per-agent, not per-workspace, and were left unchanged.
- Virtual runtime provider parity remains unimplemented (filesystem-only sources), unchanged from PAR-08 §4.5.
- The server base ladder is assembled once at boot; only per-workspace project roots are recomputed per call (same as PAR-08).
- Legacy managers without `with_sources` (test doubles) return the base manager unchanged, so workspace project roots require the real `SkillManager`.
- `_collect_orchestrator_text` callers without a workspace (heartbeat) get the base-only view, by design; group/automation turns with a payload workspace get that workspace's view.
- No commit/push/merge; candidate tree is the only product change. Evidence dir and ignored `.tmp`/`_tmp` fixtures are the only other writes.

PAR10_RECEIPT T3 READY
