# ATLAS-UPGRADE-W1 · 对标业界最新的四项结构性升级

> 任务书来源：2026-11-08 对标调研（AML 记忆榜 / MCP 2026-07-28 修订版 / AutoCompact / CLI-Anything / Genspark Claw Desktop）
> 调研结论：Atlas 在「上下文压缩」「生成-评估分离」「记忆写入门禁」三块已达业界前沿；缺口集中在四处**结构性**位置。

---

## 二、开工前必读（不许跳过）

1. `docs/plan/00-MASTER-PLAN.md` —— 主线
2. `tasks/CURRENT.md` —— 当前施工方向
3. `core/atlas/kernel/context.py` —— 压缩策略
4. `core/atlas/tools/mcp_client.py` —— MCP 连接
5. `core/atlas/memory/library/{index,store,extract,hybrid,__init__}.py`
6. `core/atlas/memory/bench.py`

## 三、硬约束

- 工作区 `D:/Atlas`，分支 `ui-redesign` **有未提交改动**。开工第一步：
  `git status --short > tasks/upgrade-w1-baseline.txt`
  此后**不** `git add` / `commit` / `push` / 切分支 / `stash`，除非用户当面明确要求。
- 环境（三条都必须满足，否则 import 会死）：
  - 解释器 `D:/Atlas/core/.venv/Scripts/python.exe`
  - `PYTHONPATH=D:/Atlas/core`
  - cwd 必须是 `D:/Atlas`
- 不删、不跳过已有测试；不降低既有能力；**不伪造测试结果**。
- 不动 `frontend/`；不动 `config/atlas.toml` 里的模型配置。
- 每个阶段独立可回滚；改完一个阶段跑一次测试再进下一个。
- 阶段报告写到 `docs/plan/UPGRADE-W1/`。

---

## 四、阶段一（P0-2）MCP 无状态协议适配

### 现状（已实证，别重新猜）

- `mcp` SDK 版本 **2.1.1**，`mcp.types.LATEST_PROTOCOL_VERSION == "2026-07-28"` —— 新协议 SDK 侧已支持。
- `core/atlas/tools/mcp_client.py` 连接后**无条件** `await handle.session.initialize()`（约 578–590 行），失败即整条连接失败。
- transport 默认 `sse`（旧的有状态双端点传输）；`streamable_http` 已实现但非默认。
- 2026-07-28 修订版：协议层**无状态化** —— 无 `initialize` 握手、无 `Mcp-Session-Id`；`clientInfo` 走 `params._meta`；新增 `Mcp-Method` / `Mcp-Name` 头与头体一致性校验；`tools/list` 支持 `MCP-Tool-Cache: ttlMs` 缓存。

### 要做

1. 握手改**探测式**：`initialize` 超时或返回不合法时**不抛错**，降级为无状态直连 —— 直接 `list_tools`。
2. 默认 transport 从 `sse` 改为 `streamable_http`；`sse` 保留为显式配置项（老 server 兼容）。
3. 无状态路径请求带 `MCP-Protocol-Version` 头；按返回的 `MCP-Tool-Cache` 缓存 `tools/list`（ttlMs），过期重取。
4. **保持既有行为不变**：`_mcp_rule_matches` 权限规则、敏感参数脱敏、连续失败冷却、重连监控，一个都不许改语义。
5. 状态上报区分 `state: "connected"` 与 `"connected_stateless"`。

### 验收

- 写最小无状态 MCP server fixture（`core/tests/fixtures/`，用 mcp SDK 的 server 侧），启动 → Atlas 连上 → `list_tools` 有工具 → 调用一次成功。
- 旧 SSE server 回归仍通过。
- 新增 `core/tests/test_mcp_stateless_handshake.py`。
- `pytest core/tests -k mcp` 全绿。

---

## 五、阶段二（P0-1）记忆作用域隔离

### 现状

- `Entry.scope` 字段存在（`store.py:65`），恒 `"global"`，无写入方。
- `items` 表**没有 scope 列**（`index.py:_SCHEMA`）。
- 已有 `ALTER TABLE ADD COLUMN` 迁移先例（`ref` 列，`index.py` 约 148 行）—— **照抄这个写法，不要重建表**。
- `origin_class` 五级（owner/agent/untrusted/system/episode）已有，不要动。

### 要做

