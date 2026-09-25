# CODEX-ATLAS-P9C-MEMORY-RECALL-AND-CONTEXT-RANKING

## Goal

Upgrade Atlas memory from approved fact storage into usable recall during agent execution.

## Scope

- Add memory retrieval ranking layer.
- Retrieve relevant memories based on current user request.
- Improve context injection quality.
- Keep existing facts and approval flow.
- Add executable tests with recorded numbers.

## Do Not Change

- Do not redesign Runtime.
- Do not modify MCP architecture.
- Do not add multi-agent planning.
- Do not store credentials or secrets.

## Acceptance

- Retrieval behavior covered by tests.
- Memory injection verified in agent context.
- Existing memory tests remain passing except documented baseline failures.
- Test commands and numerical results recorded in tasks/results/.

## KNOWN-BASELINE

Read docs/KNOWN-BASELINE-ISSUES-2026-09-26.md before execution.

## Deliverable

Create:

tasks/results/CODEX-ATLAS-P9C-MEMORY-RECALL-AND-CONTEXT-RANKING.result.md

Commit code and result record. Stop after completion.
