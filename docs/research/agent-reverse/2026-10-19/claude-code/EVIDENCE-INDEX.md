# Evidence index and evidence boundaries

## 2026-10-19 exact-package follow-up overrides the original extraction blocker

The text below under E0/E3 records the earlier web-session state; it is **historical** and no longer describes this local Codex pass. Both cached release TGZs were SHA256/size verified, fully listed and extracted, and the native PE was inspected and invoked for isolated help/version probes. Current evidence is indexed in `evidence/INDEX.md`; older D/U statements remain valid only for claims not resolved by package, bounded embedded-source, or CLI/help evidence.

## E0 — fixed artifact provenance (collection snapshot, not binary analysis)
- Source: unicorn-Y/Atlas, research/agent-reverse-dispatch-20261019, docs/research/agent-clients/2026-10-19/manifest.json and indexes/claude-codex-index.txt.
- CLI core: claude-code-cli-core-ac1a6a3364.tgz, 2.1.302, 29,082 bytes, SHA256 **ac1a6a3364c467392bc40a8a405490e821575e3e858d3013b11258862c01dfc8**. Official npm URL https://registry.npmjs.org/@anthropic-ai/claude-code/-/claude-code-2.1.302.tgz ; release URL https://github.com/unicorn-Y/Atlas/releases/download/agent-client-packages-20261019/claude-code-cli-core-ac1a6a3364.tgz.
- CLI native: claude-code-cli-win32-x64-cd077f50f2.tgz, 2.1.302, 132,494,857 bytes, SHA256 **cd077f50f24f5155c28800a3658a58c89b5d1ccae2f95a2e096a16ab250a544d**. Official npm URL https://registry.npmjs.org/@anthropic-ai/claude-code-win32-x64/-/claude-code-win32-x64-2.1.302.tgz ; release URL https://github.com/unicorn-Y/Atlas/releases/download/agent-client-packages-20261019/claude-code-cli-win32-x64-cd077f50f2.tgz.
- Collector index lists **7** core-package files and **4** platform-package files. Local Codex independently inspected all 11 members and their SHA256; see `evidence/01-archive-manifest.json`. Both archive hashes and exact lengths match the release manifest. The full native executable was unpacked only into local scratch and is not committed.
- Earlier web-session network limitations did not apply to this local Windows follow-up. No hashes, extraction, disassembly, or runtime results were fabricated.

## E1 — Atlas main source snapshot (direct files read)
HEAD verified via GitHub branch API: **aa6196f550098cc46081dc6db2c376cb87ddffa5**. Relative source links below point to main, so recheck exact SHA for future work.

| Verified path | Lines / subject |
|---|---|
| core/atlas/agents/backends/claude.py | 10-28 availability probe, npx ACP wrapper, one-shot SDK call |
| core/atlas/runtime/backends.py | 17-48 backend contract; 64-127 ACP spawn and session; 130-194 send/cancel/resume/close |
| core/atlas/runtime/external_process.py | 24-154 subprocess bridge, stderr/stdout, cancellation, generic resume NotImplementedError |
| core/atlas/runtime/external_agents.py | 9-19 CLI status probe; 60-98 typed external event normalization |
| core/atlas/api/agent_backends_router.py | 118-208 REST session/start/resume/prompt SSE/cancel/close |
| core/atlas/api/run_drive.py | 1951-2034 external execution; 2132-2210 event envelopes; 2445-2490 subtask callbacks |
| core/atlas/agent/__init__.py | 310-370 orchestrator; 485-650 delegate/worker; 761-865 run wrapper |
| core/atlas/engine/hermes_runtime.py | 1-10 Hermes attribution; 627-788 compaction; 828-940 streaming and event translation |
| core/atlas/engine/session_sync.py | 1-13 SessionDB authority; 561-618 rewind/fork and lineage |
| core/atlas/engine/steer_dispatch.py | 41-118 worker-yield/send-now request |
| core/atlas/agent/subagent_worktree.py | 237-343 git worktree create/finalize |
| core/atlas/agent/todo_state.py | 14-68 revisioned bounded todo |
| core/atlas/runtime/hub.py | 1-17 scope; 119-300 background scheduler/run |
| core/atlas/runtime/hooks.py | 60-90 settings import; 287-348 hook dispatcher; 461-548 store execute |
| core/atlas/plugins/runtime.py | 122-313 discovery, command, hook, MCP contribution paths |
| core/atlas/tools/mcp_client.py | 171-490 setup/call tools; 499-577 status/restart |
| core/atlas/models/router.py | 114-359 route and provider completion |
| frontend/src/renderer/services/runtimeEvents.ts | 3-84 event grammar/state projection |
| frontend/src/renderer/components/ConversationActivity.tsx | 35-105 timeline; 132-287 steps/steer/approval/plan |
| frontend/src/renderer/components/Composer.tsx | 40-44 and 152-205 slash/UI handling |
| frontend/src/renderer/components/ForkTree.tsx | 12-67 parent/child branch view |
| frontend/src/renderer/shell/panels/ProcessesPanel.tsx | 7-32 process list/output/stop |

Source URL prefix: https://github.com/unicorn-Y/Atlas/blob/aa6196f550098cc46081dc6db2c376cb87ddffa5/