1. `index.py`：`_SCHEMA` 加 `scope TEXT NOT NULL DEFAULT 'global'`；迁移用 `PRAGMA table_info(items)` 探测 + `ALTER TABLE items ADD COLUMN scope ...`；加 `CREATE INDEX IF NOT EXISTS items_scope ON items(scope)`。
2. `store.py`：`Entry.scope` 默认 `'global'`，确认 `meta()` / `_ENTRY_RE` 反序列化 round-trip 不丢字段。
3. 写入侧：`extract.apply` / `MemoryLibrary.add_entry` / `agent_memory_write` 接受 `scope` 参数。取值规则：
   - 默认 `'global'`（ME / NOW / SELF 三页保持 global）
   - 带项目上下文的写入 → `project:<project_id>`
   - `agent_memory_write(agent_id)` → `agent:<agent_id>`
4. 检索侧：`MemoryLibrary.search` / `recall` 接受可选 `scope` 过滤；`scope=None` 语义 = **global + 当前项目**，不要一刀切只看 global。
5. 向后兼容：老行 `scope='global'`，行为与今天完全一致。

### 验收

- 迁移测试：造一个无 scope 列的旧库 → 打开 → 列存在 → 老数据 `scope='global'`。
- 隔离测试：写 `project:A` 一条、`project:B` 一条 → 在 A 上下文检索只出 A + global。
- `core/tests/unified_memory` 全绿（基线 271 passed / 2 skipped）。

---

## 六、阶段三（P1-1）AML 评测口径

> 这是所有记忆优化的**度量前提**。没有它，后面每次改记忆都是盲改 + 自己给自己打分。

### 要做

1. 新增 `core/atlas/memory/aml_adapter.py`：
   - `add(text: str, *, scope="global", meta=None) -> str` 返回 memory id
   - `search(query: str, k: int = 10, *, scope=None) -> list[tuple[str, float]]`
   - 接口**严格**对齐 AML：只有 Add / Search 两个，不许偷偷加第三条。
2. 接数据集：PersonaMem / LoCoMo-Refined / BEAM。**先做 LoCoMo-Refined**，另两套留 adapter 占位 + TODO 注释写清缺什么。
3. 输出 **7 维剖面**：事实召回 / 多跳推理 / 时间推理 / 个性化 / 规则执行 / 记忆治理 / 写入检索效率。
4. 现有 `memory/bench.py` 不动；AML 作为外部对照，结果写 `docs/plan/UPGRADE-W1/aml-baseline.md`。

### 验收

- 一条命令跑出 baseline 分数并落盘 markdown。
- 报告必须写清：数据集版本 / 来源 URL / 跑分日期 / 模型 / 每维分数。**缺一项算没做完。**

---

## 七、阶段四（P1-2）就地 compact + 阶段感知触发

### 现状

- `context.py` 有 `thresholds` / `microcompact` / `prepare`（已对齐 Codex + ZCode）。
- `kernel/loop.py` 有 `new_context_window`（**重置式**：清窗 + 摘要交接，约 953 行）。
- 缺「就地压缩」：把历史替换成工作状态摘要，**窗口不动**。

### 要做

1. `context.py` 加 `compact_in_place(history, *, summarize, budget_tokens)`：产出「工作状态摘要」（目标 / 约束 / 已决策 / 已完成 / 待办 / 关键文件 / 未验证假设），替换历史，保留最近 N 轮 verbatim。
2. `agent/tool_catalog.py` 加 `compact_context` 工具，描述里讲清：轻量、就地、任务继续；与 `new_context_window` 的区别。
3. 阶段感知：plan 阶段完成 / 子任务收口时**评估一次**是否该压（不是无条件压）。
4. **不改** `new_context_window` 行为。

### 验收

- 单测：造 40 轮历史 → `compact_in_place` → token 数降 ≥50%，且 goal / open_items / files 都还在摘要里。
- 工具出现在 `model_facing_tools` 且能被调用。

---

## 八、交付物

- 每阶段 `docs/plan/UPGRADE-W1/P<n>-<name>.md`：改了什么文件、为什么、测试数、**验收证据（真实命令输出粘贴）**。
- 最终 `docs/plan/UPGRADE-W1/SUMMARY.md`：四项完成度、未做项及原因、风险。
- **禁止写「已完成」而无证据。**

## 九、不要做的事

- 不要顺手重构无关模块。
- 不要为了过测试改测试。
- 不要动 `ui-redesign` 的前端。
- 不要在没跑通的情况下说跑通了。
