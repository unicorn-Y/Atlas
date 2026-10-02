# Skills Hubs / Agent Skills Ecosystem — Source Freeze 2026-10-03

Scope: marketplaces and registries for Agent Skills (SKILL.md format), as of 2026-10-03.
Method: direct fetch of skills.sh, clawhub.ai, agentskills.io, code.claude.com docs; GitHub API for
NousResearch/hermes-agent (main @ 2026-10-02), anthropics/skills, agentskills/agentskills,
vercel-labs/skills, anthropics/claude-code CHANGELOG (v2.1.288 current). All URLs live unless noted.

---

## 1. skills.sh (Vercel) — LIVE, largest catalog

- Site: https://skills.sh — "The Open Agent Skills Ecosystem". Made by Vercel.
- OSS CLI/repo: https://github.com/vercel-labs/skills ("The open agent skills tool - npx skills",
  32,985 stars, default branch main, pushed 2026-10-02, homepage skills.sh). Verified alive.
- Install UX: `npx skills add <owner/repo>` (+ optional `--skill <name>`). Skills are plain GitHub
  repos; skills.sh is a discovery/leaderboard layer. Claims 20 supported agent targets: Claude Code,
  Cursor, Codex, GitHub Copilot, Windsurf, Gemini, Cline, AMP, Antigravity, OpenClaw, Droid, Goose,
  Kilo, Kiro CLI, Nous Research, OpenCode, Roo, Trae, VS Code, Zed.
- Scale (rendered 2026-10-03): leaderboard tab "All Time (1,548,384)"; top entries: find-skills
  (vercel-labs/skills) 3.7M installs; mattpocock/skills 4.4M total; microsoft/azure-skills 8.6M
  total; open.feishu.cn 14.1M total. Hermes' adapter (main, 2026-10) states the homepage exposes
  only a ~200-entry featured strip and the real catalog is sitemap-skills-N.xml files (10k URLs
  each) covering "the full ~20k+ catalog".
