# Claude Code CLI / Agent Harness — staged source audit

**Status: PARTIAL / BINARY-BLOCKED, not reverse-research complete.** This is a substantive first-stage audit of release provenance, the current official protocol surface and actual Atlas source call-sites. **No claim that Claude Code 2.1.302's compiled runtime has been decoded or dynamically executed.** The native binary is available as a release asset, but the current GitHub connector rejects non-UTF-8/big binary resources and this container cannot reach the public npm host. Read EXTRACTION-REQUEST.md and upload its small mechanical evidence bundle to this branch before claiming any S/R-grade Claude Code mechanism.

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

## Deliverables
- DISCOVERY-LEDGER.md — ID-indexed hypothesis/documentation/unknown accounting
- IMPLEMENTATION-TRACE.md — Atlas *source-grounded* execution and message traces; Claude side explicitly D/U until binary arrives
- UI-AND-WORKFLOWS.md — documented CLI flows and actually inspected Atlas GUI/REST path
- ATLAS-GAP.md — source-anchored engineering gaps with bounded confidence
- EVIDENCE-INDEX.md — source anchors, binary provenance, disallowed inference boundary
- EXTRACTION-REQUEST.md — precise local Codex binary extraction with deliverables to resume real reverse engineering
- REUSE-CANDIDATES.md — permissions/licensing and protocol reuse boundaries

## Next gating requirement
Produce the mechanical evidence requested in EXTRACTION-REQUEST.md from the two SHA-pinned tgz assets and push small text/JSON outputs to **this branch**, under evidence/. Then trace real native entrypoints, command registration, task state, daemon IPC, agent loops and at least one controlled execution log. Until then **Claude package mechanism S=0, runtime R=0**; official documented surface D is not substituted for either.

This checkpoint contains real Atlas source audit rather than a feature-list-only plan. It does **not** satisfy the protocol's completed reverse-engineering bar without binary follow-up.
