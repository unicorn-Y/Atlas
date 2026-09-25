# CODEX-ATLAS-P9B-AUTOMATIC-MEMORY-EXTRACTION

## Goal

Upgrade Atlas memory from explicit user commands to automatic memory extraction while keeping user control and avoiding incorrect memory writes.

## Scope

- Add post-conversation memory extraction pipeline.
- Detect durable user preferences, decisions, project state, and useful facts.
- Store candidates separately before promotion to active facts.
- Add tests for extraction, rejection, and persistence.

## Do Not Change

- Do not replace current runtime architecture.
- Do not remove existing facts storage.
- Do not store secrets or API keys.
- Do not commit real credentials.

## Acceptance

Must provide executable evidence:

- New extraction tests pass with recorded numbers.
- Existing memory tests remain passing except documented baseline issues.
- Candidate memory creation can be verified from a conversation fixture.
- Invalid or uncertain information is not automatically promoted.

## KNOWN-BASELINE

Read docs/KNOWN-BASELINE-ISSUES-2026-09-26.md before execution.

## Deliverable

- Code changes.
- tasks/results/CODEX-ATLAS-P9B-AUTOMATIC-MEMORY-EXTRACTION.result.md
- Stop after completion.
