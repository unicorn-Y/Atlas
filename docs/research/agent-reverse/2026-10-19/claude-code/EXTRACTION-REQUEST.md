# EXTRACTION REQUEST — execute mechanically on local Windows with Codex

**Status: PACKAGE COLLECTION AND BOUNDED STATIC SOURCE TRACES RESOLVED; DYNAMIC/NATIVE-CALL-GRAPH GATES REMAIN.** The original blocker statement immediately below records the prior web-session context and is historical. This request has now been executed against the exact pinned assets. Results are in `evidence/00-14*` and `evidence/INDEX.md`; see each file for precise scope. The lane recovered readable embedded source for supervisor, message/task schemas, and SendMessage routing, so it is no longer string-only. Remaining work is the broader native call graph and controlled authenticated runtime sample, described in `evidence/10-unknowns.md`.

**Historical original blocker:** This ChatGPT GitHub connector could read repository text but rejected the 132 MB native executable as binary; the earlier container could not reach npm. This was a targeted evidence collection request, not a delegation of the research.

**Scope:** Claude Code 2.1.302 only. **DO NOT** inspect Claude Desktop/Cowork, Codex CLI, other products, user account data or unrelated packages. **DO NOT** modify Atlas product code or main. Create/use **research/agent-reverse-20261019-claude-code**, initially branched from the dispatch branch; write solely under docs/research/agent-reverse/2026-10-19/claude-code/evidence/.

## Exact pinned inputs
1. https://github.com/unicorn-Y/Atlas/releases/download/agent-client-packages-20261019/claude-code-cli-core-ac1a6a3364.tgz
   - SHA256 ac1a6a3364c467392bc40a8a405490e821575e3e858d3013b11258862c01dfc8
   - 29,082 archive bytes, collection index reports 7 extracted members.
2. https://github.com/unicorn-Y/Atlas/releases/download/agent-client-packages-20261019/claude-code-cli-win32-x64-cd077f50f2.tgz
   - SHA256 cd077f50f24f5155c28800a3658a58c89b5d1ccae2f95a2e096a16ab250a544d
   - 132,494,857 archive bytes, collection index reports 4 extracted members.
Optional upstream sanity checks, *only if matching these SHA*: npm @anthropic-ai/claude-code@2.1.302 and @anthropic-ai/claude-code-win32-x64@2.1.302. Never silently replace with latest.

## Step 0: branch isolation
Use a **separate git worktree** based on origin/research/agent-reverse-20261019-claude-code. If already checked out somewhere, use that checkout; do not force-reset or overwrite other agents' files. Work in a temporary scratch directory outside the repository for archives and full extracted binaries. Only upload bounded sanitized text/JSON evidence; leave raw .tgz/.exe in Release or local scratch. Confirm HEAD and note commit in evidence/00-provenance.md.

Completion record: isolated linked worktree `work/claude-code-lane`, baseline `18a280b25c4a49c8eb554e227a32e0fd7c58fe4b`; scratch stayed outside this checkout; no Atlas application code or raw archives were committed.

## Step 1: independently inspect real archives
Download both release assets through authenticated gh release download or standard GET. Compute PowerShell Get-FileHash SHA256 and exact byte lengths; abort further analysis if either mismatches. Run tar -tzf against *both*. Extract to two separate scratch folders with tar -xzf, preserving paths. Generate evidence:
- 01-archive-manifest.json: input filename/URL/SHA/size/version and **every tar member** (relative path, file size, type, executable bit, sha256).
- 02-core-file-tree.txt and 03-native-file-tree.txt: actual extracted structure (not collection index guesses).
- 04-package-metadata.md: print actual package.json, bin, os/arch, dependencies, optionalDependencies, install scripts, license and published file names; note wrapper entry and how it locates native program.
- For each short human-readable JS/CJS/MJS/JSON/shell file in the 29 KB core wrapper, write an exact **path + line-number** excerpt or a source copy in evidence/core-readable/, no credentials or user data. Include full wrapper code if license permits; otherwise short relevant quotes with symbol map.
- 05-native-header.md: identify real executable by content magic, version resource, PE header machine/subsystem/sections, imports and embedded resource names using dumpbin/llvm-readobj/objdump/pefile (whichever installed). Do **not** presume runtime (Bun/Node) from filename or marketing.

