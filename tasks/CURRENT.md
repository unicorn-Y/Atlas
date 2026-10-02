# Atlas Current Task

CURRENT: ATLAS-U0-HERMES-UPSTREAM-SYNC
STATUS: READY_FOR_EXECUTION
CONTROLLER: ZCode
TASKBOOK: tasks/taskbooks/ATLAS-U0-HERMES-UPSTREAM-SYNC.md
RESULT: tasks/results/ATLAS-U0-HERMES-UPSTREAM-SYNC.result.md
REVIEW: tasks/reviews/ATLAS-U0-HERMES-UPSTREAM-SYNC.review.md

BASE_BRANCH: main
PREVIOUS: ATLAS-C6R-FINISH
PREVIOUS_REVIEW: PASS — C1-C6 closed

## Current goal

Before X2/X4/X5, update the Hermes fork to current upstream and preserve Atlas-specific improvements.

After U0:
1. U1 global latest-best refresh
2. X2
3. X4
4. X5
5. K1
6. user daily use

Do not start X2 before U0 and U1 are accepted.

## Execution

Use subagents aggressively for independent conflict groups and fill the maximum concurrency the runtime currently allows.
No fixed worker count.

## Completion

Write U0 result, set CURRENT to AWAITING_REVIEW, push fork + main coordination changes, verify heads, then stop.
