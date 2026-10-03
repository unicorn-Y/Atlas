# Atlas Current Task

CURRENT: ATLAS-MEGA-PERSISTENT-ALWAYS-ON
STATUS: READY_FOR_EXECUTION
CONTROLLER: ZCodex
TASKBOOK: tasks/taskbooks/ATLAS-MEGA-PERSISTENT-ALWAYS-ON.md
RESULT: tasks/results/ATLAS-MEGA-PERSISTENT-ALWAYS-ON.result.md
REVIEW: tasks/reviews/ATLAS-MEGA-PERSISTENT-ALWAYS-ON.review.md

BASE_BRANCH: main
PREVIOUS: ATLAS-MEGA-LATEST-DAILY-READY
PREVIOUS_REVIEW: PASS

## Goal

Turn Atlas from a daily-ready desktop agent into a persistent always-on personal agent by continuously integrating the latest strongest mature implementations.

Continuous scope:
1. freeze latest OpenClaw / Hermes / DBOS sources;
2. tail-sync Hermes fork;
3. persistent agents + Bot Mode/group chat;
4. Gateway + Telegram/Slack/Feishu/DingTalk/WeCom/Email/Webhook;
5. OpenClaw-style Heartbeat/proactivity;
6. durable Cron/Automation with existing DBOS + OpenClaw semantics + Hermes product surface;
7. Atlas-owned Windows laptop / paired-device ownership + human handoff;
8. Hermes managed local llama.cpp runtime + activation tool-call probe;
9. Skill Workshop/curator upgrade;
10. integration/dedup + deterministic acceptance.

## SUBAGENT POLICY — HARD REQUIREMENT

- Use subagents for the bulk of research, source comparison, porting, implementation, focused tests, and review.
- Target the maximum concurrency the current runtime actually allows.
- Do not hard-code a worker count.
- Keep spawning independent lanes until the runtime refuses more concurrent workers.
- If a spawn is rejected, shrink that batch; when slots free up, dispatch the rest.
- A concurrency rejection is NOT a reason to disable subagents or work single-threaded.
- Shared hot files have one integration owner.

## Principles

- Latest information first; strongest implementation wins.
- Direct-port mature code when practical.
- Cross-language high-coupling code: port the state machine/protocol, not a weak imitation.
- Do not embed OpenClaw as a second Agent core.
- Do not duplicate SessionDB / Scheduler / SkillRegistry / Computer / Browser.
- Memory stays frozen.
- Speed first; focused tests first.

## Completion

Write result, set CURRENT to AWAITING_REVIEW, push relevant repos, verify local/remote heads, and stop.
Do not start X6 / full T1 / R1.
