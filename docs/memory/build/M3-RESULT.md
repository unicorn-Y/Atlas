# M3 implementation result

Status: implemented; awaiting merged M1 lifecycle integration and real Atlas session acceptance.

## Scope and baseline

- Branch/worktree: `mem-m3` / `D:\atlas-mem-m3`.
- M3 baseline before implementation: `6b64ded7` (`origin/mem-m2` at worktree creation).
- M2 merge brought the branch to `5ffb1a16e7bdf73733198beefe8d2f581e04a3b0`; merge completed without conflicts.
- Owned implementation files: `core/atlas/memory/library/extract.py` and `core/atlas/memory/library/__init__.py`.
- M1 owns `queue.py` and lifecycle helpers; M2 owns SessionDB/source/store; M7 owns claim resolution. None were modified here.

## Implemented

- Added Chinese two-layer extraction prompt and schema for detailed session episodes plus sourced atomic fact candidates. Episode fields retain decisions/reasons, files, commands, errors, numbers, unfinished work, corrections, summary and exact M2 `SourceRef` pointers.
- Added UID-only `schedule_lifecycle(event, *, model_mgr=None)` bridge using M1 `lifecycle.enqueue` and `start_watcher`; the compatibility `schedule_turn` now resolves stable SessionDB UIDs and delegates without copying transcript bodies into the queue.
- Lifecycle consumption reads canonical SessionDB messages by UID, verifies candidate and episode provenance against exact input references and SessionDB evidence, and keeps turn-end diary/fact extraction separate from full idle/session episode extraction.
- Writes fact candidates as M4-reviewable history entries (`src=M3候选`, `why=待 M4 整合`) without changing current claims. Episode and candidate entries carry `extractor_version` and source references for idempotency/recovery.
- Stable schema/provenance errors fail without model retry; provider/transient and malformed-JSON errors retain bounded retries. Candidate facts alone do not advance the whole-message processed UID watermark.

## Verification

- `python -m py_compile core/atlas/memory/library/extract.py core/atlas/memory/library/__init__.py`: passed.
- `git diff --check`: passed.
- `core/tests/test_memory_library_w2.py`: 8 passed.
- Combined W1/W2 focused suite: 11 passed, 4 failed. The four W1 failures exercise superseded legacy episode behavior/schema: two assertions expect old episode composition/forgetting behavior, one expects a fact with no required M2 source reference, and one expects an episode with no required `source_refs`. This is recorded as an integration compatibility risk, not a passing gate.
- Not yet verified: M1 `lifecycle` integration on a merged branch, real-model extraction, real Atlas conversation with all required detail types, source opening through the live runtime, timeout-then-retry queue outcome, or end-to-end second-run idempotency. These require the merged M1 lifecycle and a real Atlas session; this result does not claim the taskbook's full real-use acceptance.

## Integration notes

- Agreed M1 adapter contract: `MemoryLibrary.schedule_lifecycle(event: dict[str, Any], *, model_mgr: Any = None) -> None`; required fields are `conversation_id`, ordered `message_uids`, `event_kind`, `occurred_at`, and `scope`; optional `run_id` and `tool_call_id`; transcript/body fields are rejected.
- M1 must merge its `lifecycle.py`/queue changes before the adapter can be exercised end-to-end. Retry wake and startup recovery stay M1-owned; M3 exposes `processed_source_uids(conversation_id)`.
- M4 should consume fact candidates from Markdown page history and use M7's agreed nine-field claim payload. M3 intentionally does not call `claim_resolution`.

## M2 API metadata follow-up

- Extended `_page_dict` entry rows in `core/atlas/memory/library/__init__.py` to expose `source_level`, `recorded_at`, `valid_from`, `valid_to`, `supersedes`, `retracts`, and `source_ref` while preserving all existing keys. Values come from the M2 `Entry` fields; `source_ref` remains its JSON object form.
- This closes the `/api/memlib` entry-view metadata gap identified during S4 integration review. Compilation and diff checks are recorded with the follow-up commit; this does not change the outstanding real-use gate status.

M3 IMPLEMENTATION READY — REAL GATE PENDING
