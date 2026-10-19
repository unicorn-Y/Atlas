# Implementation traces — bounded by actual source

## A. Native Claude 2.1.302 execution: partial trace from exact packages
The two pinned npm assets are now extracted and hashed; `evidence/` records bytes and bounded evidence. The Node wrapper-to-native launch path and console command surface are directly established. Selected readable Bun-embedded application-JS source has been recovered and statically traced for supervisor lifecycle, wire-schema construction and SendMessage routing (`evidence/12-14`); the full application and native function/call graph are not decompiled. Do not infer control flow from a symbol string alone. Remaining traces are:

1. Entry executable -> command/flag dispatcher -> mode selection (interactive / -p / daemon / attach).
2. Turn constructor -> model request/stream reader -> tool call parser -> permission/hook -> scheduler -> tool result -> next model turn -> stop.
3. Agent tool -> child spawn/selection -> foreground/background queue -> messages/notifications -> completion/error -> cleanup/resume.
4. Worker/supervisor -> socket/IPC -> durable registry -> restart/reconnect/respawn.
5. Transcript/log writer -> session ID -> fork/rewind -> compaction -> summary and budget accounting.
6. Interactive state changes -> TUI rendering/diff/status; noninteractive stream-json full event envelopes. Exact shipped client schema builders are statically traced in `evidence/13`; actual execution/order remains unobserved.

For each remaining path, publish decoded file/function/offset and exact short string evidence with confidence. Only the wrapper/binary boundary and CLI registration have runtime evidence; there is still no completed model/tool invocation trace.

### A1. Installed command to native CLI
1. `package/package.json` lines 4-5,7-16,23-38 exposes `bin/claude=bin/claude.exe`; Node `>=22`, postinstall script, and platform-specific optional package versions are pinned at 2.1.302.
2. `install.cjs:1-6,69-103,105-150,152-163,165-239` detects OS/arch, resolves `@anthropic-ai/claude-code-win32-x64/package.json`, then links/copies its `claude.exe` over the 500-byte placeholder. For normal install, npm's bin shim reaches that PE directly, so Node is not the resident process.
3. If manually invoked, `cli-wrapper.cjs:50-78,83-125,131-155` resolves the optional package, `spawnSync`s the PE with inherited stdio and `CLAUDE_CODE_INSTALLED_VIA_NPM_WRAPPER=1`, maps signal status to 128+signal, and returns process status.
4. The PE SHA is `3ab075f78998efef8b87f491c2e4a39c309dddf44e51d0103eba4f3713d2a0ae`; PE header identifies AMD64 console subsystem. `claude.exe --version` returns `2.1.302 (Claude Code)`; `--help` exits 0 and emits 311 lines. This is observed binary execution, not a model turn.

### A2. Observed CLI command and supervisor boundary
Native help verifies the command parser exposes interactive/print mode, resume/fork flags, `agents`, attach/log/stop/respawn/rm, `daemon`, plugin, MCP, import, gateway and cloud ultrareview surfaces. `agents --json` is documented by the binary as machine-readable active sessions with optional completed-session inclusion; dispatch options supply model/effort/permission/settings/MCP/plugin choices. `daemon` help gives run/status/logs/uninstall/stop. No lifecycle mutator or daemon status was invoked.

Static bundle strings (`06-native-string-index.jsonl`) include named supervisor/lease/auth/claim/respawn helpers, disk-backed subagent transcript lookup, team-context helpers, tool registry names and hook lifecycle helpers. They cluster in the `.bun` embedded payload and are corroborated by CLI commands, but their call relationships/argument fields are not resolved. Treat them as S-level code identifiers and U-level semantics.

**Update from exact embedded source:** the payload also contains readable minified application JS. `evidence/12-native-supervisor-source.md` gives exact PE offsets and bounded method content for `respawnIfIdleStale`, `retireIfSettled`, the interval sweeper, `doSpawn`, claim-frame creation and adoption. The background-supervisor client-side static state logic is now substantially traced, including safety gates, recovery fields and PID/process-start identity checks. These method bodies establish static branch logic, but not execution. Actual daemon/worker creation, attach across daemon restart, on-disk transaction/lease semantics, model interaction and emitted event sequences remain unobserved.

The same payload contains executable wire-schema builders for CLI messages and task events (`evidence/13-native-message-task-schemas.md`). Static schema definitions resolve part of the previous field/event uncertainty: parent provenance and API/local IDs are distinct; background task lifecycle has start/patch/terminal and replace-all snapshot forms; a background tool's real completion may arrive in a later task notification. This is a declared schema trace; no producer trace or serialized message was captured.

### A3. SDK declarations: separate public type contract
The shipped `sdk-tools.d.ts` gives explicit child-agent isolation/model/name/background types (`AgentInput`, lines 772-812), task creation/status/owner/blocking types (2802-2868, 4005-4038) and resumable Workflow inputs/results (2869-2900, 4142+). This gives a real published contract for concepts related to delegation and workflows. The type file does not prove a standalone CLI code path or actual persisted object schema.

