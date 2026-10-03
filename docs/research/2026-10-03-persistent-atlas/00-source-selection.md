# Persistent Atlas / Always-On 最新来源选择（2026-10-03）

> 本文件记录任务书生成时的最新调研结论。真正开工时必须重新 fetch 一次并写入 taskbook result 的 source-freeze；本页只作为为什么选这些来源的依据。

## 当前观察到的 HEAD

| 项目 | HEAD | 用途 |
|---|---|---|
| OpenClaw | `899a0ca6814f02da84938c3d2b6af5e3b6dedf04` | persistent gateway、多 Agent routing、heartbeat、cron/automation、node/paired-machine、Computer Use 的设备归属 |
| NousResearch/hermes-agent | `c8301ea6c9b797184df16a9c5dd462400b264ff4` | Bot Mode/Bot UI、群聊、Cron 产品面、中国渠道 adapters、managed llama.cpp/local runtime、Bot Screen UX |
| dbos-inc/dbos-transact-py | `03fb5c92cde8e107ff333cd2b419f65e02719e99` | durable workflow / queue / recovery / schedule execution |
| Atlas | `main` 当前已完成 Mega Latest-Daily-Ready | 保留现有 Hermes core、X2、X4、X5、Scheduler/Goal/session/runtime，不重造 |

## 逐块冠军

### 1. 长期 Agent / 多 Agent

**架构语义优先：OpenClaw。**

直接研究：
- `src/agents/**`
- `src/gateway/**`
- `docs/gateway/config-agents/**`
- agent entries / per-agent identity / channel binding / workspace/session isolation

产品交互直接参考 Hermes：
- `apps/desktop/src/plugins/hermes-bots/**`
- 尤其 `group-chat*.tsx`、`data.ts`、Bot create/edit/roster/identity/cron 相关文件

Atlas 落点：现有 Profile/child-agent/session/runtime 扩展成 persistent agent，不引入第二 Agent core。

### 2. Gateway / 渠道

**Gateway lifecycle/routing：OpenClaw。**

研究：
- `src/gateway/**`
- `packages/gateway-protocol/**`
- channel/plugin routing / reconnect / ownership / liveness

**可直接搬的 Python 渠道：Hermes。**

优先：
- `plugins/platforms/telegram/**`
- `plugins/platforms/slack/**`
- `plugins/platforms/feishu/**`
- `plugins/platforms/dingtalk/**`
- `plugins/platforms/wecom/**`

再接 Email/Webhook；其他渠道通过统一 channel plugin contract 后续按需启用。

不要把 OpenClaw 的完整 agent runtime 嵌进 Atlas；只吸收 gateway 协议/状态机/路由语义。

### 3. Heartbeat / 主动性

**OpenClaw。**

核心源码：
- `src/infra/heartbeat-runner*.ts`
- `src/infra/heartbeat-*.ts`
- `src/cron/heartbeat-*.ts`
- `src/gateway/server-chat-heartbeat.ts`
- `docs/gateway/heartbeat.md`

要吸收的不是 TS 外壳，而是状态机：
active hours、cooldown、busy guard、event wake、restart continuation、delivery target、no-change/no-notify、isolated session、per-agent heartbeat。

### 4. 自动化 / Cron

最强组合：

- **DBOS**：durable execution / queue / recovery；
- **OpenClaw**：cron/heartbeat 的持久化、恢复、delivery/ownership 语义；
- **Hermes**：Agent-facing cron API/UI、no-agent/script、skills、消息投递产品体验。

OpenClaw 重点：
- `src/cron/**`
- `src/agents/tools/cron-tool*.ts`
- `packages/gateway-protocol/src/schema/cron*.ts`
- `docs/automation/cron-jobs/**`

Hermes 重点：
- `cron/**`
- `apps/desktop/src/app/cron/**`
- `apps/desktop/src/plugins/hermes-bots/cron*.tsx`
- `hermes_cli/cron.py`

DBOS 重点：
- Python workflows/queues/schedules/recovery public API；Atlas 已经有 DBOS，优先接现有 backend，不建立第二 durable layer。

### 5. Atlas 自己的 Windows 电脑 / Node

**OpenClaw node/placement 语义 + Atlas X2 Windows runtime + Hermes Bot Screen UX。**

OpenClaw：
- `src/agents/session-placement-computer.ts`
- `src/agents/tools/computer-tool-*.ts`
- `src/gateway/desktop/computer-owner.ts`
- `src/gateway/desktop/computer-process*.ts`
- `packages/gateway-protocol/src/schema/computer.ts`
- paired node / presence / device auth / reconnect 相关 gateway 模块

Hermes UI：
- `apps/desktop/src/plugins/hermes-bots/screen-*.tsx`
- `website/docs/user-guide/features/bot-screen.md`

Atlas 不搬 Hermes 的 Linux Xfce desktop backend。笔记本本身就是 Atlas 的机器，继续用 X2 的 Windows Computer/Browser。

### 6. 本地模型 Runtime

**主体直接用 Hermes managed local runtime。**

直接复用：
- `hermes_cli/local_runtime/**`
- `hermes_cli/web_routers/local_models.py`
- `website/docs/user-guide/local-models.md`

能力包括 runtime 安装、硬件探测、CUDA/Vulkan/HIP/CPU、GGUF/HF、下载、量化/fit/context plan、supervisor、idle unload、恢复。

额外吸收 OpenClaw：
- managed llama.cpp Windows 启动/VC runtime 兜底；
- activation 时不只 health check，还跑一次真实 tool-call capability probe。

LM Studio/Ollama 保持外部 provider；不重写它们。

### 7. Skills 自学习

保留 Atlas X4/X5 单一 SkillRegistry/curator。

继续吸收：
- OpenClaw Skill Workshop 的 proposal/pending/diff/approval/rollback/agent-owned collections/watchers；
- Hermes curator/background-review 能直接复用的部分。

任何生成/录制/市场/项目/plugin skill 都必须回到同一 Atlas SkillRegistry，不出现第二 registry。

## 总原则

- 最新 ≠ 盲跟版本号；只拿当前更强的实现。
- 同语言/低耦合优先直接 port；跨语言高耦合只 port 状态机/协议，不手写缩水版。
- Hermes fork 已有代码优先直接 import/adapter，不复制第二份。
- OpenClaw 不作为第二 Agent core 嵌入 Atlas。
- DBOS 不成为第二 Scheduler UI；只做 durable execution engine。
