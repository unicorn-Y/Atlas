# CODEX-ATLAS-P7H-AGENT-SESSION-CONTINUITY

STATUS: READY
WORKER: Luna
BASE_BRANCH: main
PREDECESSOR: CODEX-ATLAS-P7G-RUNTIME-ERROR-RECOVERY
CODE_BASE_HEAD: b4d18ff5e3ef4f5ce1f557fa78825fc2fa3aa9a9

## Goal

Improve agent session continuity around reconnects and interrupted runs.

The goal is to make Atlas behave reliably when a frontend connection drops or a user returns to an unfinished session.

## Scope

Only implement:

- runtime reconnect state handling;
- safe recovery of interrupted run state;
- frontend/backend synchronization after reconnect;
- tests for disconnect and reconnect paths.

## Do not modify

- UI redesign;
- Electron lifecycle;
- MCP architecture;
- MemoryOS design;
- streaming protocol format;
- external model configuration.

## Required checks

- Existing agent/server tests remain passing.
- Add tests proving reconnect does not duplicate messages or create duplicate runs.
- Add tests proving failed/interrupted runs reach a final visible state.

## Delivery

Before commit:

- git diff --check
- inspect git diff
- no secrets or local config

Commit:

feat: harden agent session continuity

Create:

tasks/results/CODEX-ATLAS-P7H-AGENT-SESSION-CONTINUITY.result.md

Include:

- RESULT
- BASE_HEAD
- FINAL_HEAD
- REMOTE_HEAD
- CHANGED_FILES
- TEST_RESULTS
- KNOWN_ISSUES

Push to origin main and verify remote HEAD matches local HEAD.
