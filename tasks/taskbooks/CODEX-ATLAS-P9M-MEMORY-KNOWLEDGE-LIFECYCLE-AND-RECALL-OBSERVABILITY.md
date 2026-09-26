# CODEX-ATLAS-P9M-MEMORY-KNOWLEDGE-LIFECYCLE-AND-RECALL-OBSERVABILITY

## Goal
Improve visibility and safety of MemoryOS knowledge usage after P9L retrieval optimization.

## Scope
- Add deterministic observability for knowledge retrieval decisions.
- Record why knowledge items were selected or filtered.
- Add regression coverage for lifecycle rules during retrieval.
- Keep existing approval, identity evidence, and commitment lifecycle rules unchanged.

## Do Not Change
- Do not bypass candidate approval.
- Do not auto-promote rejected candidates.
- Do not weaken identity evidence requirements.
- Do not put credentials into tracked files.

## Acceptance
- Executable tests with recorded numbers.
- Retrieval decisions expose deterministic reasons/evidence.
- Existing memory lifecycle tests remain passing except documented baselines.
- Result file under tasks/results/.

## KNOWN-BASELINE
Read docs/KNOWN-BASELINE-ISSUES-2026-09-26.md before execution.

## Deliverable
- Code changes.
- Result report.
- Stop after completion.
