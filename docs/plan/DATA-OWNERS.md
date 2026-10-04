# DATA-OWNERS — 每类数据只有一个 owner（H2.1）

> Taskbook: `tasks/taskbooks/ATLAS-H1-CORE-HARDENING.md` §4 H2.1。
> 规则：每类数据只能有一个 owner。owner 负责"写"；其他人最多"读"。
> 本文件由 H2 lane 维护；发现新的存储先登记在这里，再动手写代码。

## 唯一 owner 表

| 数据 | 唯一 owner | 读方（只读） | 状态 |
|---|---|---|---|
| 对话记录（消息、工具调用、工具结果、分叉、回退） | Hermes `SessionDB`（`state.db`，经 `atlas.engine` 的 hermes runtime） | Atlas 元数据库仅存预览所需的元数据；消息分页/搜索/导出/分叉树读 SessionDB | ✅ H1R 已切换；旧 Atlas 消息行只读 |
| 对话元数据（标题、工作区、权限模式、置顶、项目关联、run 记录、用量） | Atlas SQLite（`MemoryStore` 的 conversations/metadata 表） | 前端、渠道网关 | ✅ 已是唯一写方（标题由引擎回调 `on_session_title` 写回 Atlas，见 `agent/run_phases.py::_hermes_turn`） |
| 长期记忆（facts、reflections、goal knowledge） | Atlas SQLite（`MemoryStore`） | 运行路径注入 | ✅ 用户已冻结记忆架构，本波只做 H2.3 止血（注入上限） |
| 定时/队列/回执 | DBOS（`DurableBackend`） | automation/heartbeat | ✅ |
| 渠道游标/去重 | 各 channel adapter 自己的 state db | 渠道网关 | ✅（保留，登记即可） |
| Todo（单次运行内的任务清单） | 内存（`agent/todo_state.TodoStore`，per-run）；跨轮持久清单由 Hermes todo toolset 持有 | — | ✅ 无第二存储 |
| 检查点（shadow git） | `agent/checkpoints.ShadowGitCheckpointStore` | run/回退 | ✅ |

## 双写退出结果（2026-10-05）

正常对话的 user、assistant、工具和显示元数据只写 Hermes `SessionDB`。
`agent/run_phases.py` 与 server runtime 不再向 Atlas `messages` 写正文；Atlas
只更新标题、预览和项目等元数据。历史注入、列表预览、分页、搜索、导出、
分叉树及 memory evidence 查询均从 SessionDB 读取。

`engine/session_sync.py` 直接操作 SessionDB 的分叉、截断、回退、删除和导入导出。
旧 Atlas 消息表保留只读；启动迁移只导入 SessionDB 尚未拥有的会话，同 ID
的 SessionDB 数据保持权威。按 home 隔离的迁移门控在成功前阻止 transcript 读取。

迁移先通过 SQLite online backup 备份两个库，在同卷临时 SessionDB 导入并校验
消息 UID、角色、正文、工具/显示元数据、分支锚点和时间戳，再关闭连接、checkpoint
并原子发布。导入失败不改原库；发布中途失败恢复原 main/WAL/SHM；取消会释放门控
并标记失败。重复 legacy 标题使用确定性后缀；UTC、带时区和 epoch 时间保持原值，
无法解析的非空时间拒绝导入。

控制器独立回归：`test_session_migration.py` 与 `test_hermes_session_sync.py` 共
17 passed（11.59 秒，正常退出）。隔离真实副本验收导入 59 会话、117 消息，保留
9 个已有会话；doctor 的 missing/orphans/count mismatch/unpaired 均为 0，
117 条消息时间和 59 个会话 started_at 逐条一致，Atlas 数据库哈希未变。

## H2 lane 范围内已消除/确认无重复的部分（2026-10-04）

- `agent/__init__.py::_run_atlas_subtask`：子任务结束时对两个库做**成对清理**
  （`session_sync.delete_session` + `memory.delete_conversation`），不产生孤儿。
- 子任务会话是纯运行期数据：创建即用、结束即删，不进前端列表 —— 不构成第二
  数据源。
- `agent/todo_state.TodoStore`、`AgentRunContext.changed_paths`、`plan_state`
  （经 `plan_update_callback` 由 server 持久化到 run 记录）均为派生/运行期状态，
  每类只有一个写方。
