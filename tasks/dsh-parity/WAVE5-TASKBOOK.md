# WAVE 5 任务书（可直接粘贴到新会话）

> 这份文件是给你（新会话的 ZCode agent）的完整任务说明。
> 读完即可开工，不需要问我任何问题。

---

## 0. 你的身份与目标

你是 Atlas 项目的收尾施工负责人。Atlas 是一个本地优先的个人 AI 助手
（Python FastAPI 后端 `core/atlas/`，Electron+React 桌面端 `frontend/`）。

**当前目标**：把 `docs/parity/DSH-GAP-LEDGER.md` 里剩下的 **44 条**差距
（11 条 HARD + 33 条 PARTIAL）尽可能推进到 CLOSED，其余如实定性。

**基线**：分支 `wave3`，HEAD `657414b5`，已关闭 **91/135（67.4%）**。

---

## 1. 必读文件（按顺序）

1. `D:\Atlas\AGENTS.md` — 仓库地图与禁区。**违反里面的禁区等于任务失败。**
2. `D:\Atlas\docs\parity\DSH-GAP-LEDGER.md` — 135 条差距的完整账本，每条都有
   DSH 侧 `path:line` 证据和 Atlas 侧现状。
3. `D:\Atlas	asks\dsh-parity\COVERAGE-FINAL.md` — 覆盖率与证据质量审计。
4. `D:\Atlas	asks\dsh-parity\WAVE4-PLAN.md` — 上一轮的策略（本轮沿用）。

---

## 2. 硬规则（违反即作废）

### 2.1 数据安全
- **绝不重写 `messages` 表语义**。16 个 mixin、FTS 触发器、压缩、rewind、fork、
  导出、迁移全依赖它。只能**旁路新增**，不能替换。
- **`SessionDB._execute_write` 持有不可重入的 `threading.Lock`**
  （`core/atlas/engine/state/atlas_state.py:598`）。在它的回调里再调它会**死锁**；
  在里面开第二个 `SessionDB` 会等 21 秒后抛 `database is locked`。
  要在事务内写，只能用回调传给你的那个 cursor。
- **不要改** `config/atlas.toml`、`data/user-settings.json`（含真实密钥）、
  `data/memory/**`（用户真实记忆，独立 git 库）。

### 2.2 三处真源必须同步
新增/改名事件时，同一次改动里必须同时改：
1. `core/atlas/api/event_names.py`
2. `frontend/src/renderer/services/runtimeEvents.ts`（`known` 集合）
3. `frontend/src/types/runtime.ts`（`AgentEventType`）

漏第 2 步的后果是**静默丢弃**（`normalizeRuntimeEvent` 末尾 `return null`），
不是报错。改完跑 `python -m pytest -q tests/test_event_contract.py`。

### 2.3 接线三件套
- 新 router → 加进 `core/atlas/api/application.py:135` 那个 tuple
- 新 service → 加进 `AppServices`（`core/atlas/api/app_services.py`）+ 在
  `server.py` 的 lifespan 里填充
- 新工具 → 加进 `core/atlas/agent/tool_catalog.py` 与
  `core/atlas/engine/kernel/tool_pruning.py` 的家族映射

### 2.4 测试
- 必须标 `@pytest.mark.unit` 或 `@pytest.mark.integration`，
  否则被 `addopts = "-m unit"` 静默 deselect（看起来通过，实际一条没跑）。

---

## 3. 本轮策略：只做「暴露 + 取证」，不做新原语

前四轮的经验：绝大多数 PARTIAL 是**基础设施已有但没接到模型可见面**。

对每一条，只允许三种动作：

| 动作 | 含义 |
|---|---|
| **A. 暴露** | 把已有实现接到模型可见面（工具注册、prompt 段、事件、API 路由、CLI） |
| **B. 取证** | 真实模型回合跑一次，证明它真的工作 |
| **C. 降级** | 确认真的缺底层，标 `HARD(具体缺什么)`，**不要硬写死代码** |

**禁止**为了凑 CLOSED 而新建一套底层能力。

### CLOSED 的证据标准（按区区分）

