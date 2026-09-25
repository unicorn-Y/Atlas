# CODEX-ATLAS-P7I-RUN-PERSISTENCE-RECOVERY

STATUS: READY
WORKER: Luna
BASE_BRANCH: main

## Goal

Add durable recovery metadata for interrupted agent runs.

P7H established connection continuity. P7I addresses the remaining gap: after backend restart, the system must have enough persisted information to explain and recover interrupted runs safely.

## Scope

Only implement:

- persistent run lifecycle metadata;
- interrupted run detection after service restart;
- clear recovery state exposed through existing runtime mechanisms;
- tests for restart/interruption behavior.

## Do not modify

- UI redesign;
- Electron lifecycle;
- MCP architecture;
- streaming protocol format;
- MemoryOS long-term memory design;
- model/provider selection.

## Requirements

1. Store run lifecycle state durably instead of relying only on process memory.

2. Detect runs left active after backend restart and mark them interrupted/recoverable.

3. Preserve existing run.failed behavior where true continuation is impossible.

4. Do not silently replay model/tool execution.

5. Add tests proving:

- active run metadata survives process boundary;
- stale active runs are detected;
- duplicate recovery does not execute a run twice.

## Delivery

- Run required tests.
- Commit changes.
- Push to origin main.
- Create tasks/results/CODEX-ATLAS-P7I-RUN-PERSISTENCE-RECOVERY.result.md.
- Verify local HEAD equals remote main HEAD.

Stop after this task.
