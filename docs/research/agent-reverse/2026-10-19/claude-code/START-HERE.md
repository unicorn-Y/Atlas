# Claude Code CLI / Agent Harness — staged source audit

**Status: PARTIAL / EXACT PACKAGES ANALYZED; AUTHENTICATED AGENT RUNTIME NOT OBSERVED.** The two pinned Claude Code 2.1.302 npm archives were independently SHA/size verified, fully listed and unpacked; the actual win32-x64 PE was structurally parsed and scanned for bounded strings; isolated `--version` and command help probes ran against that exact PE. The package is therefore no longer binary-blocked. It is still not reverse-research complete: native Bun bytecode/function call edges and a synthetic authenticated Agent/tool turn, persisted task/agent state and supervisor recovery remain unobserved.

## Input freeze
- Claude Code 2.1.302, npm core tgz: **ac1a6a3364c467392bc40a8a405490e821575e3e858d3013b11258862c01dfc8**, 29,082 bytes; indexed **7 extracted files**.
- Claude Code 2.1.302, win32-x64 native tgz: **cd077f50f24f5155c28800a3658a58c89b5d1ccae2f95a2e096a16ab250a544d**, 132,494,857 bytes; indexed **4 extracted files**.
- Archived at https://github.com/unicorn-Y/Atlas/releases/tag/agent-client-packages-20261019; collection manifest: docs/research/agent-clients/2026-10-19/manifest.json on dispatch branch.
- Atlas source snapshot read: **main@aa6196f550098cc46081dc6db2c376cb87ddffa5** (2026-10-19 query). This HEAD is the audited baseline only; newer work on other branches is **not** part of this judgment.
- Date of doc check: 2026-10-19. Official docs are a living reference and may describe behavior newer than, gated in, or absent from 2.1.302.

## What we actually established now
1. **Atlas's selected Claude backend is an ACP adapter**, not a port of the Claude Code binary loop: core/atlas/agents/backends/claude.py:18-28 constructs @agentclientprotocol/claude-agent-acp@0.81.2, and core/atlas/runtime/backends.py:64-194 owns ACP sessions. An independent, one-shot official Claude Agent SDK query helper also exists (claude.py:22-28). Neither is proof of Claude Code core parity.
2. **ACP resumption needs a targeted fix/verification**: backends.py:168-186 creates a *new* ACP session, then calls load_session for another ID, changes AgentSession.id but leaves metadata.acp_session_id at the new ID. Subsequent send/cancel use metadata.acp_session_id (lines 145,165). Whether load_session behavior happens to tolerate this must be tested; do not announce a runtime-confirmed failure.
3. **Generic external process resume is explicitly absent**: runtime/external_process.py:133-134 raises NotImplementedError, while API still exposes a generic resume route (api/agent_backends_router.py:137-155). Distinguish this from ACPBackend's attempted resume.
4. **Atlas's worker-session lifecycle is intentionally short-lived**: agent/__init__.py:512-651 creates a child conversation and deletes both Hermes SessionDB record and Atlas memory conversation in finally. This does not implement persistent, addressable child transcripts after completion.
5. **Atlas does have real mechanisms, not merely a shell**: Hermes run loop and compression (engine/hermes_runtime.py), revisioned TodoStore (agent/todo_state.py), git worktree helper (agent/subagent_worktree.py), event projection and GUI timeline (frontend/src/renderer/services/runtimeEvents.ts, components/ConversationActivity.tsx), SessionDB-native fork/rewind (engine/session_sync.py), background Hub (runtime/hub.py), hook/plugin/MCP runtimes. Gap conclusions therefore apply to *specific contracts*, never a blanket 'no agent functionality'.

## Real package follow-up (2026-10-19)

- Evidence tree: [`evidence/INDEX.md`](evidence/INDEX.md); archive/member verification: [`evidence/01-archive-manifest.json`](evidence/01-archive-manifest.json); PE and string anchors: `evidence/05-native-header.md`, `06-native-string-index.jsonl`, `08-native-call-anchors.md`; isolated exact-binary help: `evidence/11-cli-probes.md`.
- The PE is a 290,211,488-byte AMD64 console executable (`claude.exe`, SHA256 `3ab075f78998efef8b87f491c2e4a39c309dddf44e51d0103eba4f3713d2a0ae`) with a 170,783,232-byte `.bun` section. FileVersion/ProductVersion is 2.1.302.0; static Bun strings include `bun-v1.4`.
- A new, mechanism-level clue beyond the earlier docs: the embedded bundle has named helpers for `respawnIfIdleStale`, `scheduleRespawn`, `socketAuth`, `buildClaimFrame`, disk subagent listing/transcript lookup, dynamic team context, and lifecycle hook dispatch. Paired with exact-binary CLI help for `daemon`, `agents --json`, `attach`, `respawn`, `stop`, and `rm`, this establishes a richer resident supervisor/background-session surface. It does **not** establish how its lease protocol works or that recovery succeeds.
- Further newly observed surfaces: shipped CLI help registers config import, enterprise gateway, cloud multi-agent `ultrareview`, plugin marketplace lifecycle, MCP `serve`, and worktree-safe cleanup flags; the embedded binary explicitly says Windows does not support the POSIX-only `--hooks-dir`/orchestrator path.
- The same binary returned `2.1.302 (Claude Code)` and exit 0 for version/help probes in an isolated empty profile. No credentialed model call was attempted.
- Evidence strengths: two exact archives + 11 package members independently hashed; package source/metadata **S**; PE structure and literal bundle anchors **S**; 11 unauthenticated CLI/version/help commands **R**. This R coverage is only CLI registration/help, not an agent task run.

## Deliverables
- DISCOVERY-LEDGER.md — ID-indexed hypothesis/documentation/unknown accounting
- IMPLEMENTATION-TRACE.md — Atlas *source-grounded* execution and message traces; Claude side explicitly D/U until binary arrives
- UI-AND-WORKFLOWS.md — documented CLI flows and actually inspected Atlas GUI/REST path
- ATLAS-GAP.md — source-anchored engineering gaps with bounded confidence
- EVIDENCE-INDEX.md — source anchors, binary provenance, disallowed inference boundary
- EXTRACTION-REQUEST.md — precise local Codex binary extraction with deliverables to resume real reverse engineering
- REUSE-CANDIDATES.md — permissions/licensing and protocol reuse boundaries

## Remaining gates
The extraction request's exact assets, file trees, core package excerpts, PE header/resources, bounded native string index and CLI help probes are resolved in `evidence/`. Still unresolved: Bun bytecode-to-function call graph, exact session/task/mailbox schema, authenticated Agent/tool loop, real event samples, daemon IPC and durable recovery, TUI interactions, hooks/plugin/MCP execution, and cloud-side implementations. See `evidence/10-unknowns.md`; preserve these as U rather than promoting docs or strings into runtime proof.
