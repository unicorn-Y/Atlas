# DSH 剩余差距：细粒度并行派工（第 2 轮）

上一轮教训（必须避免）：
1. 每批 12 条太大 → worker 只能交中间版本。**本轮每批 ≤ 4 条。**
2. 按概念分类而非目录 → worker 严守文件边界只能标 PARTIAL。**本轮按目录派工。**
3. 有些条目不是「接线」而是「新工程」→ 被混在普通批次里。**本轮单列 HARD 类。**

## 状态基线

Codex 自报：**135 行中 24 行 CLOSED，111 行开放**。
本文件把 111 条拆成可并行的小批次。

## 硬规则（同上一轮，全部适用）

- 不重写 `messages` 表语义
- 不在 `_execute_write` 回调里再调 `_execute_write`（死锁）
- 事件名三处真源同步：`event_names.py` / `runtimeEvents.ts` / `runtime.ts`
- 新 router 进 `application.py` 的 tuple；新 service 进 `AppServices` + lifespan
- 测试必须 `@pytest.mark.unit` 或 `integration`
- **CLOSED 的唯一标准**：端到端测试通过 + 真实进程证据。只写代码不算。

## 基线已知失败（不许修，不许算你的回归）

`test_route_snapshot.py`(2)、`test_c4_plugin_e2e.py`(1)、
`test_atlas_mcp_config.py::test_compaction_agent_pins_bare_wire_id_from_host_shaped_config`、
`test_session_migration.py`(7)、`test_mcp_client.py`/`test_mcp_lifecycle_shutdown.py`(若干)

## 真实模型验证

```bash
cd core
python -m uvicorn atlas.server:app --port <你的端口，避开 8765>
python scripts/dsh_live_ws_check.py <你的端口> "Reply with exactly the word: OK"
```
模型 `deepseek-v4.1-flash` @ `https://d1api.xin/v1` 经 Clash `127.0.0.1:7897`。
**key 与代理已在系统凭据库，不需要环境变量。**
每个 worker 用**不同端口**（8820/8821/8822...），不要碰 8765（桌面端在用）。

---

# 批次划分（按目录所有权）

## W1 — kernel 生命周期（`core/atlas/engine/kernel/loop.py`, `state.py`）
rows: E2, E19, E25
- E2: 完整 turn/step 两级生命周期 + typed turn-end reason
- E19: `concludeTurn()` 工具可声明本轮结束
- E25: idle-only maintenance slot

## W2 — kernel 工具契约（`core/atlas/engine/kernel/tools.py`, `tool_finalize.py`, `engine/tools/registry.py`）
rows: E3, E4
- E3: 三瀑布 pre/post-execute/result + typed decision
- E4: 强制 output schema + render + presentationMeta，成功即校验

## W3 — kernel 上下文与 token（`core/atlas/engine/kernel/context.py`, `engine/agent/token_meter.py`）
rows: E8, S9, S25
- E8: step 边界压缩 + 溢出重试代次守卫
- S9: 工具结果遮蔽替换 + resume 重放
- S25: per-node token pricing

## W4 — agent 委派与 goal（`core/atlas/agent/`, `engine/goals.py`）
rows: E11, E17
- E11: goal revision CAS + 默认轮数上限
- E17: subagent fork child（继承父前缀）+ persona

## W5 — 状态层持久化（`core/atlas/engine/state/`）
rows: S4, S19, S21
- S4: reader-side repair closer（不重写 transcript）
- S19: durable image attachment
- S21: session-scoped filesystem observation

## W6 — 状态层可观测（`core/atlas/engine/state/`, `telemetry.py`）
rows: S16, S22
- S16: turnOutline 投影真正注册（`atlas_state_timeline.py` 目前是死代码）
- S22: OTel span 真实调用点（`span()` 现在零生产调用）

## W7 — 沙箱与执行（`core/atlas/sandbox.py`, `engine/tools/environments/`）
rows: E14, E18
- E14: per-call sandbox mode + enforcement reporting
- E18: per-call escalation with justification
- **注意：Windows host 没有通用 per-call OS sandbox。如确实做不了，如实标 PARTIAL 并说明缺什么。**

