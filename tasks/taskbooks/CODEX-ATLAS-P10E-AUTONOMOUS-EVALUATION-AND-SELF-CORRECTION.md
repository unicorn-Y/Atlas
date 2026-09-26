# CODEX-ATLAS-P10E-AUTONOMOUS-EVALUATION-AND-SELF-CORRECTION

## Goal
Add autonomous evaluation after execution so Atlas can judge whether a goal is actually satisfied and decide whether to complete or replan.

## Scope
- Add goal evaluation stage after execution.
- Evaluate evidence against goal and plan requirements.
- Support replan when evaluation fails.
- Preserve existing approval boundaries.
- Record evaluation decisions as events.

## Do Not Change
- Do not bypass human approval.
- Do not auto-promote untrusted memory.
- Do not remove existing reflection and recovery flow.

## Acceptance
- Goal completion requires evaluation evidence.
- Failed evaluation produces a replan path.
- Evaluation decisions are persisted.
- Existing goal scheduler tests remain passing.
- Add executable tests with measured results in result file.

## Deliverable
- tasks/results/CODEX-ATLAS-P10E-AUTONOMOUS-EVALUATION-AND-SELF-CORRECTION.result.md
