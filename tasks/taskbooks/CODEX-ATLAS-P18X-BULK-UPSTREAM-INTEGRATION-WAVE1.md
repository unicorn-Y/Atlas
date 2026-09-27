# CODEX-ATLAS-P18X-BULK-UPSTREAM-INTEGRATION-WAVE1

STATUS: READY
WORKER: Luna
BASE_BRANCH: main

## Mission

Execute the single bulk integration checklist:

`docs/ATLAS_BULK_UPSTREAM_INTEGRATION_CHECKLIST_WAVE1.md`

Do not split this into child taskbooks.

This replaces the current single-feature P18B-FIX1 queue strategy.

## Existing work to preserve

- P18A FULL_ACCESS local execution.
- P18B desktop observation/input/window work.
- P18B-FIX1 corrected external-process Windows mouse acceptance evidence.
- P15 Skills.
- P7F MCP.
- P17 packaging.

Do not throw these away.

## Execution style

Install and wire the full selected integration set first.

Do not stop after each integration for exhaustive testing.

For each component:
1. install/detect;
2. register;
3. thin adapter;
4. one deterministic smoke;
5. continue.

After everything is wired, run cross-capability and packaged smokes.

If one optional/external backend is blocked by missing local auth/account/CLI:
- mark DEGRADED/BLOCKED;
- continue with the rest;
- do not stop the wave.

## Required deliverables

- Capability registry.
- AgentBackend minimum contract.
- Bucket A integrations wired.
- Bucket B agent backends wired/detectable.
- exact versions/source/license log.
- integration matrix.
- one or more cross-capability E2E smokes.
- packaged registry smoke.
- result:
  `tasks/results/CODEX-ATLAS-P18X-BULK-UPSTREAM-INTEGRATION-WAVE1.result.md`

## Stop rule

Stop only after the bulk checklist is completed as far as the current machine permits.

Do not begin a separate FIX task.

Report all remaining issues in one integration matrix for the next concentrated debug wave.

## Queue guard

This is the only READY task.

No P18C/P19/voice/camera/mobile separate task may start during this wave.
