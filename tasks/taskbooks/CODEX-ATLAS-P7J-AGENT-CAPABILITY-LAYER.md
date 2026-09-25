# CODEX-ATLAS-P7J-AGENT-CAPABILITY-LAYER

STATUS: READY
WORKER: Luna
BASE_BRANCH: main
PREDECESSOR: CODEX-ATLAS-P7I-RUN-PERSISTENCE-RECOVERY

CODE_BASE_HEAD: 9b9a47d770b85185577be8ab4155c15fd34dc06a

## Goal

Move Atlas from a reliable execution runtime toward a personal assistant capability layer.

## Scope

Only implement the foundation for:

- task capability metadata;
- reusable skill entry points;
- agent capability discovery;
- basic capability lifecycle tests.

The goal is not to build a complete autonomous planner yet.

## Do not modify

- Electron lifecycle
- MCP architecture
- streaming protocol
- MemoryOS integration
- large UI redesign
- model provider system

## Requirements

1. Add a small capability abstraction that can describe available agent capabilities.
2. Keep capability registration separate from runtime execution.
3. Add tests proving capabilities can be discovered and invoked through the intended path.
4. Avoid coupling capabilities to a single model provider.
5. Preserve all existing runtime behavior.

## Verification

Run relevant agent/server tests.
Run frontend build if frontend-facing code changes.

Before delivery:
- git diff --check
- commit changes
- push origin main
- verify local HEAD equals remote HEAD

Create:

tasks/results/CODEX-ATLAS-P7J-AGENT-CAPABILITY-LAYER.result.md

Include RESULT, HEAD values, tests, changed files, and known issues.
