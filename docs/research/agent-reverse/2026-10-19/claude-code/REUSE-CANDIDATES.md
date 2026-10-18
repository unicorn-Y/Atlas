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
