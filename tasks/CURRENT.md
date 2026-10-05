# Atlas Current Task

CURRENT: ATLAS-H1-CORE-HARDENING
STATUS: CLOSED_BY_USER
CONTROLLER: Codex
TASKBOOK: tasks/taskbooks/ATLAS-H1-CORE-HARDENING.md
RESULT: tasks/results/ATLAS-H1-CORE-HARDENING.result.md
REVIEW: tasks/reviews/ATLAS-H1-CORE-HARDENING.review.md

BASE_BRANCH: main
BASE_COMMIT: 574db83
PREVIOUS: ATLAS-MEGA-PERSISTENT-CLOSEOUT
PREVIOUS_STATUS: REVIEW_PASSED

## Goal

主体加固一次到位：内核接口化、单一会话数据源、并发与资源、模型路由与原生通道、
server.py 拆分、错误处理、渠道默认权限、启动速度、无头 CLI、测试分层，
最后用真实模型做 Atlas 冒烟实测。不加新功能，行为默认不变，每项修复带测试。

## First steps

1. H0.1：主机未提交改动原样存到 `wip/host-uncommitted-2026-10-04` 并 push，再从干净 main 开工。
2. H0.2：跑基线脚本。
3. H5 server 拆分先做，然后按任务书第 14 节并行。

## SUBAGENT POLICY — HARD REQUIREMENT

- 用当前 runtime 允许的最大子代理并发，不写死数量；被拒就缩 batch，不退回单线程。
- 热文件单 owner：`server.py`、`engine/hermes_runtime.py`、`agent/__init__.py`、Hermes fork、`backendProcess.ts`。

## Completion

写 `tasks/results/ATLAS-H1-CORE-HARDENING.result.md`，CURRENT 改为 `AWAITING_REVIEW`，
push main，核对本地/远端 head，停。

不得启动 T1 / X6 / R1 / MemoryOS / UI 改版 / 安全审查 / 新上游调研。
