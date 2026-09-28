# Atlas Current Task

CURRENT: CODEX-ATLAS-INTEGRATION-DEBUG-WAVE1
STATUS: READY

PREVIOUS: CODEX-ATLAS-P18X-BULK-UPSTREAM-INTEGRATION-WAVE1
STATUS: PASS
RESULT: tasks/results/CODEX-ATLAS-P18X-BULK-UPSTREAM-INTEGRATION-WAVE1.result.md
REVIEW: tasks/reviews/CODEX-ATLAS-P18X-BULK-UPSTREAM-INTEGRATION-WAVE1.review.md
REVIEW_RESULT: PASS
IMPLEMENTATION_HEAD: c4b21e77b33e21e24501b52947c7414c30108e4f

TASKBOOK: tasks/taskbooks/CODEX-ATLAS-INTEGRATION-DEBUG-WAVE1.md

WORKER: Luna

CODE_BASE_HEAD: c4b21e77b33e21e24501b52947c7414c30108e4f

NEXT: CODEX-ATLAS-CAPABILITY-ENRICHMENT-WAVE1
NEXT_STATUS: BLOCKED

QUEUE_GUARD:
Integration Debug Wave 1 is the only READY task.
Do not split into Codex/Claude/Hermes/Pi/ZCode/CUA/Browser/DBOS micro-tasks.
Wave 1 bulk wiring is accepted and must be preserved.
Fix real protocol/runtime integration gaps in one concentrated pass.
External auth-only blockers may remain DEGRADED without blocking the wave.
FULL_ACCESS remains the default.
Do not reintroduce per-tool approval prompts for external Agent backends.
Voice, camera and mobile remain outside this wave.

BASE_HEAD_RULE:
After pulling origin/main, record the actual starting HEAD as BASE_HEAD.

RULE:
Read LUNA_WORKER.md, PLAN.md, the P18X review, and the current taskbook.
Execute the concentrated debug wave as one task.
Do not create a FIX1/FIX2 task after completion.
