# Atlas Current Task

CURRENT: ATLAS-C6R-FINISH
STATUS: AWAITING_REVIEW
CONTROLLER: ZCode
TASKBOOK: tasks/taskbooks/ATLAS-C6R-FINISH.md
RESULT: tasks/results/ATLAS-C6-CODING-POLISH.result.md
REVIEW: tasks/reviews/ATLAS-C6-CODING-POLISH.review.md

BASE_BRANCH: main
PREVIOUS: ATLAS-C6-CODING-POLISH
PREVIOUS_REVIEW: PARTIAL — two focused closeout fixes

## Current goal

Close only:
1. V4A path-less patch LSP diagnostics;
2. /review finding internal file + line navigation.

Everything else in C6 is accepted and must not be reopened.

## Execution

Use subagents for independent backend/frontend fixes if useful.
Use the maximum concurrency the runtime allows; no fixed worker cap.

## Completion

Append C6R evidence, set CURRENT to AWAITING_REVIEW, push main, verify remote HEAD, and stop.
Do not start T1.
