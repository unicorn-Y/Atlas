# CODEX-ATLAS-P9G-MEMORY-LONG-TERM-IDENTITY-AND-COMMITMENTS

## Goal

Build the next MemoryOS layer for stable long-term identity and commitments on top of P9A-P9F.

## Scope

- Add explicit identity/commitment memory concepts.
- Separate temporary context from durable user commitments.
- Track commitment lifecycle where appropriate.
- Ensure recalled identity information is evidence-backed.

## Do Not Change

- Do not rewrite Agent runtime.
- Do not modify MCP architecture.
- Do not store credentials or secrets.
- Do not bypass existing memory approval and quality rules.

## Acceptance

- Tests prove durable identity/commitment storage behavior.
- Tests prove old or unsupported information cannot silently become active identity.
- Context injection remains bounded and deterministic.
- Existing memory regression tests remain passing except documented baseline issues.

## KNOWN-BASELINE

Read docs/KNOWN-BASELINE-ISSUES-2026-09-26.md before execution.

## Deliverable

- Code changes.
- tasks/results/CODEX-ATLAS-P9G-MEMORY-LONG-TERM-IDENTITY-AND-COMMITMENTS.result.md
