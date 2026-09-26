# CODEX-ATLAS-P9L-MEMORY-KNOWLEDGE-RETRIEVAL-OPTIMIZATION

## Goal
Improve retrieval quality on top of the consolidated user knowledge layer.

## Scope
- Add deterministic knowledge retrieval evaluation beyond current fact matching.
- Improve ranking signals for knowledge views.
- Keep evidence chains available for every injected knowledge item.
- Add regression coverage for relevant and irrelevant retrieval cases.

## Do Not Change
- Do not bypass memory approval workflow.
- Do not auto-promote candidates.
- Do not modify identity/commitment lifecycle rules.
- Do not store credentials or secrets.

## Acceptance
- Executable tests with recorded numbers.
- Retrieval behavior is deterministic.
- Irrelevant knowledge is excluded.
- Existing memory baselines remain documented.

## KNOWN-BASELINE
Read docs/KNOWN-BASELINE-ISSUES-2026-09-26.md before execution.

## Deliverable
- Implementation commit.
- tasks/results/CODEX-ATLAS-P9L-MEMORY-KNOWLEDGE-RETRIEVAL-OPTIMIZATION.result.md
