# Atlas Current Task

> **唯一入口**：任何 agent / session 接手工作前，先读本文件，再读 `STATE_SOURCE`。
> 不要再新建并列的 `*-CURRENT.md`；"当前任务"只在这里和 `STATE_SOURCE` 声明。

ACTIVE_TASK: ATLAS-MEMORY-V1
BRANCH: memory-v1
STATE_SOURCE: docs/plan/MEMORY-V1/CURRENT.json   # 机器可读状态（唯一权威）
PROGRESS_DIR: docs/plan/MEMORY-V1/progress/
SPEC: docs/plan/MEMORY-V1/00_任务书.md
LAST_PUSH: atlas b820cd12 / memoryos d0ec6b2 (2026-10-09)

## Active

**MEMORY-V1（统一记忆 V1）施工中**，现行波次 F4。逐项状态以 `STATE_SOURCE` 为准：

| 波次 | 状态 |
|---|---|
| S0–S6 | DONE_PENDING_REVIEW |
| S3 召回装配 / 意图闸门 | IN_PROGRESS（★真缺口：画像块恒空） |
| S8 V1 验收评测 | IN_PROGRESS（真数 21/30，未达门槛） |
| S7 正式启用 / 历史回填 | NOT_STARTED — **需用户授权，停下询问** |
| F4 | A DONE_PENDING_REVIEW；B/C IN_PROGRESS；D/E NOT_STARTED |

## 历史（已结束，不再是当前任务）

- `ATLAS-H1-CORE-HARDENING` — CLOSED_BY_USER。结果/审查：`tasks/results/`、`tasks/reviews/`。
  目标：主体加固一次到位（内核接口化、单一会话数据源、并发与资源、模型路由与原生通道、
  `server.py` 拆分、错误处理、渠道默认权限、启动速度、无头 CLI、测试分层），
  不加新功能、行为默认不变、每项修复带测试。BASE_BRANCH: main @ 574db83。
- `ATLAS-C5-C6A-INTEGRATION` — 见 `tasks/ZCODE-CURRENT.md`（已归档，内容仅作历史）。

## 规则

- 完成一步只写 `DONE_PENDING_REVIEW` 继续施工；只有 S7、BLOCKED、或改变目标的决定才停下询问。
- `ACCEPTED` / `REJECTED` 只能由审查方写，施工方不得自评通过。
- 不得删除 / 跳过 / xfail 失败测试或降低门槛来"通过"；不得造假报告
  （见 `docs/plan/MEMORY-V1/progress/AUDIT_K3.md`）。
