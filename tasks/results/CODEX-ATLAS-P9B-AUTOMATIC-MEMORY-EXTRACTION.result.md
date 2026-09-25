# CODEX-ATLAS-P9B-AUTOMATIC-MEMORY-EXTRACTION

## Outcome

Implemented conservative post-run memory extraction. After the assistant message is saved, Atlas examines user messages in that conversation and puts recognized preferences, personal facts, project state, and explicit project decisions in a separate `memory_candidates` queue. Candidate creation is idempotent per source message. Uncertain statements, questions, and credential-related messages are skipped. No automatic candidate is promoted to active facts.

Users can review candidates with `GET /api/memory/candidates`, approve one with `POST /api/memory/candidates/{id}/approve`, or reject one with `POST /api/memory/candidates/{id}/reject`. Approval atomically upserts the active fact and marks the candidate approved. Existing explicit `remember: key = value` extraction remains unchanged.

The extractor intentionally recognizes a small set of clear English and Chinese sentence forms. It does not infer facts from open-ended conversation or use an external model for memory classification.

## Verification

- New candidate tests: `TestAutomaticMemoryCandidates` — **5 passed**. Covers preference and decision extraction, pending-only storage, uncertain and credential rejection, explicit approval with close/reopen persistence, and rejection.
- Agent orchestration regression: `tests/test_agent.py` — **25 passed**. Confirms extraction runs after a completed response.
- Existing memory suite: `tests/test_memory.py` — **22 passed, 1 known baseline failure**. The failure is `TestMessages.test_message_with_metadata` (`KeyError: 'metadata'`), documented in `docs/KNOWN-BASELINE-ISSUES-2026-09-26.md`.
- Facts and review API suite: `tests/test_server.py::TestFacts` — **4 passed**, including candidate listing and approval through the API using a temporary SQLite database.
- `git diff --check` — **passed**.

## Starting point

- `BASE_HEAD`: `c783995cb556fcb32dd52ff3386de0e65f022439`
- Taskbook: `tasks/taskbooks/CODEX-ATLAS-P9B-AUTOMATIC-MEMORY-EXTRACTION.md`
