# CODEX-ATLAS-P10H-AUTONOMOUS-KNOWLEDGE-APPLICATION

## Goal
Apply approved autonomous knowledge to future planning and execution while preserving evidence, provenance, and approval boundaries.

## Scope
- Add knowledge application layer for approved goal knowledge.
- Provide deterministic retrieval for planning/execution contexts.
- Keep source goal, evidence, and approval provenance attached.
- Record knowledge usage events for observability.

## Do Not Change
- Do not bypass tool approval.
- Do not auto-promote pending or rejected knowledge.
- Do not mutate original facts or commitments automatically.
- Do not store credentials.

## Acceptance
- Approved knowledge can be retrieved deterministically.
- Retrieval keeps provenance and evidence references.
- Agent receives knowledge as advisory context only.
- Tests include rejection/pending exclusion.

## KNOWN-BASELINE
- Existing metadata baseline failure remains tracked.

## Deliverable
- Implementation commit.
- tasks/results/CODEX-ATLAS-P10H-AUTONOMOUS-KNOWLEDGE-APPLICATION.result.md
