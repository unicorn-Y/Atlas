# CODEX-ATLAS-P7K-SKILL-CLEANUP-AND-GOVERNANCE

STATUS: READY
WORKER: Luna

## Goal

Clean and stabilize the skill capability layer before deeper MemoryOS and agent learning integration.

## Scope

- Fix existing skill scan YAML errors.
- Resolve duplicate skill names deterministically.
- Fix coding-discipline skill encoding issues.
- Define skill validation rules.
- Add tests for invalid skill metadata handling.
- Handle runtime generated files such as data/schedules.toml appropriately.

## Do Not Modify

- MemoryOS
- UI redesign
- Electron lifecycle
- MCP architecture
- Streaming protocol
- Runtime persistence

## Verification

- Skill discovery tests pass.
- Invalid skill inputs have clear errors.
- Existing agent capability tests remain passing.
- git status clean before push.

## Delivery

Commit and push to origin main.
Create tasks/results/CODEX-ATLAS-P7K-SKILL-CLEANUP-AND-GOVERNANCE.result.md.
