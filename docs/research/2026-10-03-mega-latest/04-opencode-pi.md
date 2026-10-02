# OpenCode + Pi source freeze — 2026-10-03

Scope: state of the world as of 2026-10-03. All versions/dates verified via GitHub API (releases) and shallow clones of both repos at HEAD/tag.

---

## OpenCode freeze

**Repo:** [github.com/anomalyco/opencode](https://github.com/anomalyco/opencode) (moved from `sst/opencode` — API returns `Moved Permanently` for the old path; OpenCode is now maintained by Anomaly). Default branch: `dev`. Site: [opencode.ai](https://opencode.ai).

**Latest release:** [`v1.18.34`](https://github.com/anomalyco/opencode/releases/tag/v1.18.34), published **2026-09-30** (release authored by `opencode-agent[bot]`; cadence is ~1–3 patch releases/week). Repo `dev` HEAD on 2026-10-02 is still `1.18.34` in `packages/opencode/package.json`.

**Architecture — a v1/v2 dual core mid-migration** (important context):
- `packages/opencode` = the shipping **v1** CLI (Bun + server + TUI), version 1.18.34. Contains `src/lsp/` (client, server, diagnostics, launch), `src/agent/` (built-in `build` + `plan` + `general` agents, with `plan_enter`/`plan_exit` permission events and plan-file write rules allowing only `.opencode/plans/*.md` and `~/.local/share/opencode/plans/*`), `src/permission/`, `src/plugin/`, `src/command/`, `src/skill/`, `src/snapshot/`, `src/session/` (compaction, revert), `src/mcp/`, `src/acp/`.
- `packages/core` = the new **v2** core, rewritten on the **Effect** library (services as Layers: `AgentV2`, `CommandV2`, `PermissionV2`, `Snapshot`, `SessionRevert`, `SessionCompaction`, `EditTool`, etc.). Drizzle/SQLite-backed sessions. This is where development energy is going; recent commits include "port Astra system prompt from v2" and CI jobs syncing a v2 models catalog daily.
- Other packages: `plugin` (v1 plugin host + `v2/`), `sdk`, `sdk-next`, `tui`, `desktop` (Electron app, heavy active development), `web`, `console`, `server`, `protocol`, `schema`, `llm`, `containers`, `slack`, `stats`.

**Feature areas at freeze (v2 core, `packages/core/src`):**
- **Edit tool** (`tool/edit.ts`): exact `oldString`→`newString` replace with `replaceAll`, BOM/line-ending preservation, `FileDiff` output `{files, replacements}`; paths outside the active Location require a separate `external_directory` approval before edit approval. There is also `apply-patch.ts` (its permission metadata was fixed in v1.18.26 to omit empty move paths).
- **LSP**: v1 has a full LSP runtime; the v2 core has an LSP **config schema** (`config/lsp.ts`) but `edit.ts` carries `// TODO: Add LSP notification and diagnostics after V2 LSP runtime exists.` — v2 LSP runtime does not exist yet at freeze.
- **Permissions** (`permission/`): v2 `PermissionV2` with a `saved.ts` persistence store (remembered approvals) + SQL tables; edit/external-directory/bash approvals flow through it. v1 keeps the ask/allow-always flow.
- **Compaction** (`session/compaction.ts`): LLM-summarized compaction with a strict structured Markdown template (Objective / Important Details / Work State (Completed/Active/Blocked) / Next Move / Relevant Files), iterative merge with prior summary, defaults `buffer=20k`, `keep=8k`, tool-output truncation at 2k chars, 4k summary output cap.
- **Snapshots/undo**: v2 `snapshot.ts` is a **content-addressed tree** capture (operations: capture / files / diff / preview / restore; best-effort, returns undefined when disabled); `session/revert.ts` reverts a session to a message boundary and restores files via Snapshot. (v1 had git-based snapshots under `src/snapshot/`.)
- **Agents/subagents**: agents are config-defined (`@opencode-ai/schema/agent`), default agent `build`; `mode: "subagent"` marks agents invocable via the `task` tool. Subagent failures are surfaced as resumable (`task_id`) since v1.18.20.
- **Plan mode**: v1 built-in `plan` agent unchanged in the window (restricts writes to plan files, uses `plan_enter`/`plan_exit`).
- **Plugins**: `packages/plugin` with tool/TUI/shell/workspace hooks + a v2 variant; only one fix in the window (`/status` dialog plugin-name extraction on Windows, v1.18.34).
- **Commands**: custom commands (markdown prompt files) unchanged in v1; desktop app gained an archive-session command (v1.18.21).

---

## OpenCode recent changes (last ~6 weeks: v1.18.20 → v1.18.34, 2026-08-21 → 2026-09-30)

Sources: [releases v1.18.20–v1.18.34](https://github.com/anomalyco/opencode/releases) + `git log --since=2026-08-20` on `dev` (~424 commits).

- **v1.18.20 (08-21)** — subagent reliability: failed subagent tool calls surface with a resumable `task_id`; permission requests triggered by subagents are answered during `opencode run`.
- **v1.18.15 (08-07)** — **revert/fork now use real message chronology instead of message-ID ordering**; repeated compaction keeps earlier tool-call history in summaries instead of dropping orphaned results.
- **v1.18.17 (08-12)** — **session compaction keeps complete recent turns and produces clearer summaries for smaller models**; capped automatic session retries + jitter (anti retry-storm).
- **v1.18.19 (08-20)** — native OpenAI/Anthropic passthroughs for Cloudflare AI Gateway; Codex rate limits matched to ChatGPT subscriptions; v1 database compatibility preserved.
- **v1.18.22–25 (08-24→28)** — Azure sign-in via Microsoft Entra ID / Azure CLI without Bun; Cloudflare AI Gateway routing fixes for third-party + dotted Anthropic model IDs.
- **v1.18.26–27 (09-01→02)** — Claude 5 sessions tolerate stale thinking blocks; `apply_patch` no longer emits empty move path in permission metadata; Anthropic `thinking.blockBinding` configurable opt-out and limited to Claude 5.1+; default provider response/stream chunk timeouts of 5 minutes.
- **v1.18.29–30 (09-04→09)** — **GPT-6 Astra** system prompt added for GPT-6 models; GitLab reasoning-effort variants.
- **v1.18.31 (09-14)** — ACP fix: restored session model/effort/mode/reasoning chunk boundaries when loading, resuming, or forking sessions.
- **v1.18.32–33 (09-21→28)** — Bedrock image-attachment hoisting restricted to Claude/Nova/Llama 4; Cloudflare gateway honors provider timeouts; Gemini thinking defaults reworked.
- **v1.18.34 (09-30)** — namespaced session/parent-session identity headers on model requests; **macOS release binaries now Developer-ID signed** (and ad-hoc re-signed after local compiles for macOS 27+).
- **Desktop app (continuous)**: large i18n + right-to-left layout push (v1.18.13–22), markdown parsing off main thread, JSON transcript export from UI (v1.18.15), archived sessions leave Home immediately, tab-state repair.
- **Model catalog wave**: Claude Opus 5.5, GPT-6 Sol/Luna (incl. Codex), Grok 4.7, DeepSeek V4.1 Flash, MiMo V2.6 added across Zen/Go/providers.
- **Did NOT change in the window**: edit tool, LSP, plan mode, plugin system, command system — effectively frozen; effort is going into provider integration, desktop, and the v2 core migration (v2 catalog sync CI, v2 desktop download links, "port Astra system prompt from v2").

---

## Pi freeze

**Repo:** [github.com/earendil-works/pi](https://github.com/earendil-works/pi) — **moved from `badlogic/pi-mono`** (GitHub API redirects repo id 1035029907 to `earendil-works/pi`). Description: "AI agent toolkit: unified LLM API, agent loop, TUI, coding agent CLI". Author: Mario Zechner (badlogic).

**Latest release:** [`v1.0.0`](https://github.com/earendil-works/pi/releases/tag/v1.0.0), published **2026-10-01** — first 1.0, jumping from v0.87.1 (09-22) via v0.99.0–0.99.2 (09-29/30).

**Monorepo packages (13, all at 1.0.0):** `agent` (= **`@earendil-works/pi-agent-core`**, deps only `@earendil-works/pi-ai` + typebox), `ai` (pi-ai unified provider layer), `coding-agent` (the `pi` CLI, npm `@earendil-works/pi-coding-agent`), `tui`, `codemode`, `mcp`, `protocol`, `server`, `client`, `durable` (experimental durable execution), `chord` ("application composition runtime for services, replicated state, RPC, and plugins"), `evals`, `telemetry`.

**Checked specifics:**
- **agent-core / session tree / JSONL** (`packages/coding-agent/docs/session-format.md`): sessions are JSONL at `~/.pi/agent/sessions/--<path>--/<ts>_<id>.jsonl`; entries form a **tree via `id`/`parentId`** (format v3; v1 linear and v2 tree auto-migrate). System messages persist prompt sections + tool loadout as replayable patches (`sections`, `toolsAdded`/`toolsRemoved`) — no separate prompt-state entry. `SessionManager` is canonical for provider context (breaking change v0.87.0); tree navigation via `session.navigateTree()`; `SessionManager.inMemory()` restores externally stored sessions (v0.85.0). RPC exposes `get_entries`/`get_tree`.
- **Compaction** (`docs/compaction.md`): structured-summary compaction (template + `firstKeptEntryId` pointer, iterative with prior summary), defaults `reserveTokens=16384` / `keepRecentTokens=20000`, per-model budget overrides (v0.86.0), retry-policy-driven summarization with retry lifecycle events (v0.81.1), `session_compact_failed` events (v0.84.3), split-turn summary fix for Claude (v0.87.1), compaction/branch usage persisted into session totals (v0.81.0). Branch summarization preserves context when switching `/tree` branches.
- **Tools**: built-ins are `read`, `bash`, `edit`, `write`, `find`, `grep`, `ls`, plus optional Windows `powershell` (v0.84.3). `defaultTools` setting configures startup loadout globally/per-project (v0.84.2). Experimental strict JSON-schema constrained sampling for the four core tools under `PI_EXPERIMENTAL=1` (v0.84.2); general constrained-sampling API (`prefer`/`require` strict schemas, Lark/regex grammars) since v0.82.0.
- **Steering/queue**: agent-core has a mid-run steering poll plus a queued-follow-up drain with modes `"all"` or `"one-at-a-time"` (`packages/agent/src/types.ts`); RPC `clear_queue` to retrieve/clear queued steering + follow-ups (v0.84.4).
- **Subagents: NOT built-in.** At v1.0.0 the only subagent implementations are (a) the official **example extension** `packages/coding-agent/examples/extensions/subagent/` (spawns separate `pi` processes, markdown agent definitions — scout/planner/reviewer/worker — parallel streaming, usage tracking, Ctrl+C propagation) and (b) `src/experimental/durable/subagent.ts` (experimental). Multi-agent composition is moving toward the `chord`/`durable` packages.
- **Extensions system** (`docs/extensions.md`): TypeScript files loaded via **jiti** (no compile step) from `~/.pi/agent/extensions/` or project dirs (or distributed as pi packages). Event-driven: `before_agent_start`, `tool_call` (block/modify/`terminate`), turn lifecycle (`turn_end` via `emitBoundary`), `agent_settled`, `AgentBeforeSettleEvent`, `finishTurn` tool hook (`{action:"end"}` replaced `shouldStopAfterTurn`, v0.87.0 breaking change), `session_info_changed`, `session_compact_failed`, `ui_prompt_start/end` (v0.84.4), `project_trust`. Tools get **exposure control** (`direct` / `model-only` / `codemode` / `deferred` / `hidden`), `namespace`, `annotations`, `outputSchema`/`structuredContent`, `isError`, and cache-friendly dynamic tool loading (v0.80.7). Extensions can register full pi-ai providers (v0.81.0), MCP servers (`pi.registerMcpServer`), custom message renderers/modes, commands, `sendUserMessage` with template/skill expansion.
- **Snapshot/revert capability**: **session-tree branching only — no git-style file snapshot/undo.** `/tree` moves within the session file (editing a user message creates a new branch), `/fork` and `/clone` create sibling/child sessions; leaving a branch can attach a branch summary. Nothing reverts files on disk; there is no checkpoint tool.
- **v1.0.0 headline features**: fullscreen TUI by default (`tuiMode: "regular"` to opt out), leaner codemode (~40% fewer prompt tokens), image generation in codemode (`models.generateImages()`), Radius login, MCP OAuth hardening, `quietStartup: "header"`.

---

## Pi recent changes (last ~6 weeks: v0.84.1 → v1.0.0, 2026-08-07 → 2026-10-01)

Sources: [releases v0.84.1–v1.0.0](https://github.com/earendil-works/pi/releases) + `packages/coding-agent/CHANGELOG.md`.

- **v0.84.2 (08-14)** — fullscreen transcript search (Ctrl+Shift+F); `defaultTools` setting; experimental constrained JSON-schema sampling for `read`/`bash`/`edit`/`write`.
- **v0.84.3 (08-24)** — **Windows PowerShell tool**; atomic staged installer-managed updates; `/thinking` selector; `session_compact_failed` extension events; Anthropic server-side refusal fallback.
- **v0.84.4 (08-28)** — RPC `clear_queue` (steering/follow-up queue control); `ui_prompt_start`/`ui_prompt_end` events (distinguish agent work from waiting on `ctx.ui` prompts); terminal capability overrides; DeepSeek V4 Flash Vision (experimental).
- **v0.85.0/0.85.1 (09-04/05)** — **prompt cache warming** was v0.86; v0.85 added persistent Claude thinking effort (per-turn effort preserved, signed-thinking mismatch recovery), `SessionManager.inMemory()`, faster fullscreen search; 0.85.1 fixed SDK import breakage by making experimental `client`/`plugin` subpaths source-only.
- **v0.86.0 (09-19)** — **prompt cache warming** (cost-aware refresh during long tool runs / idle); **per-model compaction budgets**; `/bug` redacted diagnostics reporting; **transcript-backed mid-conversation system-prompt/tool changes** (survive resume + branch navigation while keeping cached prefixes); breaking: custom providers read from normalized `TranscriptContext` (`getCurrentSystemPrompt()`/`getCurrentTools()`).
- **v0.86.1 (09-20)** — Meta Muse provider (`/login meta`); Node persistent compile cache for faster CLI startup; OSC 52 clipboard fallback for containers/WSL.
- **v0.87.0 (09-21)** — **breaking refactor of agent boundaries**: `ContextEditEntry` (edit model context without rewriting history), `context_with_system` per-request system transforms, `finishTurn` replaces `shouldStopAfterTurn`, `SessionManager` canonical for provider context, `TurnEndEvent` expanded + `AgentBeforeSettleEvent`; per-model image input limits.
- **v0.87.1 (09-22)** — Claude Opus 5.5 / GPT-6 Sol / GPT-6 Luna catalogs (incl. Copilot); xAI default Grok 4.7; fixed split-turn compaction summaries refused by Claude models.
- **v0.99.0 (09-29)** — **codemode + tool search + MCP became built-in extensions**: `codemode` tool runs model-written JS in a **QuickJS sandbox** calling pi's tools; `tool_search` declares tools on demand; MCP over stdio/streamable-HTTP with OAuth, managed via `/mcp` and `pi mcp add|remove|list|login|logout`. Also system-theme (terminal palette) default, **Sign in with ChatGPT**, **virtual models** (extensions route each request to a different physical model), classifier models.
- **v0.99.1–0.99.2 (09-29/30)** — GPT-6.1 Sol default for OpenAI Codex; MCP servers with default `codemode` exposure no longer block first prompt (surfaced via system prompt + `searchTools()`/`describeNamespace()`); provider-token auth for HTTP MCP servers; Anthropic workload identity federation.
- **v1.0.0 (10-01)** — fullscreen TUI default; leaner codemode (~40% fewer prompt tokens, self-correcting errors); image generation via `models.generateImages()`; MCP OAuth hardening (RFC 9207, per-server credentials, step-up); `quietStartup: "header"`; Anthropic copy-code login for remote browsers.

---

## Notes for Atlas

1. **Both projects rename/moved repos recently**: OpenCode `sst/opencode` → `anomalyco/opencode`; Pi `badlogic/pi-mono` → `earendil-works/pi`. Any Atlas code, docs, or caches referencing the old repos should use the new canonical URLs (old paths 301-redirect).
2. **Pi v1.0.0 (2026-10-01) is the first stable release** — a good API-stability anchor if Atlas wants to build on pi's SDK (`@earendil-works/pi-coding-agent` / `pi-agent-core` / `pi-ai`). But breaking changes were frequent through 0.8x (0.84.0, 0.86.0, 0.87.0, 0.99.0 all had them); pin exactly and expect churn in provider/auth facades (`ModelRuntime` replaced `AuthStorage` in 0.80.8).
3. **Pi has no built-in subagents** — multi-agent is an official example extension (separate `pi` processes) plus experimental `durable`/`chord` packages. If Atlas wants subagents, budget for building them on the extension API, and note the subagent example's process-per-agent isolation model (streaming, usage tracking, abort propagation) is directly reusable.
4. **Pi has no file snapshot/undo** — revert = session-tree branching (`/tree`, `/fork`, `/clone`) + branch summaries. OpenCode is the opposite: content-addressed file snapshots with message-boundary revert (v2) / git snapshots (v1). Atlas's snapshot/undo design choice should pick consciously between these two poles.
5. **Session formats**: pi = JSONL tree with `id`/`parentId` (v3 format, self-describing, replayable prompt/tool patches) vs OpenCode v2 = SQLite/Drizzle (Effect services), v1 = its own storage with v1/v2 DB compat shims. Both are converging on "tree-structured, branchable history + structured compaction summaries"; pi's JSONL is much easier to inspect/sync externally.
6. **Compaction convergence**: OpenCode v2 uses a fixed structured Markdown template (Objective/Important Details/Work State/Next Move/Relevant Files) merged iteratively; pi uses structured summaries + `firstKeptEntryId` with per-model token budgets and retry events. Both keep recent turns intact and treat summaries as context-edit entries.
7. **Codemode trend**: pi 0.99.0 shipped sandboxed (QuickJS) model-written JS as a built-in with tool search + MCP namespaces, cutting prompt tokens ~40% — worth evaluating for Atlas's tool-loading strategy (same direction as deferred tool exposure).
8. **OpenCode is mid-rewrite**: shipping CLI is v1 (Bun, no Effect), v2 core is Effect-based with SQLite sessions and a not-yet-existing v2 LSP runtime. Do not treat `packages/core` APIs as stable; watch the v2 migration for where OpenCode lands (desktop-first, remote workspaces, cloud "Go" plans).
9. **Windows support divergence**: OpenCode desktop/TUI fixed several Windows-specific issues (plugin path extraction, local binary signing for macOS though — Windows signing not mentioned); pi added a native PowerShell tool and WSL clipboard handling. Relevant if Atlas targets Windows developers.
10. **Verification dates**: OpenCode release feed checked 2026-10-03 (latest v1.18.34, 09-30; dev HEAD 10-02). Pi releases checked 2026-10-03 (latest v1.0.0, 10-01; repo pushed 10-02). Local clone copies used for verification: `/tmp/oc-repo` and `/tmp/pi-repo` (shallow, disposable).