| 区 | CLOSED 需要 |
|---|---|
| E / S / X | 单元测试通过 **且** 真实模型回合观测到该行为 |
| D（前端） | `npx vitest run` 通过 **且** `npx tsc --noEmit` 0 错误 **且** 组件测试覆盖该行为 |

**前端不要求真实模型**——上一轮已验证这个标准可行。

---

## 4. 剩余 44 条的分布

### 4.1 HARD 类（11 条）— 先评估，别硬做

```
E1  E14 E18  S1  S2  S30  X1  X5  X6  X7  X26
```

这些**大概率做不了**，原因：

| row | 为什么 HARD | 你要做的 |
|---|---|---|
| E1 / S1 / S2 | 事件日志作为模型历史真源。压缩和 rewind 靠 `UPDATE active=0` 实现，**不发事件**，等价不可达（WAVE 1 评审已论证） | 若你能设计出「事件覆盖 active 变更」的可行方案，可以尝试；否则标 `HARD(unreachable without redesign)` |
| X1 | Cordis 式服务组合根。需重构 52 字段 `AppServices` + 79 个 router 的装配 | 只做**可行性评估**，除非你能在不破坏现有测试的前提下逐步迁移 |
| X5 / X6 / X7 | 插件依赖解析、版本豁免、安装脚本审批。需包管理器语义 | 标 `HARD(needs package-manager semantics)` |
| E14 / E18 | Windows per-call OS sandbox。需 Job Object / AppContainer 执行器。Docker Engine 当前不可用（`Server: null`） | 标 `HARD(needs OS sandbox executor)` |
| S30 | DeepSeek 官方 API 会话日志上传。需官方公开契约（DSH 用的是自有 wire extension） | 标 `HARD(no public contract)` |
| X26 | typed Client↔Host gateway。需装饰器生成描述符/编解码/客户端类型 | 评估工作量后再定 |

**HARD 类的正确做法**：读代码确认它到底缺什么，然后在账本里写一句具体的
`HARD(<缺什么>)`，**不要花时间写半成品**。

### 4.2 PARTIAL 类（33 条）— 主战场

按主题分组，建议每组分给一个子代理并行：

**A 组 · 引擎（12 条）**
`E21 E23 E25 E28 E29 E30 E31 E32 E33 E34 E35 E36`
- E21 会话级工作目录 / E23 workflow 脚本 / E25 idle maintenance 生产接线
- E28 压缩区域安全 / E29 tokenMeter provider 锚定 / E30 LSP provider registry
- E31 会话查询五工具（注意：`session_queries` 已实现但**只在 legacy 路径**，
  kernel `_dispatch` 没有分支——这是典型的「暴露」任务）
- E32 worktree pinned revision / E33 写路径诊断（已 STRONGER，只需回归测试）
- E34 取消合成结果（已等价，核对）/ E35 压缩 bracket / E36 后台通知 followup

**B 组 · 会话（12 条）**
`S10 S20 S22 S23 S24 S25 S26 S27 S28 S29 S31 S33`
- S20 `present` 工具被 `select_tools_for_tier` 剪掉（三档都剪）——这就是
  W3 真实回合没调用它的原因，是纯暴露任务
- S22 OTel 双通道 / S23 session telemetry ledger / S24 product telemetry
- S25 route-aware 图像计价（`price_surface_nodes` 已支持 `image_pricing` 参数，
  但 `loop.py:2192` 调用时没传）
- S26 → HARD / S27 skill provider 协议 / S28 标题 refresh 解钉
- S29 `@session` 引用（现在只拼字符串，无 untrusted 包裹）
- S31 sessionStats / S33 失败尝试的 durable 内容

**C 组 · 扩展（4 条）**
`X8 X14 X18 X24`
- X8 `PluginRealm` 挂在 `run_phases.py:351` 但**没有任何消费方**——纯暴露
- X14 / X18 / X24 按账本描述处理

**D 组 · 前端（5 条）**
`D1 D2 D7 X27`
- D1 OS 分配端口 + boot injection（改动落在 `frontend/src/main/`）
- D2 typed host IPC lifecycle
- D7 follow-with-baseline 重连 + 序列缺口修复
- X27 `timeline.ts` **从不产出 `kind: 'extension'`**，扩展节点不可达——纯暴露

