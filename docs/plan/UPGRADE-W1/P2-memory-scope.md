# P2 — Memory scope isolation

## Changes

- core/atlas/memory/library/index.py:61 adds the scope column; :149–155 migrates old tables with ALTER TABLE and adds items_scope; :211–264 indexes entry scopes; :485–507 filters explicit scopes or global plus current project.
- core/atlas/memory/library/__init__.py:295–319 derives the prefixed project scope from workspace; :541–551 accepts scope on add_entry.
- core/atlas/memory/library/store.py:65–108 retains the existing global default and metadata round-trip. A guard at :272–294 and :398–402 prevents MemoryStore from staging through a parent repository when its root is nested; this was added after task tests unexpectedly advanced the checkout branch.
- hybrid.py needed no changes; library/__init__.py's existing agent write path preserves agent scopes, and extracted project memories use the derived project scope.
- core/tests/test_memory_scope.py:8 adds migration, isolation, metadata round-trip, and agent-scope coverage.

## Why

Persist each memory's visibility scope in the index so global, project, and agent memories can be filtered without rebuilding the table or changing the existing five origin classes.

## Verification

    $env:PYTHONPATH='D:\Atlas\core'; & 'D:\Atlas\core\.venv\Scripts\python.exe' -m pytest core/tests/test_memory_scope.py --basetemp=core/.pytest-basetemp-scope-final3 -q
    6 passed, 6 warnings in 8.35s

Related memory regression:

    $env:PYTHONPATH='D:\Atlas\core'; $env:ATLAS_TEST_DISABLE_MEMORY_EMBEDDINGS='1'; & 'D:\Atlas\core\.venv\Scripts\python.exe' -m pytest core/tests/test_memory.py core/tests/test_memory_library_w0.py core/tests/test_memory_library_w1.py core/tests/test_memory_library_w2.py --basetemp=core/.pytest-basetemp-memory-regression-final3 -q
    38 passed, 5 failed, 7 warnings in 65.31s

Failures: three source-reference prerequisites, one legacy _relevant_block return-arity expectation, and one embedding event-loop expectation. The taskbook's core/tests/unified_memory directory does not exist in this checkout, so that exact suite was not run.

## Acceptance evidence and remaining work

- Passed: legacy database migration sets old rows to global; A/B project isolation; Entry.scope serialization round-trip; agent scope write/search; MemoryLibrary workspace lookup includes the matching prefixed project scope alongside global rows; explicit scope filtering also applies to raw-search results.
- No changes were needed in hybrid.py; the five origin_class values are unchanged.
- The wider memory regression remains red; these failures are not attributed to scope without a clean baseline comparison.
- The parent-repository guard is a safety fix for the observed nested MemoryStore commit side effect. Two empty commits appeared during this run; because their tree matched origin/ui-redesign, the branch pointer was restored with a mixed reset that retained the working tree.
- A generated, untracked pytest basetemp directory at core/.pytest_tmp_w1_mem remains in the checkout; it contains per-test temporary memory roots and was not removed.
