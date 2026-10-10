# Atlas Current Task

> **唯一入口**：任何 agent / session 接手工作前，先读本文件，再读 `STATE_SOURCE`。
> 不要再新建并列的 `*-CURRENT.md`；"当前任务"只在这里和 `STATE_SOURCE` 声明。

ACTIVE_TASK: ATLAS-MEMORY-MEMOS
BRANCH: memory-v1
ENGINE: vendor/memos-local-plugin   # MemOS 2.0.20 的 Atlas fork，改动见 ATLAS_FORK.md
LAST_PUSH: atlas 43ac3156 (2026-10-10)

## Active

**记忆 = 唯一引擎 MemOS（记忆张量）的 Atlas fork。**2026-10-10 用户决定：不再维护自写的
MemoryOS / MEMORY-V1，把各家做得最好的部分并进这一个引擎，每步交付用户能亲手试的东西。

| 块 | 状态 |
|---|---|
| MemOS 接入 Atlas（Hermes 记忆插件）、记忆变动页、暂停、删记录/归档技能 | 完成（a66de15…6a0fe98） |
| 策略、世界模型可删除 | 完成（e61749f8） |
| fork 进仓库 + 中文事实规则进源码 + 「关于你」事实层（带原话出处、改口保留历史、每轮注入） | 完成，真实模型冒烟 7/7（f7196af5、43ac3156） |
| 到点提醒接回（V1 意图桥 → MemOS 事实/对话） | 待做 |
| 技能验证（微软 SkillOpt）+ 失败总结（ACE） | 待做 |
| 矛盾处理与过期淡忘（参考 Supermemory） | 待做 |

MEMORY-V1（`docs/plan/MEMORY-V1/`）与 MemoryOS 服务：**已退役**，代码保留作参考，不再施工。

## 历史（已结束，不再是当前任务）

- `ATLAS-MEMORY-V1` — 2026-10-10 退役（S0–S6 待审、S8 21/30），由 MemOS fork 取代。

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
