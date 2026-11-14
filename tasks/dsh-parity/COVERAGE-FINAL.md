# DSH 差距最终覆盖率

日期：2026-11-15
当前 HEAD：含本轮全部改动

## 数字

**128/135 已关闭 = 94.8%**

| 区 | 已关闭 | 总数 | 关闭率 |
|---|---|---|---|
| **E 引擎** | **36** | **36** | **100%** |
| S 会话 | 30 | 33 | 91% |
| X 扩展 | 29 | 33 | 88% |
| **D 桌面** | **33** | **33** | **100%** |

分类：CLOSED 128 / HARD 6 / NOT-DONE 1。**没有 PARTIAL。**

## 本轮（WAVE 6）从零实现的五项

这些之前被记为「周级工程」或「不可达」，实测后都在一轮内做完：

| 项 | 我之前的判断 | 实际工作量 | 结果 |
|---|---|---|---|
| **E14/E18** Windows sandbox | 「需 Job Object 执行器，周级」 | `sandbox.py` 165 行，`win32job` 已装 | 新建 `windows_job_sandbox.py`，KILL_ON_JOB_CLOSE + 内存/进程限制 + 真实 `enforced` 上报；8 测试 |
| **X1** 组合根 | 「重构 52 字段 + 79 router」 | `services.<field>.` 73 个调用点 | 新建 `service_registry.py`，owner + 可撤销 + 懒构建；38 服务真实注册；12 测试 |
| **E1/S1/S2** 事件日志真源 | 「压缩不发事件，等价不可达」 | 日志只记 3 种事件 | `append_message` 同事务写 `message/append`；`derive_messages` 重建历史；**实测 match=True** |
| **X26** typed gateway | 「要生成描述符」 | `runtime_ws_router.py` 263 行 | `ws_protocol.py` 描述 9 个入站帧；坏帧返回 `protocol.error`；实测验证 |
| **E23** workflow 脚本 | 「模型不能表达控制流」 | 已有 graph/scheduler/runner | `script.py` 编译 `agent/parallel/pipeline/after`；拒绝 eval/import/loop；12 测试 |

## 期间修复的真实 bug

1. **Codex hook 退出码语义冲突** — Codex 的 exit 2 是「hook 出错」，Claude 是「主动阻断」。你的 `~/.codex/hooks.json` 有一条指向已删除脚本，导致每轮 prompt 被判 blocked、模型从未被调用（`request_count: 0`）。已按 source 区分修复。
2. **Codex PostToolUse 噪音** — 同一问题的另一半：坏 hook 的 traceback 被当 `feedback` 塞进每个工具结果。
3. **E31 `session_id` NameError** — 我写的 dispatch 引用了不存在的变量，**真实模型自己发现的**。
4. **`AppServices` 是 slots dataclass** — 第一版用 `vars()` 导致启动崩溃，health 探针抓到。
5. **前端丢弃 `protocol.error`** — `isRuntimeEvent` 要求 `type==='agent_event'`，协议错误被静默吞掉。

## 剩余 7 条

**6 条 HARD**（每条都有具体原因，不是「难度」）：
- `S26` 需要 DSH 自有的 wire extension，不是公开 API
- `S30` Atlas 已用 git 版记忆库，不需要官方上传
- `X5/X6/X7` 插件依赖解析/版本豁免/安装审批 — 需要包管理器语义
- `X30` SSH 作为整套执行世界 — 需要第二个执行世界

**1 条 NOT-DONE**：`S10` 被 S19 的 durable 附件设计取代。

## 不许说的话

- ❌「DSH 全部对齐」—— 94.8%，6 条 HARD 有明确原因
- ✅ 可以说：「E 区和 D 区 100% 关闭」
- ✅ 可以说：「128 条有证据支撑，其中带真实模型验证的是少数」
- ⚠️ HARD 的 6 条我没做，理由是能力边界而非时间

## 验证记录

| 项 | 结果 |
|---|---|
| Python 语法 | 0 错误 |
| 后端启动 | health 200 |
| 真实模型回合 | `run.completed`（`request_count: 1`）× 多次 |
| 事件可派生 | `compare match: True`（derived 2 = legacy 2） |
| 失败可重放 | `attempt/failed` 事件含 category/detail/model/run_id |
| 协议错误 | 坏帧返回 `protocol.error` 含字段名 |
| 前端 tsc | renderer 0 错误 |
