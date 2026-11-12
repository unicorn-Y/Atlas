# CODEX 任务书 · Atlas 四项结构性升级（并行子代理版）

## 0. 你的位置

你在 `D:\Atlas` 这个仓库里干活，仓库当前分支 `ui-redesign`，**工作区有未提交改动**（backend-adapter、models_settings_router、records_router、persistent_agents/store.py、frontend 等）。
你的产出必须**只落在下面列明的文件**，其余未提交改动一律不许碰。

环境（三条必须同时满足，否则 import 会死）：
- 解释器：`D:\Atlas\core\.venv\Scripts\python.exe`
- `PYTHONPATH=D:\Atlas\core`
- cwd：`D:\Atlas`

## 1. 背景

2026-11 对标调研结论：Atlas 在「上下文压缩」「生成-评估分离」「记忆写入门控」三块已到业界前沿；缺口集中在四处结构性位置。本次只做这四处，**不扩范围**。

## 2. 并行分工（必须真的开子代理）

用 **3 个 worker 子代理并行**，各自独立文件范围、互不重叠；主线（你自己）负责阶段三 + 终审 + 汇总。

### agent A（worker）— 阶段一：MCP 无状态协议适配

**只许改这些文件：**
- `core/atlas/tools/mcp_client.py`
- `core/tests/test_mcp_stateless_handshake.py`（新建）
- `core/tests/fixtures/` 下新建的无状态 server fixture

**现状（已实证，不要重新猜）：**
- `mcp` SDK 2.1.1，`mcp.types.LATEST_PROTOCOL_VERSION == "2026-07-28"`
- `mcp_client.py` 连接后无条件 `await handle.session.initialize()`（约 578–590 行），失败即整条连接失败
- transport 默认 `sse`；`streamable_http` 已实现但非默认
- SDK 侧已有 `MODERN_PROTOCOL_VERSIONS`、`server/discover` 探测、`ttlMs` 缓存、服务端 `stateless_http`

**要做：**
1. 握手改探测式：`initialize` 超时或返回不合法时不抛错，降级为无状态直连（直接 `list_tools`）
2. 默认 transport 从 `sse` 改为 `streamable_http`，`sse` 保留为显式配置项
3. 无状态路径带 `MCP-Protocol-Version` 头；按 `MCP-Tool-Cache: ttlMs` 缓存 `tools/list`
4. 保持既有行为不变：`_mcp_rule_matches` 权限规则、敏感参数脱敏、连续失败冷却、重连监控，一个都不许改语义
5. 状态上报区分 `"connected"` 与 `"connected_stateless"`

**验收：** 新 fixture 能连上并 list_tools + 调用一次；旧 SSE server 回归通过；`pytest core/tests -k mcp` 全绿。

---

### agent B（worker）— 阶段二：记忆作用域隔离

**只许改这些文件：**
- `core/atlas/memory/library/index.py`
- `core/atlas/memory/library/store.py`
- `core/atlas/memory/library/hybrid.py`
- `core/atlas/memory/library/__init__.py`
- 对应测试文件（新建或改 memory 相关测试）

**现状：**
- `Entry.scope` 字段存在（`store.py:65`），恒 `"global"`，无写入方
- `items` 表**没有 scope 列**
- 已有 `ALTER TABLE ADD COLUMN` 迁移先例（`ref` 列，`index.py` 约 148 行）——**照抄这个写法，不要重建表**
- `origin_class` 五级已有，不要动

**要做：**
1. `index.py`：`_SCHEMA` 加 `scope TEXT NOT NULL DEFAULT 'global'`；`PRAGMA table_info(items)` 探测 + `ALTER TABLE items ADD COLUMN scope`；加 `CREATE INDEX IF NOT EXISTS items_scope ON items(scope)`
2. `store.py`：`Entry.scope` 默认 `'global'`，确认 meta 序列化 round-trip 不丢
3. 写入侧接受 `scope` 参数：默认 `'global'`；项目上下文 → `project:<id>`；agent 写入 → `agent:<id>`
4. 检索侧接受可选 `scope` 过滤；`scope=None` 语义 = **global + 当前项目**，不是只看 global
5. 向后兼容：老行 `scope='global'`，行为与今天一致

