# Claude Code CLI / Agent Harness — staged source audit

**Status: WORK IN PROGRESS / STATIC INBOX AND TASK-EVENT CHAINS ADVANCED; MODEL TURN BLOCKED BY 401.** Both pinned Claude Code 2.1.302 archives and executable identity remain verified. Source evidence now traces SendMessage → validated inbox append/read/ack and task registration → terminal notification construction → bounded queue → selected consumers. All 2,428 unique chunk import IDs referenced by the full `.bun` range are inventoried; semantic review remains selective. An isolated synthetic `--print` run reached `system/init` before repeated HTTP 401 `authentication_failed`. Required G0–G7 lane documents are present. Do not close the lane: TUI/action chain, authenticated model/tool/subagent execution, same-child-to-parent event delivery, actual worker/mailbox state and daemon restart remain open. See `FINISH-GATES.md`.

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
6. **Claude background supervisor logic is source-traced but static**: exact embedded methods guard stale-version restart against attached/recent/in-flight workers, restore resume ID/flags/cwd/transcript state, and validate PID/process-start on adoption (`evidence/12`). The daemon was never started.
7. **CLI event/task schemas are declared in the exact PE**: parent/tool ancestry, task/run identities, patch vs replacement updates, delayed background results, permission/execution metadata, init capabilities and result timing (`evidence/13`). No generated event frame was captured.
8. **SendMessage is traced beyond registration**: direct teammate roster resolution, permission and fail-closed identity guards, mailbox append + wake for active teammate, and recovery of an evicted child with prior messages (`evidence/14`). The mailbox writer implementation and actual message/turn were not run. Atlas main contains real group-room orchestration and a separate durable notification inbox; those contracts differ from Claude direct messaging (`ATLAS-GAP.md`).

## Real package follow-up (2026-10-19)

- Evidence tree: [`evidence/INDEX.md`](evidence/INDEX.md); archive/member verification: [`evidence/01-archive-manifest.json`](evidence/01-archive-manifest.json); PE and string anchors: `evidence/05-native-header.md`, `06-native-string-index.jsonl`, `08-native-call-anchors.md`; source excerpts: `evidence/12-native-supervisor-source.md`, `13-native-message-task-schemas.md`, `14-native-sendmessage-source.md`; isolated exact-binary help: `evidence/11-cli-probes.md`.
- The PE is a 290,211,488-byte AMD64 console executable (`claude.exe`, SHA256 `3ab075f78998efef8b87f491c2e4a39c309dddf44e51d0103eba4f3713d2a0ae`) with a 170,783,232-byte `.bun` section. FileVersion/ProductVersion is 2.1.302.0; static Bun strings include `bun-v1.4`.
- Beyond helper names, readable bundled application source now shows stale-worker restart/retirement guards, v5 state recovery inputs, PID-validated adoption and staged low-memory cleanup. This establishes static client state logic, not how lease persistence works or that recovery succeeds.
- Bundled source schemas and SendMessage code establish the declared event/task protocol and a substantial local teammate routing/resume path. They do **not** establish event ordering, mailbox transaction details, authenticated model execution or cloud service behavior.
- Further newly observed surfaces: shipped CLI help registers config import, enterprise gateway, cloud multi-agent `ultrareview`, plugin marketplace lifecycle, MCP `serve`, and worktree-safe cleanup flags; the embedded binary explicitly says Windows does not support the POSIX-only `--hooks-dir`/orchestrator path.
- The same binary returned `2.1.302 (Claude Code)` and exit 0 for version/help probes in an isolated empty profile. No credentialed model call was attempted.
- Evidence strengths: two exact archives + 11 package members independently hashed; package source/metadata **S**; PE structure, literal anchors and bounded embedded source/schema excerpts **S**; 11 unauthenticated CLI/version/help commands **R**. This R coverage is only CLI registration/help, not an agent task run.

## Deliverables
- DISCOVERY-LEDGER.md — ID-indexed hypothesis/documentation/unknown accounting
- IMPLEMENTATION-TRACE.md — Atlas *source-grounded* execution and message traces; Claude-side package evidence is in `evidence/12-14`, with runtime/API unknowns retained
- UI-AND-WORKFLOWS.md — documented CLI flows and actually inspected Atlas GUI/REST path
- ATLAS-GAP.md — source-anchored engineering gaps with bounded confidence
- EVIDENCE-INDEX.md — source anchors, binary provenance, disallowed inference boundary
- EXTRACTION-REQUEST.md — precise local Codex binary extraction with deliverables to resume real reverse engineering
- REUSE-CANDIDATES.md — permissions/licensing and protocol reuse boundaries

## Remaining gates
The extraction request's exact assets, file trees, core package excerpts, PE header/resources, bounded native string index and CLI help probes are resolved in `evidence/`. Source traces now resolve part of the supervisor/client wire/tool behavior. Still unresolved: native call graph and full Agent/model/tool loop, actual transcript/mailbox persistence schema and contents, serialized event samples/order, live daemon IPC and recovery, TUI interactions, hooks/plugin/MCP execution, and cloud-side implementations. See `evidence/10-unknowns.md`; preserve these as U rather than promoting static source into runtime proof.
