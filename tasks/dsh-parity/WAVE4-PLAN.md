# WAVE 4：ZCode 多 agent 并行收尾

**基线**：`4b31748d` 之后（40/135 关闭，29.6%）
**剩余**：95 条开放，其中 87 条可做，8 条 HARD

## 前几轮的核心教训（本轮回内化）

1. **WAVE 1**（按目录分批）→ 28/135，跨目录能力全 PARTIAL
2. **WAVE 2**（按能力分批，给跨目录权限）→ 37/135，V4 一次关 3 条
3. **WAVE 3**（worker 自声明文件清单 + 子代理并行）→ 40/135，但仍有大量 PARTIAL
4. **WAVE 4 的关键判断**：剩下的 PARTIAL 绝大多数是**同一个模式**——
   「基础设施已有，缺暴露成模型可见能力 / 缺真实模型证据」。

## WAVE 4 的策略：不做新原语，只做「暴露 + 证据」

对每一条 PARTIAL，只允许两种动作：
- **A. 暴露**：把已有实现接到模型可见面（工具注册、prompt 段、事件、API 路由）
- **B. 取证**：真实模型回合跑一次，证明它真的工作

**禁止**新建底层能力。如果发现某条真的缺底层，标 `HARD(detail)` 而不是硬写。

## 六个并行 agent（每个带自己的子代理）

| Agent | 域 | rows | 主要工作 |
|---|---|---|---|
| **Z1** | 引擎工具面 | E4 E22 E24 E26 E27 E19(已闭) | 把已有实现暴露成模型工具：Agent Teams、ralph、tools.restrict、PTC |
| **Z2** | 引擎上下文 | E28 E29 E31 E32 E33 E34 E35 E36 | 压缩/token/LSP/会话查询/worktree 的接线与取证 |
| **Z3** | 会话持久化 | S5 S7 S8 S9 S12 S14 S15 S16 S17 S18 | handle API、压缩 bracket、投影缓存、统计、导出 |
| **Z4** | 会话可观测 | S20 S22 S23 S24 S25 S26 S27 S28 S29 S31 S33 | deliverables、telemetry、skill provider、session 引用 |
| **Z5** | 扩展层 | X2 X3 X4 X8 X9 X10 X11 X21 X24 X27 | 插件管理层、preset realm、ACP、MCP instructions |
| **Z6** | 扩展+桌面 | X12 X13 X15 X18 X19 X20 X25 X26 X30 X31 X32 X33 | hooks、skill 协议、SDK、SSH、schedule、自省 |
| **Z7** | 桌面端 | D3 D5 D6 D8 D10 D11 D12 D15 D16 D17 D18 D19 D20 D21 D22 D23 D24 D25 D26 D27 D28 D29 D30 D31 D32 D33 | 前端收尾；D25/D31/D32 只加回归测试 |

## 验收标准（按区，与前几轮一致）

| 区 | CLOSED 需要 |
|---|---|
| E / S / X | 单元测试通过 **且** 真实模型回合观测到该行为 |
| D | vitest 通过 **且** TS 0 错误 **且** 组件测试覆盖该行为 |

## 真实模型通道（已验证）

```bash
cd core
http_proxy=http://127.0.0.1:7897 https_proxy=http://127.0.0.1:7897 \
  python -m uvicorn atlas.server:app --port <端口>
python scripts/dsh_live_ws_check.py <端口> "Reply with exactly the word: OK"
```
模型 `deepseek-v4.1-flash` @ `https://d1api.xin/v1`，key 在系统凭据库。

**端口分配**：Z1=8881 Z2=8882 Z3=8883 Z4=8884 Z5=8885 Z6=8886（Z7 前端不需要）

## 硬规则（违反则改动作废）

1. 不重写 `messages` 表语义
2. 不在 `_execute_write` 回调里再调 `_execute_write`（死锁）
3. 事件名三处真源同步
4. 测试需 `@pytest.mark.unit` / `integration`
5. 不许把「写了代码」当 CLOSED；RESULT 必须贴真实命令输出
6. 只改自己 worktree 内的文件

## 交付

1. 开工先输出「rows → 动作（暴露/取证/两者）→ 文件清单」
2. 写 `tasks/dsh-parity/waves/RESULT4-<Z>.md`
3. commit 到自己的分支

## HARD 类（不派工，直接定性）

`E1 S1 S2 X1 X5 X6 X7 E14 S30` — 需独立工程，写 `HARD(reason)` 结案。
