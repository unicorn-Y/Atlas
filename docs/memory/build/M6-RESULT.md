# M6 implementation result

Status: **IMPLEMENTATION READY — INTEGRATION AND REAL-USE GATES PENDING**

Branch: `mem-m6`  
Worktree: `D:\atlas-mem-m6`
Base and merge order: `origin/mem-m2@5ffb1a16` → `origin/mem-m5@c5474a80` → `origin/mem-m1@f0fc4d40` → M1 provenance fix `origin/mem-m1@11b6eddf`. The M1/M5/M2 merges were conflict-free; the resulting pre-implementation integration commit was `bef7aaa4`.

## Implemented within M6 ownership

- Added `core/atlas/agent/delegation_memory.py` with `prepare_delegation_context`, `capture_delegation_result`, and `source_refs_for_result`.
- `SubagentManager.run` now runs bounded M5 Claim search for the child task, passes only Claim text/metadata and valid SourceRef URIs, and instructs the child to use the existing `memory_search` tool and its `open` argument for further search and expansion. Search failure leaves the previous context intact and is recorded as a status field; it does not block the task.
- On `SessionEnd`, the bridge captures the child assistant terminal UID and tool-message identifiers/names/status without copying message bodies into result metadata. It asks the runner to retain the child session. A SourceRef is emitted only if the exact `(conversation_id, message_uid)` still resolves after the runner returns; otherwise the result explicitly reports the missing source.
- Results carry a deterministic event ID when parent session, child session, and terminal UID are all known. The `delegation` object carries status, timestamps, source availability, Claim IDs, ref counts/data, and compact tool summaries. Structured metadata is separate from the framed result text.
- `KernelWorkflowSubagentRunner` includes delegation metadata in the parent completion event and `NodeResult.metadata`.
- Added content-free structured events `memory.delegation.context_prepared` and `memory.delegation.result_captured`.

## Required integration callsites outside M6 ownership

These are explicit integration contracts; they were not edited in this lane.

1. `core/atlas/agent/tool_node.py`, the `atlas_options` mapping in the `delegate_task` dispatch: add `parent_conversation_id=ctx.conversation_id`. Without it, the bridge cannot form the required parent/child/terminal idempotency key.
2. `core/atlas/agent/__init__.py`, `AgentOrchestrator._run_atlas_subtask` cleanup around the `SessionEnd` callback and unconditional `delete_session` / `delete_conversation`: honor `atlas_options["retain_child_session"]` for M6 runs. The bridge already captures the terminal assistant UID during `SessionEnd` and validates the exact pointer afterward. Until retention is honored, no child SourceRef is emitted because the transcript has been deleted.
3. `core/atlas/agent/enrichment.py`, the Atlas branch of `DelegationService.run` where the `atlas_runner` result is projected into the returned mapping: preserve the `delegation` metadata field. The current projection drops fields outside its allowlist, so the parent tool result cannot yet receive this event.
4. Once preserved, the existing parent tool-result/SessionDB and M1 lifecycle path must deliver the returned experience to M3. No independent transcript store or result ledger is introduced here.

## Verification and remaining gates

- `D:\Atlas\core\.venv\Scripts\python.exe -m py_compile core/atlas/agent/delegation_memory.py core/atlas/agent/results.py core/atlas/kernel/subagents.py`: passed.
- `git diff --check`: passed.
- No real Atlas delegation was run in this lane. The M6 taskbook's three real-use cases, exact child SourceRef open, M3 processing, restart recovery, and duplicate-terminal idempotency remain pending the integration callsites above. This result does not claim `M6 DONE`.

## Decisions

- Child result text remains the normal delegated tool result and follows the parent's ordinary SessionDB/M3 path. `delegation` metadata contains pointers and lightweight execution metadata only.
- Do not treat the parent tool payload or a summary as the child transcript source. When the canonical runner has not retained the child SessionDB row, report source unavailable and omit the child SourceRef.
- M6 does not register a second memory tool: child Atlas runs already expose `memory_search(open=...)`. M5's raw search remains bounded and its full content is available only through the existing read API.

M6 IMPLEMENTATION READY — REAL-USE AND INTEGRATION GATES PENDING