- Install counts come from anonymous CLI telemetry ("only tracks which skills are being installed").
- Badge endpoint: `https://skills.sh/b/owner/repo` (e.g. https://skills.sh/b/anthropics/skills).
- Packs: bundle public+private skills behind one shareable install command (https://skills.sh/docs/packs).
- Security: routine audits + partner audits surfaced at /api/v1/skills/audit/*; reports to security.vercel.com.

### API v1 (https://skills.sh/docs/api, fetched 2026-10-03)
Base `https://skills.sh`, JSON, auth via Vercel OIDC bearer (`Authorization: Bearer` or
`x-vercel-oidc-token`); rate limit 600 req/min per (team, project); 429 carries Retry-After.
- `GET /api/v1/skills` — paginated leaderboard. `view=all-time|trending|hot` (default all-time),
  `page` (0-based), `per_page` 1–500 (default 100). `hot` adds `installsYesterday` + `change`.
- `GET /api/v1/skills/search` — `q` (min 2 chars; single word = fuzzy, multi-word = semantic),
  `limit` 1–200 (default 50), optional `owner` filter. Response has `searchType` fuzzy|semantic.
- `GET /api/v1/skills/curated` — first-party/official set (same data as skills.sh/official).
- `GET /api/v1/skills/{source}/{skill}` — detail by `id`=`{source}/{slug}` (works for GitHub ids
  like `vercel-labs/skills/find-skills` and well-known ids like `mintlify.com/mintlify`). Returns
  `id, source, slug, installs, hash` (SHA-256, null if no snapshot), `files[{path, contents}]`
  (full file snapshot — useful: you can fetch skill content directly, no GitHub round-trip).
- `GET /api/v1/skills/audit/{source}/{skill}` — partner audits (Gen Agent Trust Hub, Socket, Snyk,
  Runlayer, ZeroLeaks); `status` pass|warn|fail, `riskLevel` NONE|LOW|MEDIUM|HIGH|CRITICAL; 404 if unaudited.
- Skill object: `id, slug, name, source, installs, sourceType` (github|well-known), `installUrl, url, isDuplicate`.
- Cache: leaderboard/search 30–60s; detail/curated 5 min.
- Note: Hermes' adapter uses the older `https://skills.sh/api/search` endpoint plus sitemap walking
  (requests gzip-only because skills.sh serves per-skill sitemaps brotli-compressed).

---

## 2. ClawHub — LIVE at clawhub.ai (clawhub.com redirects)

- https://clawhub.com returns **307 → https://clawhub.ai/** (verified 2026-10-03). Use clawhub.ai.
- Registry for OpenClaw agent skills + plugins, run by the "OpenClaw Foundation". Site touts signed
  manifests, moderated releases, version history. Infra: Vercel + Convex.
- CLI: npm package `clawhub` — latest **0.23.3, published 2026-08-04**, description "ClawHub CLI —
  install, update, search, and publish skills plus OpenClaw packages"; `bin: clawhub` (legacy alias
  `clawdhub`). Site shows: `npm i -g clawhub`, `clawhub login`,
  `clawhub skill publish ./my-skill --slug my-skill --version 1.0.0`,
  `clawhub package publish your-org/your-plugin`.
- REST API (as exercised by Hermes' `tools/skills_hub_clawhub.py`, main @ 2026-10-02):
  base `https://clawhub.ai/api/v1`
  - `GET /skills?search=<q>&limit=<n>` — search (client-side re-scoring in Hermes).
  - `GET /skills` — full catalog walk (Hermes notes "50k+ skills", sequential pagination, caps the
    walk at a 12-second budget).
  - `GET /skills/{slug}` — detail; `GET /skills/{slug}/versions` and `/versions/{version}`.
  - `POST /download` — ZIP bundle download (Hermes caps at 25 MB, streams in 64 KB chunks).
  - File entries carry `rawUrl` / `downloadUrl` / `url` for per-file fetch fallback.
- Scale: 50k+ skills (per Hermes code comment). Homepage footer shows decorative "30 skills 12
  plugins" (template filler — do not trust); featured plugins: Memory LanceDB 14.4k downloads,
  DuckDuckGo 9.9k, Lobster 9.8k, Diagnostics Prometheus 8.9k.
- Security reputation: the **ClawHavoc incident — 341 malicious skills, Feb 2026** (quoted verbatim
  in Hermes' adapter: "Every skill is community trust — the ClawHavoc incident (341 malicious
  skills, Feb 2026) showed their vetting is insufficient"). Treat ClawHub as unvetted upstream.

---

## 3. Hermes Skills Hub (NousResearch/hermes-agent)

- Repo: https://github.com/NousResearch/hermes-agent — MIT, 250,753 stars, branch main, pushed
  2026-10-02; latest tag **v2026.9.24** (then v2026.9.21, v2026.9.14); last commit 2026-10-02.
- `tools/skills_hub*.py` confirmed on main: `skills_hub.py`, `skills_hub_models.py`,
  `skills_hub_sources.py`, `skills_hub_skillssh.py`, `skills_hub_clawhub.py`,
  `skills_hub_github.py`, `skills_hub_official.py`, `skills_hub_search.py`, `skills_hub_install.py`.
- Federates **8 source adapters** (docs: https://hermes-agent.nousresearch.com/docs/user-guide/features/skills):
  | Source | ID | Mechanism |
  |---|---|---|
  | Official optional skills | `official` | repo `optional-skills/` dir (Nous-maintained, not default-enabled) |
  | skills.sh | `skills-sh` | discovery via skills.sh (legacy `/api/search` + sitemap walk); content via underlying GitHub repo |
  | Well-known | `well-known` | any domain serving `/.well-known/skills/index.json` |
  | GitHub | `github` | repos/"taps"; default taps: openai, anthropics, huggingface, NVIDIA, garrytan/gstack, K-Dense-AI, synthetic-sciences (~480 science skills) |
  | ClawHub | `clawhub` | clawhub.ai `/api/v1` (all results = community trust) |
  | LobeHub | `lobehub` | `https://chat-agents.lobehub.com/index.json` → `{agent_id}.json`, agents converted to skills |
  | browse.sh | `browse-sh` | `https://browse.sh/api/skills` (+ `/api/skills/{slug}`); Browserbase's 200+ site-automation skills, ids like `browse-sh/airbnb.com/<task-id>` |
  | Direct URL | `url` | any HTTP(S) SKILL.md + referenced support files |
- Identifier prefixes: `official/`, `skills-sh/`, `github/`, `clawhub/` (+ typo aliases "skils-sh/",
  "skils.sh/"); well-known ids wrap `{base_url}/{skill}`.
- Trust levels: `builtin` (ships with Hermes) / `official` (optional-skills/) / `trusted`
  (openai/skills, anthropics/skills, huggingface/skills, NVIDIA/skills) / `community` (everything else).
- Install: `hermes skills browse|search|inspect|install|list|check|update|audit|uninstall|reset|publish|snapshot|tap`;
  chat `/skills ...`; desktop deep link `hermes://skill/install?identifier=...`. Only SKILL.md +
  referenced dirs (references/, templates/, scripts/, assets/, examples/) are copied; provenance +
  content hashes in `~/.hermes/skills/.hub/lock.json`; updates detect upstream drift, skip locally
  edited skills unless `--force`. Auto security scan on install (exfiltration, prompt injection,
  destructive commands, supply-chain); optional NVIDIA SkillEvaluator v0.1.0 / SkillSpector v2.9.5
  advisory scans; "`--force` does not override a dangerous scan verdict". Custom taps = any GitHub
  repo with a `skills/` dir (via `taps.json`). GitHub API 60 req/h unauthenticated; GITHUB_TOKEN for 5k/h.

---

## 4. anthropics/skills + Agent Skills spec (agentskills.io)

- Repo: https://github.com/anthropics/skills — 179,406 stars, 21.2k forks, pushed 2026-09-29.
  Layout: `skills/` (Creative & Design, Development & Technical, Enterprise & Communication,
  Document Skills: docx/pdf/pptx/xlsx — the document skills are source-available, NOT open source;
  the rest Apache-2.0), `spec/` (Agent Skills spec), `template/`, and `.claude-plugin/` so the repo
  itself is a Claude Code plugin marketplace (`/plugin marketplace add anthropics/skills`).
- Recent commits are content-only (no format changes): 2026-09-29 claude-api skill → Claude Opus
  5.5 default / Sonnet 5.5; 2026-09-10 Managed Agents `auto` permission policy; 2026-09-03
  frontend-design update; 2026-08-18 rename claude-academy-guide → academy-guide; 2026-08-17
  add discernment-nudge skill.
- Spec site: https://agentskills.io — LIVE. "The Agent Skills format was originally developed by
  Anthropic, released as an open standard." Spec repo: https://github.com/agentskills/agentskills
  (25,859 stars; pushed 2026-08-09; last commits: 2026-08-09 "add OpenClaw / Hermes Agent to client
  showcase", 2026-08-03 "Clarify `metadata` in the frontmatter overview"). Reference validator:
  `skills-ref validate ./my-skill` (skills-ref library in that repo). Also Discord + llms.txt index.
- SKILL.md spec (https://agentskills.io/specification, fetched 2026-10-03):
  - Required: `name` (1–64 chars; `a-z0-9-` only; no leading/trailing/consecutive hyphens; MUST
    match parent directory name), `description` (1–1024 chars; what + when).
  - Optional: `license`; `compatibility` (≤500 chars, only if env requirements);
    `metadata` (free-form map string→string); `allowed-tools` (space-separated pre-approved tools,
    e.g. `allowed-tools: Bash(git:*) Bash(jq:*) Read` — marked **Experimental**, support varies).
  - Body: markdown instructions, <5000 tokens / <500 lines recommended; split detail into files.
  - Progressive disclosure: 1) metadata (~100 tokens, loaded at startup for all skills), 2) full
    SKILL.md on activation, 3) `scripts/` `references/` `assets/` on demand. Relative file refs,
    one level deep. No spec version number is published on the site.

---

## 5. Claude Code plugin format (`.claude-plugin`, marketplace.json, mcpb)

Docs: https://code.claude.com/docs/en/plugins-reference + /plugin-marketplaces (fetched 2026-10-03;
current CC version 2.1.288).

- `plugin.json` (at `.claude-plugin/plugin.json`): only required field is `name` (kebab-case;
  Anthropic-reserved names rejected). Other fields: `displayName, version, description, author,
  homepage, repository, license (SPDX), keywords, metadata` (v2.1.222+), directory-listing fields
  (`icon, documentationUrl, supportUrl, privacyPolicyUrl, termsOfServiceUrl`), `defaultEnabled`,
  `dependencies`, `settings` (only `agent`, `subagentStatusLine` effective), `userConfig`
  (`options` picker v2.1.271+), `types`, `channels`, component keys `skills, commands, agents,
  hooks, mcpServers, lspServers, outputStyles, workflows` + `experimental` (`themes, monitors, evals`).
  Component defaults: `skills` ADDS to default `skills/<name>/SKILL.md`; commands/agents/outputStyles/
  workflows/themes/monitors REPLACE defaults; hooks/mcpServers/lspServers MERGE. A root-level
  SKILL.md makes the whole plugin a single skill. Env: `${CLAUDE_PLUGIN_ROOT}`, `${CLAUDE_PLUGIN_DATA}`,
  `${CLAUDE_PROJECT_DIR}`, `${user_config.KEY}` / `CLAUDE_PLUGIN_OPTION_<KEY>`.
- **mcpb**: `mcpServers` accepts bundle URLs (`"https://example.com/server.mcpb"`); `.mcpb` or `.dxt`
  extract to `.mcpb-cache/` under the plugin root. v2.1.285 added
  `claude plugin install --config <server>.<key>=<value>` to configure a bundled `.mcpb` server at
  install time.
- `marketplace.json` (at `.claude-plugin/marketplace.json`): required `name`, `owner` (object with
  `name`), `plugins[]`. Entry: `name` (must equal the plugin manifest's `name`), `source` (relative
  path | `{source:"github", repo}` | `{source:"git-subdir", url, path}` | `url` | `archive` (zip) |
  `npm` | `command`; git sources pinnable to `ref`/`sha`), `strict` defaults true. Reserved names
  (e.g. `claude-plugins-official`) validate but are refused on add; look-alike reserved names refused
  since 2.1.280. `metadata.pluginRoot` resolves bare source names (fixed 2.1.239). `headersHelper`
  (2.1.238) mints HTTP headers for url-marketplace catalog/archive fetches. Entry display metadata
  overrides manifest since 2.1.265. Commands: `claude plugin marketplace add <owner>/<repo>|<url>|<path>`,
  `claude plugin install <name>@<marketplace>`, `claude plugin validate`, in-session `/plugin ...`.

### Format/behavior changes, last ~6 weeks (CC ≈ v2.1.236–2.1.288; anchor: 2.1.238 ships the
Managed Agents Aug 19 release, so the window ≈ 2026-08-19 → 2026-10-03):
- **2.1.287**: "Claude Mods" — plugins may now modify deeper behavior (first builtin mod "You should know").
- 2.1.285: `--config` for bundled `.mcpb` servers; stricter git-URL validation for plugins/marketplaces.
- 2.1.284: plugins from marketplaces/claude.ai/npm can no longer self-pre-approve tools via
  `allowed-tools` under managed `allowManagedPermissionRulesOnly` (official Anthropic sources exempt).
- 2.1.283: containment checks for outputStyles/lspServers/monitors/themes paths; `/doctor prompt-audit`;
  reverted 2.1.282's reservation of the `claude-ai` skill name (partial rollback churn).
- 2.1.282: `anthropic-skills` / `claude-ai` namespaces reserved for claude.ai-synced skills
  (skill folders, workflow commands, MCP servers under those names stop listing skills/prompts).
- 2.1.281: MCP validation checks + directory-listing fields accepted without warning (docs version note);
  claude.ai-synced skills surfaced by short name.
- 2.1.275: **claude.ai account skills/plugins sync into terminal sessions** (`syncClaudeAiSkills: false`
  / `syncClaudeAiPlugins: false` opt-outs); `/plugin install <plugin> --marketplace <source>`.
- 2.1.274: plugin/marketplace clones leave Git LFS files as pointers.
- 2.1.271: skills'/slash commands' inline `!` shell commands follow default-mode permission rules
  (no longer classifier-bypassed).
- 2.1.269/2.1.265: claude.ai-synced skills named `anthropic-skills:<name>`; `effort:` frontmatter
  honored on skills/commands/subagents; marketplace entry metadata preferred for display.
- 2.1.261: `/skill-doctor` — shows unused skills + their context cost.
- 2.1.257: symlink escapes via declared component paths refused; 2.1.251: marketplace entry command
  path-traversal rejected; 2.1.247: marketplace names with control/invisible chars rejected.
- 2.1.239: UTF-8-BOM .md (agents/skills/commands) silently ignored — fixed; `metadata.pluginRoot` fixed.

---

## Notes for Atlas X4

1. **Canonical format**: agentskills.io SKILL.md spec — `name`+`description` required, `metadata`
   map, `allowed-tools` experimental. Validate with `skills-ref`. `name` must equal the directory
   name — enforce on Atlas-side publishing.
2. **Federation blueprint** = Hermes' 8 adapters: official(bundled) / skills.sh / clawhub / github
   taps / well-known / lobehub / browse.sh / direct URL. Hermes' trust model (builtin > official >
   trusted-list > community) + auto security scan + content-hash lockfile is the pattern to copy.
3. **skills.sh is the best-programmatic source**: read-only API v1 (search fuzzy/semantic, leaderboard,
   curated, detail with **full file snapshots** keyed by SHA-256 `hash`, partner audit results with
   riskLevel). 600 req/min with a Vercel OIDC token. No publish API documented — publishing = having
   a GitHub repo and being installed via `npx skills add`.
4. **ClawHub**: simple REST (`/api/v1/skills?search=`, `/skills/{slug}`, `/versions`, `/download` ZIP)
   and huge (50k+), but treat as untrusted post-ClawHavoc (341 malicious skills, Feb 2026): scan
   everything, label community, pin versions. Note clawhub.com → clawhub.ai redirect.
5. **Self-host discovery convention worth adopting**: serve `/.well-known/skills/index.json` for
   Atlas-published skills (Hermes + skills.sh "well-known" sourceType both consume it).
6. **Claude Code plugin format is a superset of skills** (root SKILL.md ⇒ whole plugin is one skill);
   mcpb bundles are first-class in `mcpServers`. If Atlas ships a Claude Code-compatible marketplace,
   follow `.claude-plugin/marketplace.json` (`name/owner/plugins[]`, `source` types incl. npm/archive)
   and the strict path-containment/symlink rules added in Aug–Sep 2026.
7. **Expected UX verbs** users will bring from other hubs: `npx skills add owner/repo --skill X`,
   `clawhub skill publish`, `claude plugin marketplace add owner/repo` + `/plugin install name@marketplace`,
   `hermes skills install <id>`.
