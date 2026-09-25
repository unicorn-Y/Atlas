# Atlas Current Task

STATUS: READY

TASK_ID: CODEX-ATLAS-P7I-RUN-PERSISTENCE-RECOVERY

TASKBOOK: tasks/taskbooks/CODEX-ATLAS-P7I-RUN-PERSISTENCE-RECOVERY.md

WORKER: Luna

CODE_BASE_HEAD: aa54a84195ca4d6a18ee668b986c34223545686c

BASE_HEAD_RULE:
After pulling origin/main, record the actual starting HEAD as BASE_HEAD. Review/task-dispatch commits after CODE_BASE_HEAD are expected.

PREVIOUS_REVIEW:
P7H accepted. Session continuity handles reconnect routing, duplicate run.start prevention, and missing runtime state terminal failure. Remaining gap: runtime state is memory-resident and does not survive service restart.

RULE:
Read LUNA_WORKER.md first, then execute TASKBOOK exactly. Do not start another task after completion.
