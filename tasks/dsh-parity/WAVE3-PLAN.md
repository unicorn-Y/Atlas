# WAVE 3：收尾剩余 98 条 DSH 差距

**日期**：2026-11-14
**基线**：`2bc3a626`（已关闭 37/135）
**目标**：把 98 条开放项推进到尽可能多的 CLOSED，其余如实定性。

---

## 前两轮的真实教训（本轮必须内化）

| 轮次 | 做法 | 结果 | 教训 |
|---|---|---|---|
| WAVE 1 | 16 worker，按**目录**分批，每批 ≤4 条 | 28/135 | 目录切分导致跨目录能力只能 PARTIAL |
| WAVE 2 | 10 worker，按**能力**分批（给跨目录权限） | 37/135 | V4 一次关 3 条；V1/V6/V7 拿到真实模型证据 |
| **WAVE 3** | **按「可验证单元」分批**，worker 自己决定改哪些文件 | 本轮 | 见下 |

### WAVE 3 的三条新规则

**规则 1：worker 自己声明文件清单，不由我预设。**
每个 worker 开工前必须先输出「我要改这 N 个文件的哪几处」，然后才动手。
理由：前两轮我预设的目录边界多次与实际能力位置不符。

**规则 2：CLOSED 的证据标准按区区分。**
| 区 | CLOSED 需要什么 |
|---|---|
| E / S / X | 单元测试通过 **且** 真实模型回合观测到该行为 |
| D | vitest 通过 **且** TypeScript 0 错误 **且** 组件测试覆盖该行为 |

前端不要求真实模型——WAVE 2 已验证这个标准可行。

**规则 3：HARD 类不派工，我在账本里直接定性。**
以下 10 条不做，写 `HARD(reason)`，不占 worker 时间：
`E1 S1 S2 X1 X5 X6 X7 E14 S30` + `D1`(已部分完成) / `E18`(host 部分)

---

## 模型通道（已实测可用，必须照抄）

```bash
cd core
http_proxy=http://127.0.0.1:7897 https_proxy=http://127.0.0.1:7897 \
  python -m uvicorn atlas.server:app --port <你的端口>
python scripts/dsh_live_ws_check.py <你的端口> "Reply with exactly the word: OK"
```
- 模型 `deepseek-v4.1-flash`，base `https://d1api.xin/v1`
- key 与代理已在系统凭据库，**不需要任何环境变量**
- 期望：`[terminal] run.completed` + `[reply] 'OK'`

**端口分配**：X1=8871 X2=8872 X3=8873 X4=8874 X5=8875 X6=8876（前端批次不需要）

---

## 六批划分（按「一条能力能否被同一个 worker 端到端证明」）

### X1 — 引擎语义补全（`engine/kernel/`, `agent/`）
rows: **E2 E4 E19 E25**
- E2：turn/step 完整生命周期（WAVE 2 V1 已 Live PASS，本轮补 step 级类型与 reason 全枚举）
- E4：逐工具 output schema（WAVE 2 V2 已完成链路，本轮补存量工具语义 schema）
- E19：`concludeTurn`（WAVE 2 V1 已 Live PASS，本轮补与 step 的交互）
- E25：idle maintenance 生产调用点（WAVE 2 V1 只做了 kernel API）

### X2 — 引擎能力扩展（`engine/kernel/`, `agent/`, `engine/tools/`）
rows: **E21 E22 E23 E24 E26 E27**
- E21 会话级工作目录 / E22 Agent Teams 工具化 / E23 workflow 脚本
- E24 ralph 循环 / E26 tools.restrict 作用域 / E27 PTC run_code 模式

### X3 — 上下文与工具治理（`engine/kernel/context.py`, `tools.py`, `stuck.py`）
rows: **E28 E29 E30 E31 E32 E33 E34 E35 E36**
- E28 压缩区域安全 / E29 tokenMeter / E30 LSP provider registry
- E31 会话查询五工具 / E32 worktree pinned revision / E33 写路径诊断（已 STRONGER）
- E34 取消合成结果 / E35 压缩 lock bracket / E36 后台通知 followup

### X4 — 会话持久化补全（`engine/state/`, `session_sync.py`）
rows: **S5 S7 S8 S9 S12 S14 S17 S18 S20 S23 S24 S26 S27 S29 S31 S33**
- S5 handle 式持久化 / S7 压缩 bracket / S8 压缩策略 / S9 剪枝重放
- S12 投影持久缓存 / S14 查询工具 / S17 导出 ZIP / S18 spill 缝
- S20 deliverables / S23 session telemetry / S24 product telemetry
- S26 官方 API 上传 / S27 skill provider / S29 session 引用 / S31 统计投影 / S33 尝试级可观测

### X5 — 扩展层补全（`plugins/`, `skills/`, `tools/mcp_client.py`, `automation/`）
rows: **X2 X3 X4 X8 X9 X10 X11 X21 X27 X24 X12 X13 X15 X18 X19 X20 X25 X26 X30 X31 X32 X33**
- X2 async MCP disposer（WAVE 2 已 CLOSED，复核）/ X3 plugin 管理 / X4 profile bundle
- X8 preset realm 接入 / X9 ACP preset / X10 plugin_manager 工具 / X11 bundle 清单
- X21 MCP instructions（已改）/ X27 节点注册表 / X24 ACP 完整 / X12 X13 hooks
- X15 skill 阶梯 / X18 provider 协议 / X19 新鲜度 / X20 依赖门
- X25 SDK settle barrier / X26 typed gateway / X30 SSH 缝 / X31 schedule 原会话
- X32 组合自省 / X33 agent provider 缝

### X6 — 桌面端收尾（`frontend/src/`, `backend-adapter/`）
rows: **D3 D4 D5 D6 D8 D10 D11 D12 D15 D16 D17 D18 D19 D20 D21 D22 D23 D24 D25 D26 D27 D28 D29 D30 D31 D32 D33**
- 注意：D25(re误) D31(多窗口) D32(消息操作) 是 **Atlas 已更强**，只加回归测试，不改实现
- 其余按 WAVE 2 的标准：vitest + TS 0 错误 + 组件测试

---

## 每批交付物

1. 开工时先输出「文件清单 + 每处改什么」
2. 更新 `docs/parity/DSH-GAP-LEDGER.md` 对应行状态
3. 写 `tasks/dsh-parity/waves/RESULT3-<批号>.md`：逐条 CLOSED/PARTIAL/NOT-DONE + 证据
4. commit 到自己的分支

## 禁止

- 不许把「写了代码」当 CLOSED
- 不许把「测试通过」当「功能可用」
- 不许在 RESULT 里写「已实现」而不贴命令输出
- 不许跨 worker 抢文件（开工前声明清单，冲突由我仲裁）

---

## 附：HARD 类定性（不派工，直接写入账本）

| row | 定性 | 原因 |
|---|---|---|
| E1 / S1 / S2 | HARD | 事件日志作为模型历史真源。压缩/rewind 靠 `UPDATE active=0`，不发事件，等价不可达（WAVE 1 评审已论证） |
| X1 | HARD | Cordis 式服务组合根。需重构 52 字段 `AppServices` + 79 router |
| X5 / X6 / X7 | HARD | 插件依赖解析/版本豁免/安装审批。需包管理器语义 |
| E14 / E18(host) | HARD | Windows per-call OS sandbox。需 Job Object/AppContainer 执行器；Docker Engine 当前不可用 |
| S30 | HARD | DeepSeek 官方 API 会话日志上传。需官方契约 |
