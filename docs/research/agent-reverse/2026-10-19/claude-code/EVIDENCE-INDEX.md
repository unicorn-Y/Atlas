# Evidence index and evidence boundaries

## E0 — fixed artifact provenance (collection snapshot, not binary analysis)
- Source: unicorn-Y/Atlas, research/agent-reverse-dispatch-20261019, docs/research/agent-clients/2026-10-19/manifest.json and indexes/claude-codex-index.txt.
- CLI core: claude-code-cli-core-ac1a6a3364.tgz, 2.1.302, 29,082 bytes, SHA256 **ac1a6a3364c467392bc40a8a405490e821575e3e858d3013b11258862c01dfc8**. Official npm URL https://registry.npmjs.org/@anthropic-ai/claude-code/-/claude-code-2.1.302.tgz ; release URL https://github.com/unicorn-Y/Atlas/releases/download/agent-client-packages-20261019/claude-code-cli-core-ac1a6a3364.tgz.
- CLI native: claude-code-cli-win32-x64-cd077f50f2.tgz, 2.1.302, 132,494,857 bytes, SHA256 **cd077f50f24f5155c28800a3658a58c89b5d1ccae2f95a2e096a16ab250a544d**. Official npm URL https://registry.npmjs.org/@anthropic-ai/claude-code-win32-x64/-/claude-code-win32-x64-2.1.302.tgz ; release URL https://github.com/unicorn-Y/Atlas/releases/download/agent-client-packages-20261019/claude-code-cli-win32-x64-cd077f50f2.tgz.
- Collector index says **7** core-package files and **4** platform-package files extracted. It does not publish their textual contents in this index. Release exists as archive listing; **this session did not fetch bytes or independently recompute hash**.
- Local environment check: direct requests to registry.npmjs.org failed DNS resolution; GitHub connector explicitly rejects non-UTF-8 oversized binary. No fake unpack logs or binaries generated.

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

## E3 — gap register / missing observations
- **No:** core package.json and files read, platform binary name/PE header, native strings with offsets, unpacked program modules, registration map, disassembly, exact agent tool grammar, TUI frames, daemon socket protocol, native session schema, HTTP routing/wire captures, runtime testing, errors/stack traces.
- **Reason:** release asset is available but current connector cannot materialize executable bytes; outbound DNS from container failed.
- **Unlock:** run EXTRACTION-REQUEST.md on authorized local Windows Atlas environment. Preserve artifact SHA and exact asset paths, attach only text/JSON/redacted task logs; raw executable can remain at Release.
- **Scope excluded:** Claude Desktop/Cowork app.asar or its internal services, cloud server implementation, other products' source inferred as Claude's native code, authentication bypass/DRM and credentials.
- **Coverage:** Atlas source inspected across orchestration/backend/session/UI/hooks/MCP/skills/daemon. Claude package first-hand coverage **0 files / 0 bytes**; static native source **S=0**, runtime **R=0**. Do not call this complete.