## Step 2: native binary static symbol/string map
Use local Python or ripgrep to extract ASCII printable sequences (length >= 8) with **byte offsets**, and UTF-16LE sequences if significant; keep large full dumps **local only**. Make evidence/06-native-string-index.jsonl with fields:
- offset_hex, encoding, exact_excerpt (cap 300 chars), category, context_before_after (short), file_sha256;
- only **bounded relevant hits** (target <= 5 MB) grouped by registration/protocol/states, not every generic English word.
- Search both *names and their likely field keys* in compiled strings for these categories:
  - command registration: cli root/subcommands, daemon, agents, attach, respawn, stop, logs, rm, resume, fork-session, compact, rewind, tasks, plan, focus, goal, batch, ultrareview, import, hooks, plugin, mcp, remote-control, gateway, self-hosted-runner;
  - model/tool loop: assistant, tool_use, tool_result, stop_reason, input_tokens, output_tokens, cache_read_input_tokens, max_turns, prompt, completion, tool scheduler, retry, compaction, system prompt;
  - children/team: SubagentStart/Stop, Agent, parent_tool_use_id, agent_id, team, inbox, SendMessage, TaskCreate/Get/List/Update, background, handback, supervisor;
  - state/event: session_id, transcript, jsonl, fork, parent_uuid, request_id, stream-json, hook_started/progress/response, permissions, notifications, stale/lease/daemon/socket;
  - terminal: renderer/fullscreen, keybindings, menus/status markers, accessibility fallback, progress/spinner/layout.
For each substantive hit cluster, collect nearby strings, executable section and 5-20 related hits. Distinguish "static symbol/word" from "callable function". If disassembler/decompiler (Ghidra, radare2, Binary Ninja, llvm) is available, additionally map XREF/function start/assembly snippet for **10 highest-value clusters**: native dispatch, agent tool invocation, supervisor/worker registry, transcript writer, team mailbox, event serialization, compaction trigger, tool permission/hook, model HTTP/stream, TUI state. Include raw offset and confidence. Do **not** generate unsupported pseudocode claiming an entire function is decoded.

Outputs:
- 06-native-string-index.jsonl
- 07-native-registrations.md (commands, handlers, feature flags, string locations)
- 08-native-call-anchors.md (symbol/function/offset and linked observable behavior)
- 09-native-state-schema.md (only real keys/schema excerpts and file writes; annotate uncertain)
- 10-unknowns.md (literal unknown IDs, unrecognized protocols, suspicious discoverable extra commands)

## Step 3: controlled unauthenticated CLI checks
Use the **extracted native executable** when possible, not another installed version. Record command line, exact executable SHA, stdout/stderr text and exit code for:
- --version and --help;
- agents --help, daemon --help/status, attach --help, plugin --help, mcp --help, if these return without login.
- --output-format and --input-format help snippets if discoverable.
Capture only command help, no personal session picker, no auth status fields, no local ~/.claude contents. Save evidence/11-cli-probes.md. If help hangs or requires login, record that without workaround.

## Step 4: controlled dynamic sample when authorized account can run it
**Optional until authenticated test access is available**: run in a newly created temporary git repo with one synthetic .txt file, with a fresh synthetic task, no user's chat history/project sources. Prefer fixed installed/extracted 2.1.302, verify sha/version. Collect:
A. simple question + one file read + one allowed tool, noninteractive with --output-format stream-json --verbose --include-partial-messages; include --forward-subagent-text if supported. Save sanitized original event JSONL and a separate event type/field schema summary.
B. create foreground and background child; emit completion and cancellation; log parent/child ID, parent_tool_use_id, ordered updates and final tool result. If delegation is model-disabled, mark blocked.
C. session --resume and --fork-session on synthetic content; compare IDs and parent linkage, do not copy any preexisting user transcripts.
D. one synthetic hook tool event; one toy local MCP server if already configured in scratch; record order and event types.
E. if possible background supervisor: start -> detach -> agents --json -> attach/logs -> stop -> respawn, in temporary project. Observe real daemon process tree/socket registry and which state survives restart. Only open scratch-owned daemon/session artifacts; do not inspect preexisting user folders.
F. terminal render snapshots of agent/task/status panels with synthetic session. Capture sanitized screen text/key sequence, no personal names or auth.

Write evidence/12-stream-events-redacted.jsonl, 13-event-schema.md, 14-state-lifecycle.md, 15-tui-frames.md, 16-runtime-process-tree.md as available. Preserve **observed** from **inferred**. If a stage cannot run, record exact blocker in 99-blockers.md and continue other stages. No attempt to bypass authentication/permissions or extract private tokens.

## Step 5: output integrity + push
- Every static claim: path / file sha / section + byte offset or readable file line.
- Every runtime claim: exact command, version, setup, redacted log, exit/status, whether reproduced.
- Include evidence/INDEX.md with paths, byte totals, captured timestamp and "not run" status for missing parts.
- Do not upload archives, native full strings, session DB, chats, home directory, API keys, Cookie, machine identifiers or telemetry secrets.
- Commit **only** evidence/ outputs to research/agent-reverse-20261019-claude-code; push. Do **not** edit our completed docs or Atlas application code in this mechanical pass. Report full commit SHA and evidence/INDEX.md URL to this ChatGPT session.

## Acceptance
Reject pseudo-research like a list of commands copied from docs or AI-generated summaries of concepts. Accept bytes-derived index with SHA and reproducible offsets, true source excerpts, and actual synthetic execution logs (where possible). On receipt, this session can proceed to cross-reference **CLAUDE_CODE-001..025**, upgrade D/U to genuine S/R, fill mechanism-level implementation traces and update Atlas gap judgments without needing the whole large package in chat.