## B. Atlas actual primary agent loop (source S for Atlas ONLY)
- core/atlas/agent/__init__.py:310 defines AgentOrchestrator; :761-870 packages RunRequest + RunCallbacks and delegates to execute -> phase runner. This is not an in-house clone of Claude Code's loop.
- core/atlas/engine/hermes_runtime.py:1-10 explicitly identifies Hermes AIAgent fork/upstream inputs; :828-855 run_turn uses worker thread; :855-920 maps streaming text/tool start/tool result/compression/usage through an asyncio queue; :627-788 implements compaction pathway.
- core/atlas/api/run_drive.py:2132+ _execute_run constructs Runtime Event envelopes; :1951-2033 _execute_external_agent runs an external backend and normalizes ACP updates; :2445+ builds subtask.started/progress/completed event callbacks.
- frontend/src/renderer/services/runtimeEvents.ts:3-84 validates event envelope and projects bounded event buffer (MAX_RUN_EVENTS=800).
- frontend/src/renderer/components/ConversationActivity.tsx:132-190 presents step rows, details and child-steering form; :191-287 handles approvals/questions/plans.
- core/atlas/engine/session_sync.py:1-13 identifies Hermes SessionDB as sole persisted conversation transcript writer, with user-turn ordinal native rewind/fork; :561-618 implements those session operations. This is different from a Claude transcript filesystem and should not be conflated.

## C. Atlas's external-Claude transport call chain (verified source)
1. core/atlas/agents/backends/claude.py:18-19 create() produces **ACPBackend("claude", "npx", ["--yes", "@agentclientprotocol/claude-agent-acp@0.81.2"])**. A separate helper :22-28 invokes claude_agent_sdk.query for a single request; this helper does not prove it owns the normal interactive stream.
2. core/atlas/runtime/backends.py:76-127 start_session() spawns an ACP child, initializes protocol and issues new_session, then keeps an in-process dictionary of managers, connections and prompt task.
3. backends.py:130-161 send() launches connection.prompt() as one async task, writes update and done/error events to one queue; :163-166 cancel() issues ACP cancellation.
4. core/atlas/api/agent_backends_router.py:118-136 exposes start; :137-155 resume; :158-178 prompt over SSE; :180-207 cancel/close.
5. core/atlas/api/run_drive.py:1965-1991 maps conversation_id/executor -> in-memory external session ID; :1990-2010 filters ACP update events to Atlas reply.delta / tool.started / tool.completed; :2012-2032 handles cancellation/close.
6. core/atlas/runtime/external_agents.py:60-98 normalize_external_event recognizes agent_message_chunk, tool_call/_update, errors. Other native Claude Code event variants need targeted inventory; no full fidelity or nested-child transcript projection is demonstrated by this function.

**Specific suspected resume defect, static only:** core/atlas/runtime/backends.py:168-185:
- If prior ID is absent from _states, calls start_session(), which creates and caches a *new* ACP session ID and AgentSession metadata {"acp_session_id": newId}.
- Calls connection.load_session(session_id=requestOldId), changes session.id=requestOldId and dictionary key but **does not change session.metadata["acp_session_id"]**.
- send()/cancel() address metadata.acp_session_id, not AgentSession.id. This is inconsistent. A real resumption test must determine whether the connection maintains a second valid new session and where prompts go. Do not label it experimentally broken yet.

## D. Atlas native children, storage and collaboration (verified source)
- core/atlas/agent/__init__.py:485-495 delegate_task calls configured AgentBackendHost; :497-510 resolves child model from settings; :512-650 _run_atlas_subtask recursively runs an Atlas worker, emits SubagentStart/Stop and streams worker callbacks.
- __init__.py:525-546 constructs an independent conversation/prompt, conditional tool denials and no user interaction. :640-650 finally deletes SessionDB entry and memory conversation. **Post-run resume/inspection of that worker transcript is therefore not provided by this path.**
- core/atlas/agent/subagent_worktree.py:237-343 creates/finalizes isolated git worktrees.
- core/atlas/agent/todo_state.py:14-68 holds a bounded revisioned todo list; this is not proof of shared mailbox + claimed task transitions.
- core/atlas/runtime/hub.py:1-17 describes a separate local hub that runs scheduled goals independently of Electron; :119-300 hosts local task orchestration. This does not prove Claude-style interactive daemon-attached session recovery.
- core/atlas/engine/steer_dispatch.py:41-66 uses Hermes steer + tool-worker yield for send-now; :68-118 handles enqueue and compatibility. Live behavior requires an actual run.
- core/atlas/runtime/external_process.py:24-118 pipes subprocess I/O, supports pi-rpc and text only; :133-134 throws NotImplementedError for generic resume. Do not confuse this adapter with ACPBackend.

## E. What source alone does not prove
Despite exact package and help evidence, no native executable function body/call graph, actual spawned daemon process tree, mailbox operation, native event trace, interactive terminal frame, compaction algorithm, authenticated model request routing, or crash-recovery invariant has been observed. PE imports like ConPTY/named pipes/Job Objects are runtime dependencies and do not prove product flow without call xrefs. Likewise Atlas frontend components existing does not establish end-to-end parity. A controlled synthetic authenticated run and a bytecode-aware call trace remain required.
