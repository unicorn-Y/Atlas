# hermes-agent upstream survey (NousResearch/hermes-agent, latest main)

Survey date: 2026-10-03. Ground truth: local fetch of `upstream/main` in D:/hermes-agent
(remote `upstream` = https://github.com/NousResearch/hermes-agent.git), cross-checked
against the GitHub README and docs site.

## Upstream freeze (HEAD, date)

- **upstream/main HEAD:** `a6e75acb0dc68c99d33fe8ba421a186b6b781b7c`
  ("Merge pull request #131697 from unsupportedpastels/fix/128974-uninstall-dry-run")
- **HEAD commit date:** 2026-10-02 17:44:26 -0400
- **Delta vs Atlas merge-base `aea969677c`:** 518 commits, 939 files changed, +23,241 / −28,820
- Docs site (linked from README): https://hermes-agent.nousresearch.com/docs/ (docusaurus source lives in `website/docs/` in-repo). Desktop app landing: hermes-agent.nousresearch.com. No GitHub Releases page usage — distribution is install scripts (`setup-hermes.sh` / `setup-hermes.ps1`), signed APT repo for Android/Termux (`stable` + `canary` channels), and desktop auto-updaters.
- README pitch: "self-improving AI agent… The agent that grows with you" — learning loop (skill creation from experience, FTS5 session search, Honcho user modeling), delegation/parallel subagents, one gateway process for Telegram/Discord/Slack/WhatsApp/Signal/CLI, cron automations, Hermes Desktop, any-model providers via `hermes model`. Includes an OpenClaw migration path (`hermes claw migrate`).

## Capability inventory on latest main

All seven Atlas-relevant capability areas exist on latest main. Exact paths verified via `git ls-tree upstream/main`:

### 1. Browser stack — present, mature, essentially frozen since 2026-09-28
- Core: `tools/browser_tool.py` (+ `browser_tool_cdp.py`, `browser_tool_cloud.py`, `browser_tool_real_profile.py`, `browser_tool_session.py`, `browser_tool_snapshot.py`, `browser_tool_vision.py`, `browser_tool_origin.py`, `browser_tool_eval_policy.py`, `browser_tool_install.py`, `browser_tool_lifecycle.py`, `browser_tool_lightpanda_fallback.py`)
- Supervisor: `tools/browser_supervisor.py` (+ `browser_supervisor_dialogs.py`, `browser_supervisor_frames.py`), `tools/browser_dialog_tool.py`, `tools/browser_cdp_tool.py`
- Engines: `tools/browser_camofox.py` + `browser_camofox_state.py` (local anti-detect Firefox), `tools/browser_lightpanda.py` (Zig headless engine, Browser-Use mode + built-in tools with Chrome fallback), cloud = Browser Use / Browserbase / Firecrawl / "nous" subscription (selected by `browser.cloud_provider` via `hermes tools`)
- Extension router: `tools/browser_extension_router.py`; CLI: `tools/browser_use_cli.py` (Browser Use CLI 3.0 as default driver); vault fill: `tools/browser_vault_tool.py`
- Docs: `website/docs/user-guide/features/browser.md`; desktop RPC: `tui_gateway/methods_browser.py`, `methods_browser_control.py`; gateway: `gateway/browser_control_broker.py`, `browser_control_artifacts.py`
- Per-session isolation: `browser_exec session=<name>` — one daemon + one browser per name (parallel subagents don't clobber)
- Only 3 browser files changed in the 518-commit window (`browser_use_cli.py` +36, `browser_tool_lifecycle.py`, both via `/browser connect|disconnect` retarget + `/browser use [off]` outside CLI fixes)

### 2. Computer use — present
- `tools/computer_use/`: `tool.py`, `backend.py`, `cua_backend.py` (+ `_capture`, `_daemon`, `_driver`, `_input`, `_parse`, `_session`), `doctor.py`, `permissions.py`, `schema.py`, `vision_routing.py`; entry `tools/computer_use_tool.py`. Docs: `features/computer-use.md`. **Zero changes** since 2026-09-28 (file untouched in the whole 518-commit window).

### 3. Skills hub + skill learning/curator — present, actively hardened
- Hub: `tools/skills_hub.py` (+ `_clawhub`, `_github`, `_install`, `_models`, `_official`, `_search`, `_skillssh`, `_sources`), i.e. sources = official/optional-skills, ClawHub, SkillSSH, GitHub, agentskills.io standard. Security pipeline: `tools/skills_guard.py`, `skills_ast_audit.py`, `skillevaluator_scan.py` (NVIDIA SkillEvaluator Tier-1 + SkillSpector on hub installs), `skill_linter.py`, `skill_provenance.py`, `skill_ledger.py`, `skill_usage.py`, `skills_sync*.py` (personal + org Skill Sync)
- Curator: `agent/curator.py` + `agent/curator_backup.py` (background fork of AIAgent; active→stale→archived lifecycle, LLM consolidation review, default interval 7d / idle 2h, `hermes curator run --dry-run`), plus `agent/background_review.py`. Docs: `features/curator.md`, `features/skills.md`. Skills state under `~/.hermes/skills/.hub/lock.json`
- In-window change: only `tools/skills_guard.py` (plugin-guard false-positive fixes)

### 4. Delegation / nested orchestration / subagent worktree — present
- `tools/delegate_tool.py` (+ `_child_run`, `_config`, `_dispatch`, `_progress`, `_registry`, `_results`, `_tasks`, `_toolsets`), `tools/async_delegation.py` (+ `async_delegation_recovery_hints.py`), `tools/subagent_worktree.py`, `tools/delegation_live_log.py`, `delegation_output_schema.py`. Docs: `features/delegation.md` (up to 10 concurrent subagents default, `output_schema`, fresh-context subagents that inherit project context files). `tools/delegate_tool.py` itself **unchanged** in-window; `subagent_worktree.py` and `async_delegation_recovery_hints.py` only got the repo-wide "neutralize repository-named git filters / noninteractive git env" fix series.

### 5. Gateway / bot mode / platforms / cron — present, large surface
- `gateway/` (~90 files): platform registry (`gateway/platform_registry.py`), platforms dir = api_server (OpenAI-compatible routes, runs, room grants), bluebubbles, signal, whatsapp_cloud, webhook, weixin, qqbot, yuanbao, tcp_site, msgraph_webhook; hosted rooms, kanban watchers, relay/ (`gateway/relay`), delivery ledger, pairing, profile routing
- Bot mode: `tools/bot_mode_dm.py`, `bot_mode_probe.py`, `bot_relay.py`, `bot_live_delivery.py`, `bot_failure_reasons.py`, `tools/bot_desktop/`
- Cron: top-level `cron/` package (scheduler + detached worker + tick/ownership/preflight/quota_hold/incidents/monitor, `blueprint_catalog.py`, `bot_chat_delivery.py`), plus `tools/cronjob_tools.py` / `cronjob_prompt_scan.py` / `cronjob_job_args.py`. Docs: `features/cron.md`, `bot-mode.md`, `api-server.md`

### 6. Desktop app + tui_gateway — present, the most churned area
- `apps/desktop/` (Electron + Vite/React TS; `electron/`, `src/`, `e2e/` Playwright, packaging, updater feed), `apps/shared/`, `apps/bootstrap-installer/` (Tauri). Docs: `features/desktop.md`, `web-dashboard.md`, `extending-the-dashboard.md`
- `tui_gateway/` package: `server.py` + ~30 `methods_*.py` RPC modules (methods_browser, methods_complete, methods_config, methods_connectors, methods_display, methods_free_tier, methods_groups, methods_i18n, methods_images, methods_onboarding, methods_profiles, methods_projects, methods_prompt, methods_session*, methods_tools, methods_bot_relay, …) + `contracts/` typed payloads (billing, connectors, sessions, liveness, prompt_voice, profiles_vault_complete_foreign_subagents, …) + `compute_host.py`/`compute_host_bridge.py`
- In-window: desktop src churned 201 files (+6,931/−5,920), electron 43 files (+1,212/−847). The desktop "capabilities catalog" UI (`src/app/capabilities/catalog/*`) was **deleted** — catalog moved to the repo-level `plugin-catalog/` YAML catalog rendered per docs `features/plugin-catalog.md`. New electron modules: `embed-host.ts`, `preview-guest-offscreen.ts`, `preview-url-target.ts`, `watch-storm-breaker.ts`, `updater/relaunch-waiter-resource`; renderer-server.ts removed. Windows MSIX/appx assets + macOS 26 layered icons + DMG volume icons added.

### 7. Provider registry — present
- `agent/provider_registry.py` = generic `ProviderRegistry` engine (global + per-profile scoped maps, hot-reload re-registration, snapshot/restore for plugin unwind) reused by all `agent.*_registry` modules (TTS/browser/etc.). Last touched 2026-09-05 — stable. Provider breadth lives in `agent/model_metadata.py` (+78 in-window) and the `providers/` base package; model pickers include Nous Portal, OpenRouter, OpenAI, Anthropic, Bedrock (`agent/bedrock_adapter.py`), Azure identity (`agent/azure_identity_adapter.py`), Codex OAuth runtime (`agent/codex_runtime.py` + `codex_responses_adapter.py`, new picker variant `gpt-6.1-sol-900k`), subscription-proxy feature doc. Docs: `features/provider-routing.md`, `fallback-providers.md`, `credential-pools.md`, `configuring-models.md`.

Other live capability docs (for orientation): mcp.md (huge `tools/mcp_*.py` family incl. OAuth/device/loop/sampling), memory.md + memory-providers.md, voice-mode.md/wake-word.md/tts.md, kanban*.md, loops.md, pets.md, goals.md, heartbeat.md, deliverable-mode.md, acp.md, code-execution.md, lsp.md, tool-search.md, web-search.md/x-search.md, spotify.md, skins.md, language-packs.md.

## Notable upstream changes since 2026-10-01 baseline (aea969677c..a6e75acb0d, 518 commits)

Conventional-commit mix: 264 fix / 92 test / 40 refactor / 17 feat / 12 docs — a stabilization window, not a feature wave. Churn by area: `apps/desktop` (largest), `hermes_cli` (64 files, +2,029), `agent/` (43 files, +1,193), `gateway/` (+435), `cron/` (+245), `website/docs/` (+530); `tools/` mostly quiet (23 files, +514).

1. **Honcho memory plugin un-bundled** — `plugins/memory/honcho/*` deleted ("chore(memory): remove bundled honcho provider; install from the plugin catalog", 7e53b3ef82); new `hermes_cli/memory_provider_migration.py` and plugin-catalog listings for retaindb / byterover / holographic memory (Nous-maintained). README still advertises Honcho user modeling, but it is now catalog-installed.
2. **Plugin guard hardening** — `tools/plugin_guard_context.py` +151, new `hermes_cli/plugin_validate_core_override.py` (+331); feature: "refuse plugins that override Hermes core or Desktop at runtime"; two rounds of false-positive fixes from a 2026-10-01 catalog sweep.
3. **Anthropic thinking plumbing** — new `agent/anthropic_thinking_replay.py` (+206) and `agent/anthropic_thinking_policy.py` (+74); `agent/anthropic_message_convert.py` reworked.
4. **New `agent/tool_call_batches.py`** (+80) and `agent/message_sanitization.py` (+99), plus turn-recovery work (`turn_recovery.py`, `repetition_guard.py`, `transcript_repair.py`, `turn_context.py`) — agent-loop robustness cluster.
5. **CLI status revamp** — `hermes status` summary is now the default (`--full` for everything), new `hermes status --short`; new `hermes_cli/gitlock.py`, `windows_store_update.py`, `windows_appinstaller_update.py` (Windows Store/App Installer update channels).
6. **Git-safety sweep** — "neutralize repository-named git filters" across subagent worktrees, kanban, worktree-gc, recovery hints, session snapshots; remaining index-reading git calls under `noninteractive_git_env`. Touches `tools/subagent_worktree.py` and `tools/async_delegation_recovery_hints.py` (relevant to Atlas's own worktree tooling).
7. **Desktop update/release pipeline** — win32 bundle candidate gate, release-abandon cancels runs, updater handoff readiness, macOS/Windows icon work, `apps/desktop/electron/watch-storm-breaker.ts`.
8. **Gateway relay metrics + turn liveness** — shared metrics flush off-turn, relay metrics test/export fixes; open PR #128528 adds `turn.alive` ("tell clients a quiet turn is still running") and #129791 isolates profile-owned delegation child controls.
9. **Misc feats** — kanban in-process schedule tool, desktop message-timestamp hover, Classic Hermes gold/navy skin, plugin-catalog additions (go-whatsapp, 0bull, woof).

## Notes for Atlas U0/U1

- **Freeze recommendation:** pin Atlas to `a6e75acb0d` (2026-10-02). The Oct 1→2 window alone is small; the 518-commit delta is dominated by desktop UI, Windows/macOS packaging, and CLI status — none of it breaks the seven backend capability areas Atlas forks.
- **No supersession risk for Atlas's own implementations** in browser/CUA/skills/delegation: `browser_tool.py`, `browser_supervisor.py`, `browser_tool_real_profile.py`, `browser_extension_router.py`, `browser_vault_tool.py`, `computer_use/`, `skills_hub.py`, `curator.py`, `delegate_tool.py`, `provider_registry.py` were all untouched in the window (last upstream touch 2026-09-03..09-28). If Atlas reimplemented any of these, upstream has not moved past the fork point on them.
- **Cherry-pick candidates for Atlas:** the repo-wide git-filter neutralization series (bba715b42d, 9c589b91bd, 803cd03521, 1ff01f4cf7) if Atlas uses `subagent_worktree`/git ops; plugin core-override guard (`plugin_guard_context.py` + `hermes_cli/plugin_validate_core_override.py`) if Atlas loads plugins; Anthropic thinking replay/policy if Atlas relies on Anthropic extended thinking.
- **Divergence watch:** upstream un-bundled the Honcho memory plugin (catalog-installed now) and removed the desktop capabilities-catalog UI in favor of the repo-level `plugin-catalog/` YAMLs — if Atlas's fork carries `plugins/memory/honcho` or desktop catalog code, those are now dead weight vs upstream.
- **Two open PRs to track** for near-term main movement: #128528 (`turn.alive` quiet-turn liveness, desktop+gateway) and #129791 (profile-owned delegation child control isolation), plus #129836 (profile-scoped plugin lifecycle registrations).
- Upstream has no GitHub Releases/tags-based versioning; treat `main` HEAD + docs site as the release surface. Installers target Python 3.14.