## W8 — 后台作业（`core/atlas/engine/kernel/exec.py`, `background_tasks.py`）
rows: E16
- E16: 统一 job registry（shell/subagent/workflow 共用）+ byte-capped rings

## W9 — 插件层（`core/atlas/plugins/`）
rows: X2, X4, X8
- X2: 所有 plugin 贡献的 disposer（含 async MCP lifecycle）
- X4: profile/bundle 有序层 + row-id patching + dump 预览
- X8: preset isolate realm + 子插件行能力

## W10 — 技能层（`core/atlas/skills/`, `library/`）
rows: X16
- X16: `/name` 内联注入 + 摘要 diff 交付

## W11 — MCP 与外部入口（`core/atlas/tools/mcp_client.py`, `automation/`）
rows: X23, X9
- X23: MCP server scope 真正被 agent/session 使用
- X9: ACP 入口接 preset

## W12 — 前端核心（`frontend/src/renderer/`）
rows: D1, D2, D3
- D1: OS 分配端口 + boot injection
- D2: typed host IPC lifecycle
- D3: per-node incremental projection（去掉全量重建）

## W13 — 前端渲染（`frontend/src/renderer/components/`）
rows: D4, D30
- D4: keyed ConversationNode renderer 注册表（移除中央 switch）
- D30: Chat/Trajectory 双态同一视图切换

## W14 — 前端输入与附件（`frontend/src/renderer/`）
rows: D5, D6
- D5: durable attachment staging + 进度 + 取消
- D6: 结构化 composer 草稿（chip 进文本模型）

## W15 — 前端布局与连接（`frontend/src/renderer/`）
rows: D7, D8
- D7: follow-with-baseline 重连 + 序列缺口修复
- D8: 右侧栏 split 树 + 浮动面板 + 可插 tab

## W16 — 前端其余（`frontend/src/`, `core/atlas/api/`）
rows: D10, D13, D17
- D10: 自动更新调度 + 退避 + journal
- D13: `present` 交付物工具 + 卡片
- D17: 命名空间 i18n

---

# HARD 类：不是接线，是新工程（单独立项，不计入普通批次）

| row | 为什么是 HARD | 需要什么 |
|---|---|---|
| E1 | 只追加事件日志作为模型历史真源 | 需重写 `session_sync` + `atlas_state_messages` 的读取路径，并证明与现有路径等价。**上一轮已论证：压缩/rewind 不发事件，等价不可达**。需先解决事件覆盖问题。 |
| S1 | 同上 | 同上 |
| S2 | surface replace 折叠 | 依赖 E1 |
| X1 | Cordis 式服务组合根 | 需重构 52 字段 `AppServices` + 79 个 router 的装配方式 |
| X5 | 插件依赖解析 + 回滚 + 取消 | 需引入包管理器语义，不是接线 |
| X6 | 插件版本兼容与豁免 | 依赖 X5 |
| X7 | 安装脚本审批门 | 依赖 X5 |
| E14/E18 | Windows per-call OS sandbox | 需真正的进程隔离执行器（Job Object / AppContainer），是独立子系统 |
| S30 | DeepSeek 官方 API 会话日志上传 | 需官方 API 契约，Atlas 无此依赖 |

**HARD 类的处理方式**：不派给普通 worker。由我单独评估，能做的拆成独立项目，不能做的写进 `WONTFIX(reason)`。

---

# 每批的交付要求

1. 该批 rows 逐条更新 `docs/parity/DSH-GAP-LEDGER.md` 的状态列
2. 新增测试，跑通并贴出真实输出
3. 该批完成后写 `tasks/dsh-parity/waves/RESULT-<批号>.md`：
   - 逐条 CLOSED / PARTIAL(原因) / NOT-DONE(原因)
   - 改了哪些文件
   - 测试命令 + 真实输出
   - 真实模型回合输出（如果该批涉及运行路径）
4. **不许写「已实现」而没有贴输出**
