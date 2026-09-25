# CODEX-ATLAS-P9F-MEMORY-ACTIVE-CONTEXT-AND-USER-CONTINUITY

## Goal

Upgrade memory from retrieval into active user continuity context.

## Scope

- Build active context assembly from validated memories
- Improve user continuity across conversations
- Add deterministic context selection rules
- Preserve existing facts/candidates/consolidation contracts

## Do Not Change

- Do not rewrite Agent runtime
- Do not change MCP architecture
- Do not store credentials
- Do not bypass memory approval rules

## Acceptance

Must provide executable verification:
- Active context selection tests
- Cross-session continuity tests
- Irrelevant memory exclusion tests
- Existing memory regression remains passing except documented baseline failures

## KNOWN-BASELINE

Read docs/KNOWN-BASELINE-ISSUES-2026-09-26.md before execution.

## Deliverable

- Code changes
- tasks/results/CODEX-ATLAS-P9F-MEMORY-ACTIVE-CONTEXT-AND-USER-CONTINUITY.result.md
