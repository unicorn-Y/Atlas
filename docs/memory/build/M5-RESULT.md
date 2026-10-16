# M5 implementation result

Status: **M5 IMPLEMENTATION READY — INTEGRATION AND REAL GATE PENDING**

S4 follow-up: addressed the acceptance return on raw search. `search_raw` now returns only a 320-character-bounded matched excerpt and stable `SourceRef`; it omits results with no excerpt and never falls back to a message-body field. Full transcript text remains available only through `memory_open`.

Branch: `mem-m5`
Base: `origin/mem-m2` at `5ffb1a16`
Worktree: `D:\atlas-mem-m5`

## Implemented within M5 ownership

- `core/atlas/memory/library/index.py`: exposes normalized Claim metadata and ranking reasons on hits; consumes M7 `is_current_claim(entry, now)` when available; supports target-page filtering and one-hop association wiring through M9's API; keeps SQLite/FTS as rebuildable projections. Association is lazily imported because `association.py` is delivered on M9's branch.
- `core/atlas/memory/library/hybrid.py`: records normalized keyword/vector scores, fusion weights, and temporal decay in `rank_reasons`.
- `core/atlas/memory/library/sources.py`: adds `memory_open(ref, window, engine_root=...)` and exact `SourceRef` URI/mapping resolution by `(conversation_id, message_uid)`, including bounded neighboring context and optional span/hash checks. Existing `session@timestamp` references remain readable and are labeled `precision=approximate`.
- `core/atlas/memory/library/__init__.py`: keeps the existing `recall/search` entry points compatible, includes Claim ID/source/time/reason and association provenance in relevant summaries, and exposes citation/usage metadata in search results. M3-owned write/lifecycle portions were not changed.
- `core/atlas/memory/library/recall.py` (new): provides a single lexical-only `recheck_memory(error_text, limit=3)` for M1's repeated-tool-failure hook, plus citation-block parsing and idempotent citation event recording.
- `MemoryIndex` maintains a derived `usage_events` table with stable event IDs and distinct event types. Public `MemoryLibrary.search(..., invocation_id=...)` records exposures using `exposure:<sha256(invocation_id)>:<claim_id>`; the kernel caller should pass a run/message/tool-call identity. When omitted, the documented deterministic fallback hashes UTC date, normalized query, filters, limit, and sorted result Claim IDs. This fallback deduplicates identical searches with the same result set on one UTC date; separate calls should pass distinct invocation IDs. Citation events update derived `usage_count/last_used`. Rebuilding or deleting `.index.sqlite` may discard these statistics, as intended for derived data.

## Frozen cross-module calls

- M7 confirmed `claim_resolution.is_current_claim(entry, now=None) -> bool`, accepting Entry or Mapping. M5 passes parsed Markdown Entries; the local branch does not contain M7's module yet, so the code retains a legacy-bucket fallback marked `claim_currentness=legacy_bucket_fallback` until integration.
- M9 confirmed `build_link_index(store)`, `expand_one_hop(seeds, link_index, limit)`, and `rank_associations(seeds, candidates)`. M5 supplies seeds with `path`, optional `id` and `source_ref`, and expects page candidates with `page_path`, `via_page`, `link_text`, `seed_id`, `seed_source_ref`, `reason`, and `rank_reasons`. M5 then searches the target page to obtain current Claims. M9's module is absent from this base; linked recall is not yet runtime-verified.
- M1 can call `from atlas.memory.library.recall import recheck_memory` after two consecutive tool failures. The function returns `query`, `hits`, and a compact `block`; it performs no rewrite, vector search, or association expansion.

## Integration gaps and real-use gate

The existing kernel registration and dispatch live outside M5 ownership. Root integration must add `memory_open` to `core/atlas/kernel/tools.py:kernel_tool_schemas`, wire its execution beside `memory_search` in `core/atlas/kernel/loop.py`, and add it to `core/atlas/kernel/plan.py`'s fixed tool allowlist. The memory instruction is currently appended in `core/atlas/kernel/loop.py` (`Long-term memory` prompt block); it needs the Chinese read-path guidance there. M1 owns `loop.py`; M5 did not edit these files. Citation parsing also needs a post-response call to `record_citations(answer, run_id=..., message_id=...)`; explicit open/feedback/task-result event call sites remain for integration.

The required real Atlas dialogue gate has **not** been run. After M7, M9, M1, and M5 are integrated, verify Chinese keyword, semantic, named-entity, time-bounded, and conflicting-current/history queries; open at least three real SourceRefs and verify the exact SessionDB message; disable embeddings and confirm keyword fallback; delete `.index.sqlite` and rebuild from Markdown; exercise one-hop, orphan, broken-link, and deleted-target paths; verify exposure/open/citation/feedback event separation and replay idempotency. Do not mark M5 DONE until this gate and kernel integration pass.

## Verification performed

- `py_compile` passed for the five changed Python modules using `D:\Atlas\core\.venv\Scripts\python.exe`.
- No pytest suite or real Atlas conversation was run in this implementation branch. The acceptance gate above remains pending integration.
