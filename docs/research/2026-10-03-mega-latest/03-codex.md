# OpenAI Codex — source-freeze dossier (2026-10-03)

Repo: https://github.com/openai/codex ("Lightweight coding agent that runs in your terminal")
Layout: Rust workspace `codex-rs/` (~200 crates) + TypeScript (`codex-cli` npm shim, `sdk/typescript`, desktop app). License Apache-2.0.

## Version freeze

| Item | Value |
|---|---|
| Latest stable tag | `rust-v0.160.0`, released **2026-10-01 20:19 UTC** (https://github.com/openai/codex/releases/tag/rust-v0.160.0) |
| Previous stables | 0.159.3 (Sep 30), 0.159.0/.1/.2 (Sep 29), 0.158.0 (Sep 28), 0.157.0 (Sep 25), 0.156.0 (Sep 22), 0.155.1 (Sep 18), 0.155.0 (Sep 17) |
| Atlas 2026-09-15 baseline | latest stable was **0.154.0 (Sep 9)** (GPT-6-Astra availability, experimental worktree support); alphas 0.155.0-alpha.* were cutting edge that day (https://github.com/openai/codex/releases, pages 12-14) |
| In-flight pre-releases | 0.161.0-alpha.1–13 (Oct 1), 0.162.0-alpha.1–7 (Oct 1–2) |
| Repo stats (2026-10-03) | ~127.6k stars, ~20k forks, 11,781 commits on main, last push 2026-10-02 21:52 UTC |
| Activity | Extremely high: 546 commits between 0.156.0→0.157.0 (2-3 days), 356 commits 0.157.0→0.158.0, 268 commits 0.158.0→0.159.0; >100 commits/day peaks; PR/issue numbers moved ~#49,160 (0.160.0 window) → ~#50,437 (Oct 2). Cadence: stable every 1–3 days + dozens of `*-alpha.N` per day, 178 release assets per tag (macOS/Linux/Windows, incl. musl). |
| CHANGELOG | `CHANGELOG.md` on main now defers to the releases page; only an "Unreleased" entry (fix: unified exec command lifecycle events when process creation fails, #44557) |

## Recent capability changes (0.155.0 → 0.160.0, Sep 17 → Oct 1; vs 0.154.0 baseline)

### Agent loop / steering
- **NEW (0.159.0) "instant_interrupt"** (opt-in): new user input steers/interrupts Codex *while the model is still responding* or during long code-mode tool calls (#48135, #48141). https://github.com/openai/codex/releases/tag/rust-v0.159.0
- **NEW (0.159.0)** compact welcome screen for new sessions; transcript scrolling while deciding whether to implement a plan (#48805); warnings viewer ("k" to keep a warning).
- (0.157.0) fullscreen transcript default-on; `f` shortcut forks a conversation open in another app, preserving drafts and queued prompts; `/import` available in remote and background-server sessions.
- (0.156.0) streamed answers/plans preserved when turns fail or are interrupted, including subagent completion events; plan mode restored on resume.

### apply_patch (V4A format)
- No change to the patch *format* in the window. Changes are all permission/safety integration: authorize `apply_patch` in the executor path context (#42391, Sep 2); macOS system-alias path matching in patch permission checks (#47879, Sep 24 → shipped 0.158.0); Guardian reviews bound to the action's target environment (#47630); filesystem sandbox policy context preserved when cwd disappears (#46112). Crate: `codex-rs/apply-patch` + `codex-rs/core/src/apply_patch.rs`.

### unified_exec / terminal
- Source layout (verified 2026-10-03): `codex-rs/core/src/unified_exec/` (process manager, process state, oneshot, stdin approval, shell snapshot, head/tail buffer, async watcher), tool handlers `core/src/tools/handlers/unified_exec/{exec_command,write_stdin}.rs`, Windows backends `codex-rs/windows-sandbox-rs/src/unified_exec/backends/{legacy,elevated}.rs`.
- TUI: `/ps` lists background terminals (multiline previews since 0.158.0), `/stop` stops all.
- (0.158.0) exec-server WebSocket connections secured with bearer tokens; (0.159.0) unique exec-server process IDs; stray console windows on Windows eliminated for MCP servers, code-mode hosts and piped commands, with embedded-mode fallback; command completion events include early output and report launch failures.

### Review mode + "Guardian" (the big new subsystem)
- `/review` = "review my current changes and find issues" (inline args supported) — `codex-rs/tui/src/slash_command.rs`.
- **NEW: Guardian** — an automated policy/safety reviewer wrapped around approvals and agent actions, rolled out across this window: approval reviews preserve actions/authorization evidence and retry transient failures (0.155.0); Guardian thread context **enabled by default** + message-board partial index + policy config (0.157.0); OTLP logging of final responses and Guardian assessments (0.158.0); Guardian circuit-breaker structured errors (0.159.0); **NEW (0.160.0) opt-in Guardian review features pull earlier user instructions and agent-handoff context** (#49036, #49057). Crates: `codex-rs/ext/guardian-reviewer`, `codex-rs/ext/guardian-v2` (async scorer), `codex-rs/core/src/guardian`, `codex-rs/protocol/src/openai_models/guardian*.rs`.
- `/approve` (AutoReview): "approve one retry of a recent auto-review denial" — i.e., denials can be auto-retried with explicit user approval.

### Plan mode
- Implemented as a **"collaboration mode"**: `ModeKind::{Plan, Default}` (aliases: code, pair_programming, execute, custom) with per-mode model/reasoning/developer-instruction presets (`codex-rs/models-manager/src/collaboration_mode_presets.rs`, `codex-rs/protocol/src/config_types.rs`). Plan mode uniquely `allows_request_user_input()` (structured elicitation of clarifying questions).
- (0.156.0) plan mode restored on session resume; (0.159.0) can scroll transcript while deciding whether to implement the plan; (0.160.0) plan-mode cycling hint in the fullscreen status line. `/plan` supports inline args.

### Permissions / sandbox
- Documented model unchanged (developers.openai.com/codex/security; repo stub `docs/sandbox.md` now redirects there): sandbox modes `read-only | workspace-write | danger-full-access`, approvals `untrusted | on-request | on-failure | never`; OS mechanisms Seatbelt (macOS), seccomp+namespaces/Landlock (Linux), AppContainer/restricted tokens (Windows); network off by default in workspace-write. Docs moved off-repo to developers.openai.com (also `docs/skills.md`, `docs/slash_commands.md` are 3-line stubs).
- NEW direction: **exec-server** as a broker that runtime-enforces permission grants (streaming approvals), `codex mcp`-style terminal-input approval default for elevated commands (0.158.0); network policy enforced across redirects, ongoing HTTP/WebSocket traffic, app-server requests, AWS auth, remote control (0.157.0); `.aws` directories protected by default under writable roots; approved commands keep explicit filesystem denials (0.159.0).
- Windows sandbox: sustained hardening (WSL escape blocked 0.155.0; inbound-connection and privileged-socket gaps closed 0.156.0; logon-session object-access limits 0.157.0; Win10 paths / stored credentials / large policies fixed 0.158.0; PowerShell fallbacks + long-path ACL repair 0.160.0). On main (Oct 2): new CLI command to uninstall the legacy Windows sandbox (#50437).
- `/permissions` ("choose what Codex is allowed to do") + `/setup-default-sandbox` (elevated agent sandbox setup); projectless sessions use workspace defaults and restore saved permissions on resume (0.160.0).

### Skills
- Crate `codex-rs/skills`; SKILL.md-based, description-only injection until invoked; `/skills` picker. Docs now at developers.openai.com/codex/skills.
- **NEW**: cloud/executor skill listings deduplicated before budgeting (0.160.0, #49127) — skills now come from the account/cloud as well as disk; bundled sample skill `openai-docs` ships GPT-6 migration references; bundled `plugin-creator` skill **removed** (0.159.0); `repo_url` dropped from skill invocation analytics (0.155.0).

### MCP
- (0.158.0) `codex mcp add --oauth-client-secret` for servers requiring pre-registered OAuth client secrets; (0.155.0) accurate expired-credential reporting + reconnect guidance; (0.156.0) credential refresh on 503 OAuth discovery errors; (0.157.0) security restrictions — Unix local MCP servers limited to stdio descriptors, OAuth endpoints restricted to HTTP(S); (0.159.0) single-server status discovery, credential boundaries preserved across reconnects. `/mcp [verbose|login <name>]`. Crates: `codex-mcp`, `rmcp-client`.

### Subagents / threads / agent command center
- **NEW infrastructure**: `codex-rs/core/src/agent/` (AgentControl, registry, roles, resolver, child config, SpawnRequest routing — 0.157.0), agent message board with subscriptions/notifications, plus crates `agent-graph-store`, `agent-identity`, `agent-roles`, `agent-message-board-client`.
- **NEW UI**: `/agents` opens the **agent command center** — task list with status/worktree filtering (0.156.0), hide/archive/delete tasks, worktree ownership details, confirmed deletion of clean managed worktrees (0.155.0), browsable older tasks via keyboard-accessible "Show more" (0.160.0). `/subagents` switches between the current session's subagents. Subagents keep still-starting environments and surface config/preparation failures (0.160.0).
- **NEW (on main, post-0.160.0)**: `/side` and `/btw` — "start a side conversation in an ephemeral fork" (side conversations have their own allowed-command subset).
- `/goal` sets/views the goal of a long-running task; saved threads/active goals recover after daemon restarts (0.155.0). App-server clients can paginate thread history from a specific item (0.159.0). Worktrees are enabled by default (0.156.0).

### Compaction
- `/compact` ("summarize conversation to prevent hitting the context limit") and **NEW `/recap`** ("summarize the current conversation now"). **NEW remote compaction v2**: `core/src/compact_remote_v2*.rs` (history changes in 0.157.0, image budget handling), `history` crate compaction checkpoints/resume metadata, `rollout-trace` compaction reducer. Prompts are saved even if compaction fails before a turn starts (0.155.0).

### Models
- Baseline 0.154.0 added **GPT-6-Astra**. **NEW (0.157.0): GPT-6 Sol and Luna**, incl. Amazon Bedrock support and migration prompts for older models (#47332, #47347). **GPT-5.4 removed** from bundled catalogs (0.158.0) while keeping migration prompts. Bedrock catalog slugs (verified in `codex-rs/model-provider/src/amazon_bedrock/catalog.rs`): `gpt-5.5`, `gpt-5.6-{luna,sol,terra}`, `gpt-6-{astra,luna,sol}`, `gpt-6.1-sol`.
- **NEW "Daybreak"**: a cyber access program (DaybreakBlue/DaybreakRed treatments) advertised per-model via `ModelAccessPrograms` (`codex-rs/protocol/src/openai_models/access_programs.rs`), toggled with `/daybreak`; main (Oct 2) allows API-key accounts to use Daybreak in the TUI (#50433). Wired into `state` migrations (`0054_threads_daybreak_enabled.sql`).
- Reasoning effort: `max`/`ultra` values in the TypeScript/Python SDKs (Python SDK 0.154.0 release); Pro Max plan support (0.158.0). Explicit provider model catalogs are treated as authoritative (no stale bundled entries) (0.160.0).

### Other major new surfaces since the Sept 15 baseline
- **Voice conversations** (entirely new): experimental `/voice` with live transcripts and mic controls (0.155.0); **on by default** with F8 toggle, `/voice settings` picker, bundled audio runtimes (0.156.0); active voice survives thread switching (0.157.0); `realtime-webrtc` crate, RTP timestamp alignment (0.159.0).
- **Fullscreen TUI** (`/tui`): transcript search, mouse select/copy, copy-on-select, middle-click paste on Linux X11 (0.156.0→0.160.0); default from 0.157.0.
- **Daemon**: background app-server (`codex-rs/app-server-daemon`), `/daemon` menu + `--no-daemon`, configurable update schedules, `codex app-server daemon update` (0.155.0-0.156.0); auto background-server startup for eligible sessions (0.157.0).
- **Usage analytics**: `/usage` dashboard (account usage, token totals, plugin/skill activity) (0.156.0).
- **Memories & hooks**: `/memories` (memory use/generation config; `memories` crate, `context-fragments`), `/hooks` (lifecycle hooks; `hooks` crate, hook_runtime, hook_mcp_executor).
- **Plugins & apps**: `/plugins` browser, plugin manifest caching + HTTP connection reuse (0.160.0); `/apps` + `connectors` crates; IDE context via `/ide`.
- **Import migration**: `/import` brings setup, project, and recent chats **from Claude Code**.
- Rendering: Mermaid diagrams + display equations in responses (0.156.0+), Unicode bullets/checkboxes/aligned math (0.157.0), six new themes, terminal pets.
- Misc removals: follow-up prompt suggestions removed (0.159.0); "friendly"/"pragmatic" personality settings no longer affect responses (0.156.0).

## Notes for Atlas parity mapping

1. **Steering**: `instant_interrupt` (0.159.0) is Codex's answer to mid-turn steering — queue-and-interrupt with opt-in; compare with Atlas's send-while-running behavior. Queue integrity (resume-after-reconnect without duplicate sends, drafts preserved on fork) is a repeated bugfix theme worth matching.
2. **Guardian is the pattern to study** for Atlas's permission UX: an automated reviewer scoring actions (async scorer in guardian-v2), bound to the target environment, producing structured circuit-breaker errors, with an `/approve` escape hatch for retrying auto-review denials. It sits *between* sandbox rules and the user approval.
3. **Plan mode = collaboration-mode mask** (per-mode model/reasoning/developer-instructions + elicitation of user input). Atlas plan mode can copy the "mode presets" abstraction rather than a hardcoded branch.
4. **unified_exec** session terminals (`exec_command` + `write_stdin` + `/ps` `/stop`, stdin approvals, shell snapshots) remain the reference for Atlas's terminal tool; note the exec-server broker with bearer-token WebSockets as the enforcement point for approvals.
5. **Review mode** is a first-class slash command with inline args; plus the new **side conversations** (`/side`, `/btw` ephemeral forks) — a lightweight pattern for "quick question without polluting the main thread".
6. **Subagents**: AgentControl + roles + message board + per-session subagent switching (`/subagents`) + agent command center UI (`/agents`) with task lifecycle (hide/archive/delete, older-task paging). Atlas's equivalents can mirror the task/worktree coupling (worktrees on by default, ownership shown).
7. **Compaction v2** moved to a remote/server-assisted summarization with image budgets; local checkpoints + resume metadata in the `history` crate are the fallback. `/recap` as a user-invoked summary is cheap parity.
8. **Skills**: SKILL.md + progressive disclosure is now table stakes; differentiators to note are cloud-synced skill listings with budget+dedupe (0.160.0) and bundled sample skills (openai-docs) that Codex uses to self-migrate models.
9. **Models**: family is now GPT-6 (Astra flagship / Terra balanced / Luna fast) + `gpt-6.1-sol`; GPT-5.x being retired from catalogs with migration prompts. Migration-prompt UX (auto-offered when a removed model is configured) is a parity feature. "Daybreak" = cyber-access program (blue/red treatments), surfaced as a TUI toggle.
10. **Ops shape**: background daemon (auto-start, self-update), SQLite state with numbered migrations, plugin manifest caching, OTLP logging of responses and Guardian assessments, `/doctor` — all operational surfaces Atlas could benchmark against.
11. **Docs policy change**: repo docs are now stubs pointing to developers.openai.com (which blocks plain fetchers); pin content from release notes + source when citing Codex behavior going forward.