**验收：** 旧库迁移测试（造无 scope 列的库 → 打开 → 列存在 → 老数据 global）；隔离测试（A/B 两项目互不可见）；`core/tests/unified_memory` 全绿（基线 271 passed / 2 skipped）。

---

### agent C（worker）— 阶段四：就地 compact + 阶段感知

**只许改这些文件：**
- `core/atlas/kernel/context.py`
- `core/atlas/agent/tool_catalog.py`
- 对应测试文件（新建）

**现状：**
- `context.py` 有 `thresholds` / `microcompact` / `prepare`
- `kernel/loop.py` 有 `new_context_window`（**重置式**，约 953 行）——**不许改它的行为**
- 缺「就地压缩」：把历史替换成工作状态摘要，窗口不动

**要做：**
1. `context.py` 加 `compact_in_place(history, *, summarize, budget_tokens)`：产出工作状态摘要（目标/约束/已决策/已完成/待办/关键文件/未验证假设），替换历史，保留最近 N 轮 verbatim
2. `agent/tool_catalog.py` 加 `compact_context` 工具，描述里讲清与 `new_context_window` 的区别（轻量、就地、任务继续）
3. 阶段感知：plan 阶段完成 / 子任务收口时**评估一次**是否该压，不是无条件压

**验收：** 造 40 轮历史 → `compact_in_place` → token 降 ≥50%，goal / open_items / files 都在摘要里；工具出现在 `model_facing_tools` 且可调用。

---

## 3. 主线（你自己）— 阶段三 + 终审

### 阶段三：AML 评测口径

**只许新建/改：**
- `core/atlas/memory/aml_adapter.py`（新建）
- `docs/plan/UPGRADE-W1/aml-baseline.md`（新建）

**要做：**
1. `add(text, *, scope="global", meta=None) -> str`、`search(query, k=10, *, scope=None) -> list[tuple[str, float]]` —— 严格只有 Add / Search 两个接口
2. 接 LoCoMo-Refined（先做这个），PersonaMem / BEAM 留 adapter 占位 + TODO 注明缺什么
3. 输出 7 维剖面：事实召回 / 多跳推理 / 时间推理 / 个性化 / 规则执行 / 记忆治理 / 写入检索效率
4. 现有 `memory/bench.py` 不动

**注意：** 阶段三依赖 agent B 的 `search(scope=...)` 签名 —— **等 B 返回后再动手**，不要和 B 同时改 memory 层。

### 终审与汇总

- 三个 agent 回来后，逐项核对证据（真实 pytest 输出、真实文件 diff），不接受「已完成」自述
- 写 `docs/plan/UPGRADE-W1/SUMMARY.md`：四项完成度、未做项及原因、风险、测试数
- 若某 agent 越界改了别人的文件 → 立即停止该 agent 并回滚越界部分

## 4. 硬约束

- **不 git add / commit / push / 切分支 / stash**
- 不动 `frontend/`；不动 `config/atlas.toml` 的模型配置
- 不删、不跳过已有测试；不为了过测试改测试
- **不伪造测试结果**——报告里贴真实命令输出
- 三个 agent 各自用独立 pytest `--basetemp`，不要同时跑 `tests/unified_memory` 全量（会抢 8099 端口出假失败）
- 每阶段独立可回滚

## 5. 交付物

- `docs/plan/UPGRADE-W1/P1-mcp-stateless.md`
- `docs/plan/UPGRADE-W1/P2-memory-scope.md`
- `docs/plan/UPGRADE-W1/P3-aml-baseline.md`
- `docs/plan/UPGRADE-W1/P4-compact-in-place.md`
- `docs/plan/UPGRADE-W1/SUMMARY.md`

每份报告必须含：改了哪些文件（路径 + 行号）、为什么、测试命令与真实输出、验收证据、未做项。

## 6. 现在开始

先回一句「已读，开始派工」+ 你实际开的子代理清单（名字/角色/文件范围），然后并行开工。
