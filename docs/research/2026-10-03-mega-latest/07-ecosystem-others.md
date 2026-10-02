# 07 — Ecosystem: Other Agent Harnesses (source freeze 2026-10-03)

Scope: Factory droid, Cline, Kiro, Roo Code, goose, Gemini CLI, Amp, OpenHands, Google Antigravity + new-harness scan. Versions/dates verified against GitHub Releases API, docs.factory.com changelog, kiro.dev changelog, ampcode.com/news, HN Algolia, and Web search on 2026-10-03 (UTC+8; some items dated Oct 2 local).

## 1. Factory (factory.ai / droid CLI)
- Latest: **CLI v0.232.0 / Desktop v0.189.0 — 2026-10-02** (CLI v0.231.0 Oct 1, v0.230.0 Sep 30; 233 releases total). Closed source; changelog: https://docs.factory.com/changelog/cli (docs.factory.ai 308-redirects to docs.factory.com).
- Harness notes: `/compress` summarizes current session and `/handoff` starts a "summary-only successor" (Sep 26); interrupted mid-stream replies are discarded instead of finishing tool calls; questions survive restarts (Sep 30). Subagents: running-subagent indicator in terminal+app (Sep 25), stop a subagent from its transcript panel (Sep 22), selective delegation for OpenAI models with subagent-report reuse (Jul 27). Skills activate mid-message (Sep 26), `--disable-builtin-skills` CLI flag (Jul 22), per-skill disable w/ cross-scope resolution (Jul 15). MCP: faster HTTP connections at session start (Oct 2), wildcard hostname allowlists (Sep 9), per-server connectTimeout (Jul 30), first turn waits for MCP load (Jul 24). Spec Mode uses a separate model from the main loop (Sep 20-25); auto-compaction preserves plans/transcripts.

## 2. Cline (cline/cline)
- Latest: **extension v4.1.22 — 2026-09-30**; parallel tracks: **CLI cli-v3.0.68 (2026-10-02)**, **Desktop v0.0.43 (2026-10-02)**, **SDK sdk/sdk/v0.0.90 (2026-10-02)**. Repo: https://github.com/cline/cline — description now "Autonomous coding agent as an SDK, IDE extension, or CLI assistant."
- Harness notes: v4.0.0 (2026-06-26) moved the whole agent runtime (turns, tools, Plan/Act, MCP, checkpoints, compaction, mistake limits, history) onto the shared Cline SDK session layer; added ClinePass subscription, "Customize" marketplace for Skills/MCP/Plugins, and Plugins (team skills+MCP bundles); queued prompts. v4.1.22 (Sep 30) adds providers + server-side Anthropic refusal fallback / failover via OpenRouter-Cline. Very high release tempo (multiple desktop+SDK+CLI ships per day).

## 3. Kiro (AWS / kiro.dev)
- Latest: **CLI 2.27.0 — 2026-10-01**; IDE 1.2.4 — 2026-09-30; Crew 0.7.0 — 2026-09-24. Changelog: https://kiro.dev/changelog
- Harness notes: "Workflows" (multi-step agent plans) rolled out Web (Sep 30) → IDE background multi-agent (1.2.4, Sep 30) → CLI V3 opt-in (2.26, Sep 30), with inspect/steer/pause/resume and stricter V3 approvals for file writes, MCP tools, shells. CLI 2.27: sub-agent delegation control, live steering context, saved MCP prompts as slash commands, `#[[folder:...]]` steering refs. CLI 2.25: Powers management (`kiro-cli powers`), SessionEnd hook. CLI 2.24: `/tools trust-all` + env isolation (project .env no longer auto-loads into chats/MCP/tools). Crew 0.7: skill index + `skill_search` replaces auto-injection; new agent backends incl. OpenCode and goose; AWS Fargate remote crews. Claude Opus 5.5 (1M ctx) Sep 28.

## 4. Roo Code (RooCodeInc/Roo-Code)
- **CONFIRMED ARCHIVED.** GitHub `archived: true`; last push 2026-05-15; last release **v3.54.0 — 2026-05-15** (prev v3.53.0 Apr 23). ~1,033 open issues at freeze. Repo: https://github.com/RooCodeInc/Roo-Code
- Effectively end-of-life on GitHub; no releases for ~4.5 months. Treat as frozen fork baseline (of Cline lineage), not an active competitor.