## E2 — official D-only public declarations, checked October 19, 2026
1. https://code.claude.com/docs/en/cli-reference — flags/commands, daemon, sessions, background, stream-json, fallback, self-hosted runner.
2. https://code.claude.com/docs/en/sub-agents — foreground/background, tool filters, child notifications and navigation.
3. https://code.claude.com/docs/en/agent-teams — disk mailbox, per-agent context, task management and SendMessage.
4. https://code.claude.com/docs/en/hooks — lifecycle, SubagentStart fields and context injection.
5. https://code.claude.com/docs/en/skills — skill resolution and invocation surface.
6. https://code.claude.com/docs/en/checkpointing — rewind conceptual surface.
7. https://code.claude.com/docs/zh-CN/commands — commands including /goal, /batch, /autofix-pr and /focus.
Documentation can evolve independently of npm 2.1.302 and is **not native-S evidence**.

## E3 — remaining gap register
- **Resolved here:** core package metadata/wrapper, exact PE header/section/import/resource maps, bounded strings with byte offsets, native help registration, version/help execution.
- **Partially resolved statically:** embedded client source traces supervisor upgrade/retirement/recovery/adoption; schema builders declare message/task/event shapes; `SendMessage` traces local target resolution, inbox/wake and evicted-child resume. See `evidence/12-14`.
- **Still missing:** full native function/call graph and embedded-module inventory, broader `Agent` tool/model loop, TUI frames, daemon socket envelope/durable registry transaction and runtime process tree, actual session/task/mailbox contents and event ordering, HTTP routing/wire captures, authenticated model/agent turns, operation failures and crash recovery.
- **Reason:** the readable Bun source recovery is bounded and does not resolve native control-flow edges or all application paths; model/daemon/agent operations require controlled authenticated runtime evidence. A full PE inventory attempt exceeded the provider's 330-second analysis deadline; no partial result was treated as success.
- **Unlock:** use a bytecode-aware Bun/Ghidra workflow on the pinned file SHA and a fresh synthetic project/account run without reading pre-existing profile or chat data. Keep all raw binaries/strings local; upload only bounded sanitized evidence.
- **Scope excluded:** Claude Desktop/Cowork app.asar or its internal services, cloud server implementation, other products' source inferred as Claude's native code, authentication bypass/DRM and credentials.
- **Historical coverage line:** the prior web-only session had Claude package first-hand coverage 0 files/0 bytes, S=0, R=0. Current local package/help coverage is in E4 and supersedes that snapshot. This lane remains partial rather than complete.

## E4 — local package and runtime evidence
- `evidence/01-archive-manifest.json` — both verified archives, member inventory, size/type/executable/hash.
- `evidence/02-core-file-tree.txt`, `03-native-file-tree.txt`, `04-package-metadata.md` — actual payload paths and install/runtime launcher chain.
- `evidence/05-native-header.md` — PE structure, imports/resources; `06-native-string-index.jsonl` — selected byte-offset strings tied to executable SHA; `08-native-call-anchors.md` — symbol/module anchors and limits.
- `evidence/07-native-registrations.md`, `11-cli-probes.md` — exact binary help and command exit/output summary.
- `evidence/09-native-state-schema.md`, `10-unknowns.md` — bounded observed types/keys and remaining unknowns.
- `evidence/12-native-supervisor-source.md`, `13-native-message-task-schemas.md`, `14-native-sendmessage-source.md`, `15-native-mailbox-source.md` — exact-PE static source traces with byte offsets and Atlas comparisons; no raw package/binary is included.
- Current package evidence totals: 2 exact archives / 11 extracted members independently hashed; 19 curated native string offsets; 11 version/help commands previously exit 0. A new isolated synthetic `--print` process emitted `system/init` and then returned repeated 401 authentication failures. Its request did not produce an Agent/tool event.
- Static source S now covers the full locally traced SendMessage→mailbox append→read→ack path in the named helper methods. R covers startup/init and the explicit 401 only; Agent operation R remains 0.

## E5 — forced G0–G7 checkpoint (2026-10-19)

- Required work products: `COVERAGE.md`, `SURFACE-MAP.tsv`, `END-TO-END-TRACES.md`, `ATLAS-IMPLEMENTATION-BACKLOG.md`, `FINISH-GATES.md`.
- New `evidence/15-native-mailbox-source.md` adds bounded source from exact PE offsets 248019409–248027467 for inbox path, reader, writer, single/bulk ack and clear.
- Runtime attempted in a new scratch repository with isolated `CLAUDE_CONFIG_DIR`; first event `system/init`, model request failed with HTTP 401 `authentication_failed`. Exact command and facts are in `END-TO-END-TRACES.md`. No valid credentials were read or requested.
- Full PE inventory timed out at 330 seconds; focused REA literal lookup stalled >5 minutes; direct byte-local source extraction was used to continue. Full embedded module/command handler inventory remains open.
- Lane status remains WORK IN PROGRESS: G0 PASS; G1–G3, G5–G6 PARTIAL; G4 BLOCKED-401 for model/task execution; G7 prohibits completion while local code coverage and source traces remain available.
