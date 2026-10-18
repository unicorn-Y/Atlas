# Implementation traces — bounded by actual source

## A. Native Claude 2.1.302 execution: NOT YET TRACEABLE
Two official npm assets are identified and hash-pinned, but neither is a text codebase accessible to this runtime. The 29 KB core wrapper could be inspected after extraction, and the 132 MB platform native asset requires strings/disassembly/controlled command tracing. Do not reverse-infer internal algorithms from Anthropic docs. Required native traces after evidence upload:

1. Entry executable -> command/flag dispatcher -> mode selection (interactive / -p / daemon / attach).
2. Turn constructor -> model request/stream reader -> tool call parser -> permission/hook -> scheduler -> tool result -> next model turn -> stop.
3. Agent tool -> child spawn/selection -> foreground/background queue -> messages/notifications -> completion/error -> cleanup/resume.
4. Worker/supervisor -> socket/IPC -> durable registry -> restart/reconnect/respawn.
5. Transcript/log writer -> session ID -> fork/rewind -> compaction -> summary and budget accounting.
6. Interactive state changes -> TUI rendering/diff/status; noninteractive stream-json full event envelopes.

For each, publish decoded file/function/offset and exact short string evidence with confidence. **Nothing in this list is claimed already decoded.**

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
No available Claude native function names/offsets, actual subprocess topology, mailbox parser, native events, intermediate terminal frames, TUI AST, compaction algorithm, model request routing or crash-recovery invariants have been observed. Likewise Atlas frontend components existing does not establish end-to-end parity. Extraction and controlled dynamic runs are the minimum next stage.