---

## 5. 真实模型验证（照抄执行）

```bash
cd D:\Atlas\core
# 注意：必须先设代理环境变量，否则会报「模型代理凭据缺失」
http_proxy=http://127.0.0.1:7897 https_proxy=http://127.0.0.1:7897   python -m uvicorn atlas.server:app --port 8890
```

另开一个 shell：
```bash
cd D:\Atlas\core
python scripts/dsh_live_ws_check.py 8890 "Reply with exactly the word: OK"
```

**期望输出**：
```
[terminal] run.completed data={"result": "completed", "model": "deepseek-v4.1-flash", ...
[reply] 'OK'
```

**如果看到 `request_count: 0`**，说明模型没被调用，检查：
1. 代理环境变量设了吗
2. 凭据库里 `atlas.model_network.proxy_url` 在不在
   （`python -c "import keyring;print(keyring.get_password('Atlas','atlas.model_network.proxy_url'))"`）

**每个 worker 用不同端口**（8890/8891/8892…），**不要碰 8765**（桌面端在用）。

---

## 6. 并行方式

**用 `subagent_type: glm-flash` 或 `router-glm-5-3-flash` 启动子代理**，
不要用 `general-purpose`（那会跑在主会话的付费模型上）。

如果启动时报 `provider-not-found`，说明 ZCode 还没重载配置——
告诉用户重启 ZCode 并重新登录后再说。

**建议 4 个子代理并行**（A/B/C/D 四组），每个独立 worktree：

```bash
cd D:\Atlas
git worktree add -b wave5-a .worktrees/w5-a wave3
git worktree add -b wave5-b .worktrees/w5-b wave3
git worktree add -b wave5-c .worktrees/w5-c wave3
git worktree add -b wave5-d .worktrees/w5-d wave3
```

---

## 7. 交付要求

每个 worker 完成后写 `tasks/dsh-parity/waves/RESULT5-<组号>.md`，必须包含：

1. 逐条 `CLOSED` / `PARTIAL(原因)` / `HARD(缺什么)` / `NOT-DONE(原因)`
2. 改了哪些文件
3. **测试命令 + 真实输出**（不许写「已通过」而不贴输出）
4. 真实模型回合输出（若该条涉及运行路径）

全部合并后写 `tasks/dsh-parity/COVERAGE-WAVE5.md`：135 行逐条状态，
**不许留空、不许 TBD**。

---

## 8. 禁止事项

- ❌ 把「写了代码」当 CLOSED
- ❌ 把「测试通过」当「功能可用」
- ❌ 在 RESULT 里写「已实现」而不贴命令输出
- ❌ 为了凑数把 PARTIAL 说成 CLOSED
- ❌ 跨 worktree 改别人的文件
- ❌ 硬写一个新原语然后标 CLOSED 却没有调用方

---

## 9. 上一轮踩过的坑（避免重复）

| 坑 | 后果 | 怎么避免 |
|---|---|---|
| 按目录划分子代理 | 跨目录能力只能 PARTIAL | 按**能力**分组，一个 worker 拥有该能力跨越的所有目录 |
| 子代理用 `general-purpose` | 跑在父会话付费模型上 | 必须用 `glm-flash` / `router-glm-5-3-flash` |
| Codex hook exit 2 被当阻断 | 每轮 prompt 被拦，模型从未调用 | 已修（`hooks.py`），但改 hook 相关代码时注意 |
| 账本审计脚本解析错行尾 `|` | 报出 99 而非 91 | 用 `re.match(r'^\|\s*(\w+)\s*\|(.*)\|\s*$')` |
| 合并时工作区脏 | merge 静默失败 | 合并前 `git status --short` 必须为 0 |

---

## 10. 开始

1. 读第 1 节列的 4 个文件
2. 确认 `git status --short` 为空、`git log -1` 是 `657414b5` 或其后
3. 建 4 个 worktree
4. 用 `glm-flash` 启动 4 个子代理
5. 开工
