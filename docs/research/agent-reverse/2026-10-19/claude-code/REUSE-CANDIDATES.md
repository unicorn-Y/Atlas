# Reuse and integration candidates

## C1 — Existing Atlas Hermes engine (already in tree)
- core/atlas/engine/hermes_runtime.py:1-10 records upstream NousResearch/hermes-agent source, with a pinned fork. core/atlas/agent/subagent_worktree.py:1-10 credits MIT upstream and Atlas adjustments.
- Already integrated: agent turn executor, compression, MCP, tool progress; reusing this engine plus improved event contracts is far less expensive than guessing Claude's closed implementation.
- Before upstream port: verify exact source revision and notice requirements in THIRD_PARTY_NOTICES.md and local pinned Hermes fork. Respect semantic differences: do not market as a Claude Code native clone.

## C2 — ACP protocol + Claude ACP bridge
- Atlas source uses @agentclientprotocol/claude-agent-acp@0.81.2 from npx, and acp session/process transport (agents/backends/claude.py:18-19; runtime/backends.py:64+).
- Candidate: better session-ID reconciliation, structured event preservation, command capabilities and resume tests inside Atlas bridge. Check the installed dependency's license/contract at the pinned version before redistribution.
- Caveat: community/bridge implementation is **not the official Claude Code native engine**. ACP updates may intentionally omit fields present in Claude's own CLI stream-json.

## C3 — Claude Agent SDK official boundary
- Atlas claude.py:22-28 references official claude_agent_sdk.query; official SDK is a way to *use Claude's supported agent interface*, not source access to the proprietary native executable.
- Prefer documented SDK APIs for external Claude integration if the product requires stable programmatic use. Check subscription/auth/metering, terms and actual ability to stream/resume before treating it as a drop-in.
- Do not confuse SDK session persistence with Atlas's SessionDB.

## C4 — Adopt public protocol ideas, not copied binary code
- Event envelopes with parent-child ancestry, typed tool completion, process supervisor registry, durable background task notifications and revisioned mailbox can be independently implemented in Atlas after observed evidence.
- Developer source interfaces and observable file formats can be studied for interoperability. **Claude Code binary is proprietary; no approval to redistribute decompiled components** is established by possession of the official installer.

## C5 — UI and plugin compatibility
- Atlas already contains its own React renderer, Claude-like hook settings parser, plugin discovery, MCP and skills. Improve data flow and validation against evidence before rewriting UI.
- Claude HUD/ccusage are **third-party extension samples**, not evidence that an analogous component is native to Claude Code 2.1.302. They are assigned to their own product sessions; do not blend results here.

## Decision
Preserve Atlas as the sole runtime/memory owner. Use Claude externally through supported boundaries, translate typed events without throwing away provenance, and implement missing Atlas-native durability. For native Claude mechanisms, defer code-level porting decisions until **actual binary evidence** is extracted; official docs establish user behavior but not internal architecture or reuse rights.

## C6 — Workflow and task semantics from the shipped SDK types
- The core package's `sdk-tools.d.ts:772-812,2802-2900,4005-4038` publishes agent isolation, addressable background agents, explicit task dependencies/status, and resumable Workflow script/run identifiers. These are useful interop-contract candidates for comparison with Atlas `TodoStore`, group/task storage, subagent worktrees and run lifecycle.
- The declarations are bundled SDK API types, not source under an OSI license and not proof the native CLI calls each interface. The package license is all-rights-reserved / subject to Anthropic legal agreements; copy neither code nor type text into Atlas. Reimplement compatible concepts from observed behavior only if product requirements justify them.
- High-value verification: establish whether Atlas's task store needs owner/dependency links and whether resumed workflow caching requires idempotency records. First obtain an actual Claude API/event sample; do not infer user-facing guarantees solely from TypeScript comments.

## C7 — Windows supervisor feasibility and platform boundary
- The actual PE imports Windows console, process, named-pipe and job APIs, while the bundle includes explicit diagnostics that self-hosted lifecycle hooks/orchestrator mode require POSIX execution. This identifies a platform-specific boundary to investigate; imported Win32 symbols are not permission or evidence to copy a supervisor design.
- Native executable remains proprietary. Evidence is restricted to hashes, metadata, selected offsets and independently written bounded descriptions of embedded-source logic; no native executable or bulk decompiled source is redistributed.

## C8 — Addressed messaging and child recovery concepts (analysis only)
- Exact 2.1.302 PE source (`evidence/14-native-sendmessage-source.md`) shows recipient resolution guards, permission/hook checks, task-scoped inbox writes, wake-on-message for a running teammate, and metadata-based rehydration of an evicted child. These are good **comparison concepts** for Atlas's existing persistent group-room log and detached-notification inbox; this research found no direct code/package that can be reused.
- Atlas main `aa6196f550098cc46081dc6db2c376cb87ddffa5` already has real group orchestration (`core/atlas/groups`) and durable per-conversation notifications (`core/atlas/engine/notifications.py`). If a product requirement calls for direct child-addressed messaging or child resume, specify how those should interoperate with those current stores before implementation. This lane makes no implementation recommendation beyond the observed contract difference.
- `Zw` inbox-write internals, file schema and locking were not recovered; event and recovery behavior has not been run. Do not implement a guessed clone from the method names or assume the private binary grants source/license rights. A future change should use Atlas-owned contracts and independently defined storage semantics.
