# Claude Code source freeze — 2026-10-03

Sources: npm registry (https://registry.npmjs.org/@anthropic-ai/claude-code), GitHub releases (https://github.com/anthropics/claude-code/releases, fetched via `gh api`), CHANGELOG.md (https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md, 880 KB / ~8.2k lines), https://github.com/anthropics/skills, https://agentskills.io (+ /specification).

## Version freeze

- **Package:** `@anthropic-ai/claude-code`
- **`latest`: 2.1.288** — published **2026-10-02T18:30Z** (GitHub release v2.1.288, 2026-10-02T20:19Z)
- **`stable`: 2.1.285** — published 2026-09-29; `next`: 2.1.288
- Release cadence: roughly one release per day (44 releases between 2026-08-17 and 2026-10-02: v2.1.234 → v2.1.288). Bug-fix-only releases say "Bug fixes and reliability improvements" (e.g. v2.1.240, 241, 250, 252).
- Repo: ~149k stars; npm `bin: claude`, Node >=18, no runtime deps (optional `@img/sharp-*`); repo URL still points at `claude-cli-internal.git`.
- Recent npm publish dates: 2.1.288 = 2026-10-02, 2.1.287 = 2026-10-01, 2.1.286 = 09-30, 2.1.285 = 09-29, 2.1.284 = 09-28, 2.1.283 = 09-25, 2.1.282 = 09-24, 2.1.281 = 09-23, 2.1.280 = 09-22, 2.1.278 = 09-19, 2.1.277 = 09-18, 2.1.270 = 09-12, 2.1.257 = 09-01, 2.1.251 = 08-28.

## Recent capability changes (last 6 weeks: ~2026-08-22 → 2026-10-03, v2.1.240 → v2.1.288)

All bullets are quoted/condensed from the GitHub release notes for the named version.

### 1. Claude Mods — the headline new extensibility mechanism (v2.1.287, Oct 1)
- **"Added Claude Mods: plugins may now modify deeper behavior"** — a new layer above plugins that can alter harness behavior itself, not just add tools/commands. (Also teased in an HN thread on 2026-09-18.)
- Built-in mod **"You should know"**: a side agent "watches your back and flags things you or Claude might miss"; enable via `/plugin enable cc-plugin-you-should-know@builtin`. Notes are phrased "we"/"the main agent"/"you" depending on who made a decision (2.1.288).
- Mod API: `$.ui.selection()` returns the text last selected in fullscreen mode plus the transcript row (v2.1.288); mods can draw buttons above the prompt; `claude plugin test` is mod-aware (2.1.288).
- Why copy: this is Claude Code's answer to "harness-as-a-platform" — third parties reskinning/reteaching the harness without forking.

### 2. Model lineup refresh (three new default models in 3 weeks)
- **Claude Sonnet 5.5** (`claude-sonnet-5-5`) becomes default Sonnet — 1M context, $2/$10 per Mtok, $0.20/Mtok cache reads (v2.1.284, Sep 28).
- **Claude Opus 5.5** (`claude-opus-5-5`) becomes default Opus — 1M context, $4/$20 per Mtok (v2.1.280, Sep 22). Default model on **Pro and Team Standard plans switched from Sonnet to Opus** (v2.1.280); Enterprise seat-based default moved to Opus 5 (v2.1.251).
- **Claude Fable 5.1** (`claude-fable-5-1`) becomes default Fable — 1M context, $10/$50 per Mtok (v2.1.257, Sep 1).
- **1M context becomes the default everywhere**: Opus 4.7+/Fable use 1M on Bedrock/Vertex/Foundry/gateways without the `[1m]` suffix (`CLAUDE_CODE_DISABLE_1M_CONTEXT=1` keeps 200K) (v2.1.287); sessions behind custom `ANTHROPIC_BASE_URL` also get 1M (v2.1.285).
- Effort system: `/effort` saved **per model** (v2.1.251); Ultracode is now its own toggle in `/effort` that no longer forces xhigh effort (v2.1.284); `maxEffortLevel` setting caps effort per model (v2.1.267).

### 3. "Auto mode" — LLM-classifier permission mode becomes the default
- Interactive terminal and VS Code sessions **start in auto mode by default on every plan and provider** (v2.1.284); headless `-p`/SDK and third-party-provider sessions follow (v2.1.283, v2.1.285). `permissions.defaultMode` still overrides.
- **Server-side classifier** becomes default for Claude API/Enterprise and Bedrock/Vertex/Foundry/gateways — no billed classifier overhead (`CLAUDE_CODE_AUTO_MODE_SERVER=0` opts out) (v2.1.278, extended v2.1.282); billing doc: https://code.claude.com/docs/en/auto-mode-classifier-billing
- **Per-command `allowed_domains`** in auto mode with sandboxing: the hosts a command needs are reviewed and opened for that command alone (v2.1.271).
- Auto mode grows rules: "Containment Escape" rule blocks cloud metadata-credential fetches / egress evasion / cross-tenant reach (v2.1.257); one-time prompt before first read outside working dirs + `permissions.blockReadsOutsideWorkingDirectories` (v2.1.257, "ask again next time" option v2.1.284); classifier conversation auto-compacts instead of failing when too long (v2.1.288).
- UX: **Auto mode tab in `/permissions`** for viewing/editing classifier rules (v2.1.246); `/insights` estimates how many prompts auto mode would have handled (v2.1.281); stacked permission prompts show "2 of 5" counts (v2.1.286); dangerous `rm` prompts time out after 2 min and deny with a rewrite hint so unattended sessions keep going (v2.1.281).
- Related safety mode: **`--restricted`** removes all code-executing tools and WebFetch, refuses bypassPermissions, ignores user/project/local settings (v2.1.248).

### 4. AGENTS.md support (v2.1.277, Sep 18)
- "In a project with no CLAUDE.md, Claude Code reads **AGENTS.md** instead; change it under 'Project instructions' in `/config`" (not yet on Bedrock/Vertex/Foundry at ship). Cross-tool instructions standard adopted.

### 5. Agent teams / subagents (hardening window; teams shipped earlier)
- Agent teams (multi-teammate sessions with mailboxes, idle notifications, agents view) were stabilized across the whole window (many `Fixed agent teams:` entries — teammate final answers reaching the lead via idle notification, transcript eviction during retries, tmux pane cleanup).
- **Subagent-output framing as prompt-injection defense**: subagent results reach the main agent under a header marking them as subagent output, indented, "so text in a subagent's result cannot pass as the session's own instructions" (v2.1.277); workflow `agent()` prompts framed as script-authored text (v2.1.277).
- Agent frontmatter additions: `omitClaudeMd` (run subagents without CLAUDE.md files) (v2.1.271); `experimental.cacheTtl` ("5m"/"1h") per-agent prompt-cache TTL (v2.1.248).
- Model routing: `CLAUDE_CODE_SUBAGENT_MODEL` becomes a *default* that agent definitions and per-spawn models override (v2.1.251); `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` overrides everything (v2.1.257).
- Cross-session messaging (`SendMessage` / `ListAgents`) extended to Bedrock/Vertex/Foundry and telemetry-off (v2.1.248); peer messages collapse to one-line previews (v2.1.247); background sessions manageable via `claude attach/logs/stop/respawn/rm` (v2.1.251).
- Subagents in auto mode end their run as soon as they hand back their report (v2.1.285).

### 6. Hooks
- **New `PreModelSwitch` and `PostModelSwitch` hook events** — block, confirm, or annotate a model switch; `SessionStart` resume hooks now receive session staleness + estimated re-cache cost (v2.1.251).
- `PermissionRequest` hooks restricted to command/http types (agent hooks can't answer) (v2.1.280); PreToolUse/PermissionRequest no longer silently skipped on serialization failures (v2.1.288); hook output sizes added to OTel `hook_execution_complete` (v2.1.280).

### 7. Plugins & marketplace format
- `claude plugin eval`: run a plugin's eval suite against Claude Code, get scored reproducible results (JSON + HTML report) (v2.1.269; requires git 2.31+ per v2.1.283).
- Supply-chain hardening: plugin installs **refuse npm sources that are git repos or folders** and install deps only from registry packages (v2.1.286); `--accept-command <sha256>` to accept exactly the displayed install command instead of `-y` (v2.1.271); marketplaces imitating reserved names refused (v2.1.280); git-URL validation (v2.1.285).
- Lifecycle: `claude plugin configure <plugin>` shows/saves plugin options, incl. stdin values (v2.1.285); `<server>.<key>=<value>` config for bundled `.mcpb` MCP servers at install time (v2.1.285); `--json` on install/uninstall/update/enable/disable (v2.1.268); `--plugin-dir` accepts a folder of plugins with live add/remove (v2.1.265); `claude plugin validate` checks `.mcp.json` entries, undeclared `${user_config.*}` refs, insecure URLs (v2.1.281).
- Attribution: `"attribution": false` setting hides all commit/PR attribution (v2.1.281).

### 8. Skills
- **`/skill-doctor`**: shows which loaded skills go unused and what they cost in context (v2.1.261).
- **`verify` skill convention**: if the project/user defines a skill named `verify`, Claude is told to run it right before committing (docs-only/tests-only excepted) (v2.1.286).
- Namespace reservation: `anthropic-skills` / `claude-ai` namespaces are reserved for claude.ai-synced skills; local skills/plugins/MCP servers under those names no longer load or list (v2.1.282); `Skill(...)` allow/deny rules matched against alias and display name (v2.1.283).
- `/skill <name>` typed mid-message now tells Claude it's a skill, incl. `disable-model-invocation` ones (v2.1.287).

### 9. MCP
- **URL elicitation**: servers on the 2026-07-28 protocol can launch browser-based flows (v2.1.281); URL prompts on the 2025-11-25 protocol with `bareElicitationCapability` config (v2.1.287); completion handshake ("I'm done, continue") for servers that can't report completion (v2.1.288).
- **Mid-call OAuth re-auth prompt** when a server asks for more scope during a tool call (v2.1.288).
- **Tool search / deferred loading**: `alwaysLoad: false` now defers an entire server's tools behind tool search (v2.1.287); per-tool `_meta['anthropic/alwaysLoad']` respected (v2.1.285).
- `/mcp reconnect all` retries every failed server at once (v2.1.284); `CLAUDE_CODE_MAX_MCP_DESCRIPTION_LENGTH` (default 2,048 chars) (v2.1.280); `CLAUDE_CODE_MCP_STARTUP_WAIT_MS` bounds first-turn startup wait (v2.1.274); org-wide `managedMcpServers` managed setting (HTTP/SSE only) (v2.1.259); large tool results: less memory, smaller session files, no extra token-count upload (v2.1.287).

### 10. Context management / compaction / prompt cache
- `/autocompact` window saved **per model** (v2.1.288); Sonnet 5's default auto-compact window extended to full 1M (~967K tokens) (v2.1.247); notices say when a fallback dropped 1M→200K (v2.1.286); "Prompt is too long" failure when usage was zero now auto-compacts (v2.1.288).
- **Prompt-cache telemetry**: `/cost` gains a per-session cache line (hit ratio, misses, tokens re-cached, warm/cold) + `prompt_cache` status-line object (v2.1.251), plus **likely-cause diagnosis** for misses (tool defs/system prompt changed, TTL idle) (v2.1.260).
- Inline output budgets: `bashOutputMaxChars` / `taskOutputMaxChars` up to 128K chars before spilling to a file (v2.1.261); 1 GB cap on tool results saved to disk (v2.1.265).

### 11. Background tasks & sessions
- **Background command time limit**: default 30 min, max 2 h — but as of v2.1.288 it applies **only to unattended sessions** (`-p`, SDK, CI, cloud); terminal/desktop/VS Code sessions have no limit (v2.1.285 → v2.1.288).
- Send-now (ctrl+enter) **moves running tools to the background instead of cancelling the turn** (v2.1.281, refined v2.1.286); `/tasks` folds Claude's own background work under a "System tasks" row (v2.1.285); `--resume` on a session running in the background now attaches to it (v2.1.285); Ctrl+C-cleared prompts recoverable with Up (v2.1.288).

### 12. Memory
- Auto-memory hardening: invisible characters / Claude-Code-markup imitation neutralized in `MEMORY.md` and recalled notes before reaching the model (v2.1.284); auto-memory can no longer be *enabled* from background or child-tool sessions (v2.1.285); VS Code gains a Memory dialog (view/edit/delete saved memories) and Memory/Instructions entries in the Customize menu ([VSCode] entries, ~v2.1.279–286).

### 13. New tools & slash commands
- `SendFeedback` tool — Claude drafts a bug report for review in `/feedback` (v2.1.247); **`/doctor prompt-audit`** — audits CLAUDE.md/skills/agents/commands for prompting patterns written for older models (v2.1.283); `/claude-api cost-optimize` — profiles API spend and works through cost levers (v2.1.247); `/diff` — fullscreen side diff panel of uncommitted changes (v2.1.260); `/output-style [name]` incl. headless (v2.1.269); Bash-edit diff shown in Bash tool results (`bashEditDiffEnabled`) (v2.1.269); `/code-review --max-findings <n>|all` (v2.1.288); `/advisor` text form for headless (v2.1.260); `claude --desktop` opens the Claude desktop app on the current dir (v2.1.285); GitLab `glab mr` recognition with MR badges (v2.1.259); `Workflow` tool concurrency raised to 1–256 via `CLAUDE_CODE_WORKFLOW_MAX_CONCURRENT_AGENTS` (v2.1.269); `CLAUDE_CODE_DISABLE_WEB_FETCH` kills WebFetch (v2.1.285); `--bare` tightened to named MCP servers only, no system reminders, no background tasks (v2.1.286).

## Agent Skills ecosystem (brief)

- **anthropics/skills** (https://github.com/anthropics/skills): ~179k stars, 21.2k forks, 57 commits on `main`. Layout: `skills/` (example skills in 4 categories), `spec/`, `template/`, `.claude-plugin/` marketplace config. Installable as two Claude Code plugins: `document-skills` and `example-skills` via `/plugin marketplace add anthropics/skills`. Apache-2.0 except docx/pdf/pptx/xlsx (source-available references).
- **agentskills.io** is the open-standard home (originated by Anthropic, now open to contributions; spec discussion at https://github.com/agentskills/agentskills with a `skills-ref` validator: `skills-ref validate ./my-skill`).
- Spec (https://agentskills.io/specification): SKILL.md with required `name` (≤64 chars, lowercase/hyphens, must match dir name) + `description` (≤1024 chars); optional `license`, `compatibility` (≤500 chars), `metadata` (string→string map), `allowed-tools` (space-separated pre-approved tools, marked **Experimental**). Progressive disclosure: metadata (~100 tokens) → instructions (<5k tokens, <500 lines recommended) → resources on demand. Optional `scripts/`, `references/`, `assets/` dirs.
- Adoption is very broad (agentskills.io client showcase): Gemini CLI, GitHub Copilot/VS Code, Cursor, OpenAI Codex, OpenCode, Amp, Goose, OpenHands, Roo Code, Factory, Kiro, Tabnine, Letta, Spring AI, Databricks, Snowflake, Mistral Vibe, etc. — the de facto portable skill format.
- No breaking marketplace-format change found in the 6-week window; the notable marketplace-side changes are the supply-chain hardening and lifecycle additions listed in §7, plus reserved skill namespaces (§8).

## Notes for Atlas parity mapping

Highest-value items for a competitor harness to copy (feature → changelog anchor):

1. **Claude Mods (v2.1.287)** — a second extensibility layer that lets packages modify harness behavior itself (UI hooks like `$.ui.selection()`, watchdog side-agents like "You should know"). Atlas's plugin/skill story currently stops at tools+prompts; a "mods" layer that can intercept UI and internal behavior is the new differentiator.
2. **Auto mode as default permission mode (v2.1.278/282/283/284)** — an LLM classifier that approves/denies tool calls instead of static rules, default-on everywhere, with server-side classification to avoid billed overhead, `/permissions` tab for classifier rules (v2.1.246), per-command network `allowed_domains` (v2.1.271), and unattended-session deny-timeouts for dangerous ops (v2.1.281). This replaces "click yes 50 times" UX.
3. **AGENTS.md fallback (v2.1.277)** — trivial to add, big interop win: read AGENTS.md when no Atlas-specific instructions file exists.
4. **Subagent output framing (v2.1.277)** — mark subagent results with an unforgeable header + indent so subagent text can't impersonate user/system instructions. Cheap prompt-injection defense worth mirroring.
5. **Prompt-cache observability (v2.1.251/260)** — per-session hit ratio + miss-cause diagnosis in `/cost` and the status line. Atlas has no cache telemetry; this is high-value and easy.
6. **Hooks: PreModelSwitch/PostModelSwitch (v2.1.251)** — guardrails around model switching (cost/policy), plus per-agent `cacheTtl` (v2.1.248) and `omitClaudeMd` (v2.1.271) agent frontmatter fields.
7. **`verify` skill convention (v2.1.286)** — if a skill named `verify` exists, run it before every commit. A one-line convention with outsized reliability payoff.
8. **`/skill-doctor` (v2.1.261) and `/doctor prompt-audit` (v2.1.283)** — hygiene tooling: measure unused-skill context cost; audit instruction files for stale prompting patterns. Atlas should copy both as diagnostics.
9. **Background-task ergonomics** — send-now backgrounds the running tool instead of cancelling (v2.1.281/286); attach/stop/respawn for background sessions (v2.1.251); time limits only in unattended sessions (v2.1.288).
10. **Plugin supply-chain hardening (v2.1.271/286)** — registry-only dependencies, sha256-pinned install commands, reserved namespaces, `plugin eval` scored test harness (v2.1.269). Atlas plugins should adopt the same trust model early.
11. **MCP deferred tool-loading via `alwaysLoad:false` / tool search (v2.1.285/287)** and `MAX_MCP_DESCRIPTION_LENGTH` — context-cost controls for MCP that Atlas will need as its MCP surface grows.
12. **Skills spec conformance** — Atlas skills should emit the agentskills.io frontmatter (`name`, `description`, optional `compatibility`/`metadata`/`allowed-tools`) so they are portable to the ~40-client ecosystem; note `allowed-tools` is still experimental.

Version-freeze anchor for benchmarking: pin `@anthropic-ai/claude-code@2.1.288` (2026-10-02); `stable` channel lags at 2.1.285 (2026-09-29).