## 5. goose (now aaif-goose/goose)
- Org changed: block/goose redirects to **aaif-goose/goose** — goose was donated by Block to the Linux Foundation **Agentic AI Foundation (AAIF)** (announced 2025-12-09 alongside Anthropic's MCP and OpenAI's AGENTS.md; GitHub org created 2026-03-25; docs moved to https://goose-docs.ai/). Not archived; 54.9k stars; pushed 2026-10-02.
- Latest: **v1.53.0 — 2026-10-02** (v1.52.0 Sep 23; v1.51.0 Sep 17).
- Harness notes: recipes fully alive — v1.52.0 enforces recipe parameter limits (max 32 params / 200 select options / 128 KiB); sub-recipes documented at https://goose-docs.ai/docs/guides/recipes/sub-recipes/. v1.51 routes Desktop to a state-machine agent loop via ACP; v1.53 ships a lean ACP-only binary, live model metadata from models.dev, resizable PiP MCP Apps window, session rename CLI. v1.52 added live voice in desktop.

## 6. Gemini CLI (google-gemini/gemini-cli)
- Latest stable: **v0.62.0 — 2026-09-29**; nightlies already at v0.64.0 (daily). Repo: https://github.com/google-gemini/gemini-cli
- Harness notes: built-in `a2a-server` (agent-to-agent) with V1→V2 settings migration; ACP bridge (usage_update notifications); **autonomous plan execution in non-interactive mode** (Sep 30 nightly #29539); ChatRecordingService now does append-only delta patching + bounded history windowing (context mgmt, #29568); atomic state persistence w/ backup recovery; serialized atomic file-tool writes. Unverified third-party claim (primo.ai): consumer Gemini CLI access ended 2026-06-18, replaced by Antigravity CLI `agy` — but the open-source repo is still shipping daily, so treat the claim as affecting Google's consumer packaging only.

## 7. Amp (ampcode.com)
- **Active and shipping.** No semver "release"; changelog ("Chronicle") at https://ampcode.com/news (the /changes page is now behind sign-in).
- Latest items: **Plaid Speed — 2026-09-29** (6x faster GPT-6 Astra inference); **Shared Runners — 2026-09-24** (`--share` a runner so the workspace can launch threads on your machine; macOS app can self-start a runner); **"Free Agent" — 2026-09-13** (free tier using your own compute/model keys); Opus 5.5 powers `medium` mode (Sep 28).
- Harness notes: agents spawning and messaging other agents ("From Agent to Agent", Jul 17) + Puck meta-agent (Jul 20); global plugins & skills shared per workspace (Aug 11); MCP servers attachable to Orbs/Puck (Aug 19); "Read Bigger Threads" (Jul 2) — agents read threads of any size; "Steer, Don't Queue" (Sep 8).

## 8. OpenHands (OpenHands/OpenHands)
- Org renamed **All-Hands-AI → OpenHands** (old org URL redirects). Latest: **v1.24.0 — 2026-09-25** (v1.23.0 Sep 23, v1.22.0 Sep 22 — weekly-ish cadence). Repo: https://github.com/OpenHands/OpenHands
- Harness notes: new **Agent Canvas** desktop app shipping in releases (universal macOS DMG, per-arch bundled runtimes, deb assets); Skills / Hooks / Tools management dialogs in-conversation; remote MCP server testing via the app server + MCP server persistence (v1.22); Git Sync to org admins; automations (cron/stepped schedules), shared read-only automation conversations. OSS app-server architecture remains the SDK backbone.

## 9. Google Antigravity + new harnesses (Sep–Oct 2026)
- **Antigravity 2.0** (Agent Manager surface; platform split from the IDE earlier in 2026) + **Antigravity CLI `agy`** + **Antigravity SDK — announced 2026-09-08** (Google Cloud blog: https://cloud.google.com/blog/topics/developers-practitioners/power-agent-hubs-or-custom-harnesses-with-the-antigravity-sdk): exposes the same runtime engine as Antigravity 2.0/CLI with declarative safety policies, aimed at "agent hubs or custom harnesses." Later Sep items: local-model support in the SDK (Sep 23), Antigravity Spaces project switcher (Sep 21), "Preview 09-2026" (Sep 18). antigravity.google was unreachable from the research sandbox (timeout), so versions are unversioned — no semver published.
- New-harness scan (HN Algolia, stories >40 pts since 2026-09-01): no major new general-purpose harness emerged in Sep–Oct 2026. Adjacent noise: Whiteboard (YC W26, open-source design IDE, 423 pts Sep 24), Skillsync (YC W26, portable chat sessions across agents, Sep 17), Drawgent (Excalidraw-canvas coding agent, Sep 26). Nothing at the maturity bar of the tools above.

## Cross-cutting signals for Atlas
- **ACP (Agent Client Protocol) is becoming the desktop↔agent bus** (goose state-machine loop + lean ACP binary; Gemini CLI ACP bridge; Zed-origin protocol spreading).
- **Skills + MCP + plugins marketplace-ification** everywhere: Cline Customize marketplace, Amp global plugins/skills, Factory per-skill disable, Kiro Powers, goose AAIF (MCP itself under the same foundation).
- **Compaction/handoff as first-class loop control**: Factory `/compress` + `/handoff`, Gemini CLI bounded history windowing, Amp thread-read/handoff, Kiro Crew compaction.
- **Foundation governance**: goose under Linux Foundation AAIF (Dec 2025) — vendor-neutral agent tooling is consolidating.
- **Roo Code archived (May 2026)** — one less VS-Code-fork competitor; Cline's SDK-first v4 pivot ("agent as SDK") is the direct response to CLI/desktop fragmentation.
