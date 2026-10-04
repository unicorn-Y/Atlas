# DATA-OWNERS — 每类数据只有一个 owner（H2.1）

> Taskbook: `tasks/taskbooks/ATLAS-H1-CORE-HARDENING.md` §4 H2.1。
> 规则：每类数据只能有一个 owner。owner 负责"写"；其他人最多"读"。
> 本文件由 H2 lane 维护；发现新的存储先登记在这里，再动手写代码。

## 唯一 owner 表

| 数据 | 唯一 owner | 读方（只读） | 状态 |
|---|---|---|---|
| 对话记录（消息、工具调用、工具结果、分叉、回退） | Hermes `SessionDB`（`state.db`，经 `atlas.engine` 的 hermes runtime） | Atlas 元数据库仅存预览所需的元数据；消息分页/搜索/导出/分叉树读 SessionDB | ⚠️ 过渡期：见下"双写退出计划" |
| 对话元数据（标题、工作区、权限模式、置顶、项目关联、run 记录、用量） | Atlas SQLite（`MemoryStore` 的 conversations/metadata 表） | 前端、渠道网关 | ✅ 已是唯一写方（标题由引擎回调 `on_session_title` 写回 Atlas，见 `agent/run_phases.py::_hermes_turn`） |
| 长期记忆（facts、reflections、goal knowledge） | Atlas SQLite（`MemoryStore`） | 运行路径注入 | ✅ 用户已冻结记忆架构，本波只做 H2.3 止血（注入上限） |
| 定时/队列/回执 | DBOS（`DurableBackend`） | automation/heartbeat | ✅ |
| 渠道游标/去重 | 各 channel adapter 自己的 state db | 渠道网关 | ✅（保留，登记即可） |
| Todo（单次运行内的任务清单） | 内存（`agent/todo_state.TodoStore`，per-run）；跨轮持久清单由 Hermes todo toolset 持有 | — | ✅ 无第二存储 |
| 检查点（shadow git） | `agent/checkpoints.ShadowGitCheckpointStore` | run/回退 | ✅ |

## 双写退出计划（对话记录：Atlas `messages` 表 → SessionDB）

现状（P2 双写）：正常一轮对话里，引擎把完整轮次写入 Hermes `SessionDB`
（`engine/hermes_runtime.py` turn loop，H3 起每会话复用 agent）；同时
`agent/run_phases.py::_phase_finalize` 把最终 assistant 文本再写一份到 Atlas
`messages`（`save_message`），历史注入也先读 Atlas（`get_conversation_messages`），
引擎侧已优先读 SessionDB（`turn_history = stored`，Atlas 文本只作首轮导入）。

退出步骤与依赖（步骤 1、2 的读接口在 `core/atlas/server.py` / `core/atlas/api/**`，
归 server lane；`engine/session_sync.py` 的"Atlas 改 → 同步到 Hermes"双写改直写
SessionDB，归 engine lane。H2 lane 不拥有这些文件，只交付规格）：

1. **读切换**（server lane）：会话列表预览、消息分页、搜索、导出、分叉树改读
   `SessionDB`；`atlas doctor sessions`（H9 lane 的 CLI 入口）对比元数据与
   SessionDB 报告孤儿与不一致。
2. **写切换**（engine lane）：`session_sync.py` 的截断/回退/分叉/删除/导入导出
   直接操作 `SessionDB`，删除"A→H"同步路径。
3. **停写**（H2 lane，等 1、2 合并后）：`_phase_finalize` 的 `save_message`
   降级为只写元数据（预览/标题），消息正文只进 SessionDB；Atlas `messages`
   表保留只读一个版本用于回滚，之后可删。
4. **迁移**（server lane + H2 lane 验收）：首启把 Atlas 有而 SessionDB 没有的
   历史会话导入；迁移前自动备份两个库到 `data/backup/<时间戳>/`；幂等、可重复；
   失败不删任何数据并在界面提示。fixture 验收：含分叉、回退、工具调用、图片、
   中文的真实形状库，断言条数、顺序、工具配对一致；重复迁移不重复导入；中途
   异常两库均未改动。

## H2 lane 范围内已消除/确认无重复的部分（2026-10-04）

- `agent/__init__.py::_run_atlas_subtask`：子任务结束时对两个库做**成对清理**
  （`session_sync.delete_session` + `memory.delete_conversation`），不产生孤儿。
- 子任务会话是纯运行期数据：创建即用、结束即删，不进前端列表 —— 不构成第二
  数据源。
- `agent/todo_state.TodoStore`、`AgentRunContext.changed_paths`、`plan_state`
  （经 `plan_update_callback` 由 server 持久化到 run 记录）均为派生/运行期状态，
  每类只有一个写方。
