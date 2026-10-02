# Atlas Current Task

CURRENT: ATLAS-C6-CODING-POLISH
STATUS: READY_FOR_EXECUTION
CONTROLLER: GPT-6.1 Sol / reasoning=medium
WORKERS: GPT-6 Luna / reasoning=high (parallel)
TASKBOOK: tasks/taskbooks/ATLAS-C6-CODING-POLISH.md
RESULT: tasks/results/ATLAS-C6-CODING-POLISH.result.md
REVIEW: tasks/reviews/ATLAS-C6-CODING-POLISH.review.md

BASE_BRANCH: main
PREVIOUS: ATLAS-C5-C6A-INTEGRATION
PREVIOUS_REVIEW: PASS — tasks/reviews/ATLAS-C5-C6A-INTEGRATION.review.md

## Current goal

Finish the remaining C6 before T1:

1. Wire the already-integrated LSP core into real edits + UI.
2. Implement /init.
3. Implement /review using the existing child runtime.
4. Fix long-session rendering/performance.
5. Do the final core UX polish pass.

Do not rebuild the C6A LSP core.

## Execution

Use subagents aggressively for independent modules and use the maximum concurrency the current runtime allows.
Do not hard-code a worker limit.
Prefer mature upstream implementations/components over custom reduced versions.

## Completion

Write C6 result, set CURRENT to AWAITING_REVIEW, push main, verify remote HEAD, then stop.
Do not start T1.
