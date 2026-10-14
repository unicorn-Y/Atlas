# CTX-1 完成报告

工作区：`D:\atlas-ctx-opt`，分支 `ctx-opt`，基于 `origin/memory-v1`。`D:\Atlas` 主工作区未改动；未触碰 `core/atlas/memory/*`、`agent/injection_budget.py`、`breaker.md`、`~/.atlas-expert` 或 `subagents.py` 的 `summary[:4000]`。

## 1. A–F 改动与参考来源

### A. 压缩与摘要质量

- `core/atlas/kernel/context.py`：按配置执行裁剪和摘要；保护最近上下文及 `skill`/`use_skill` 结果；限制工具序列化；识别命令、退出码、路径和搜索命中；支持最近窗口、split-turn 合并、迭代摘要、用户原话和回查提示；检查摘要结构、乱码及路径/哈希/会话 id/测试名/端口等标识符；缺项重试，质量检查仍失败时不替换原历史；跟踪累计读取和修改文件。
- `core/atlas/kernel/loop.py`：将真实 provider usage 交给压缩器；按配置选择摘要模型并在失败时回到当前主模型；提交成功后更新会话历史并记录压缩 token 数，供界面显示。
- `engine/config.yaml`：加入压缩、摘要和失败保护配置。
- `core/atlas/agent/tool_catalog.py`、`core/atlas/engine/tool_registry.py`：说明 `new_context_window` 的安全调用时机。
- 借鉴：OpenCode `packages/opencode/src/session/compaction.ts:28–31, 271–320`；Pi `packages/coding-agent/src/core/compaction.ts:123–129, 431–499, 643–731, 994–1034`；Hermes `agent/context_compressor.py:983, 1013, 1964, 3267`；OpenClaw `docs/concepts/compaction.md:29–33`；Claude Code `services/compact/prompt.ts:61–77`。

### B. 压缩后恢复上下文

- `core/atlas/engine/compact_restore.py`：恢复磁盘当前修改文件、只读文件回查清单、原计划/todo 和当前已加载技能说明，并按每项及总 token 上限裁剪。
- `core/atlas/engine/tool_registry.py`、`core/atlas/kernel/loop.py`：接入 `read_file` / `local_file` 跟踪，压缩后失效旧读取状态并调用恢复 helper；SSH workspace 不将远端相对路径误解为本地文件。
- 借鉴：Claude Code `services/compact/compact.ts:122–130, 1437–1447, 1454–1462`；ZCode `packages/core/src/runtime/helpers/compact-post-reminders.ts:8–50, 57–68, 74–85`；Atlas 技能输入 `core/atlas/agent/run_phases.py:131–149, 557–564`，todo `core/atlas/engine/tool_registry.py:520–523`。

### C. 重复读取去重

- `core/atlas/engine/read_dedupe.py`、`core/atlas/engine/tool_registry.py`：按会话、规范化路径、读取范围和 mtime 判定文件是否变化；仅当上次读取结果仍在上下文时返回前文提示；压缩/裁剪掉结果后清除对应去重记录。
- 借鉴：Claude Code `tools/FileReadTool/FileReadTool.ts:326, 543–567, 564, 686–690`。

### D. 接力到新会话

- `core/atlas/api/conversations_router.py`、`core/atlas/api/handoff_metadata.py`：生成接力开场提示、创建关联子会话、持久化父会话和目标元数据；接力提示留在新会话输入框草稿，不自动发送；接受/拒绝均记录真实 run 的事件。
- `core/atlas/agent/tool_catalog.py`、`core/atlas/agent/tool_node.py`、`core/atlas/engine/tool_registry.py`：新增 `propose_handoff(goal, context)` 和父会话过滤查询；模型提议等待用户选择。
- `frontend/src/renderer/App.tsx`、`frontend/src/renderer/components/TokenUsage.tsx`、`ConversationActivity.tsx`、`MessageThread.tsx`、`timeline.ts`、`HandoffProposalCard.tsx`、`HandoffSuggestion.tsx`、`runtimeEvents.ts`、`useAtlasStore.ts`、`frontend/src/types/runtime.ts`、`backend-adapter/src/client.ts`、`backend-adapter/src/types.ts`：支持 `/handoff`、上下文用量按钮、接力提议卡、拒绝操作、父会话返回链接及可展开压缩分隔条。
- 借鉴：Pi `examples/extensions/handoff.ts`（任务书所指约第 190 行）；Cline `docs.cline.bot/exploring-clines-tools/new-task-tool`（网页未提供稳定行号）；Amp `read_thread` 会话读取思路；Atlas 会话/分叉参考 `core/atlas/memory/__init__.py:217`、`core/atlas/engine/session_sync.py:53–70, 91–98`（仅作只读参考，memory 模块未修改）。

### E. 子任务节点主动压缩

- `core/atlas/agent/tool_catalog.py`、`core/atlas/engine/tool_registry.py`、`core/atlas/kernel/loop.py`：重写 `new_context_window` 描述并接到 A 的新压缩引擎；仅在阶段完成、方案确定、测试通过或规划转实施后建议调用，执行中途不调用。
- 借鉴：任务书第 3 节 E（既有 `new_context_window` 接口位置 `core/atlas/agent/tool_catalog.py:238` 与 `core/atlas/engine/tool_registry.py`）；时机参考 Self-Compact 论文中阶段边界压缩做法。

### F. 日志与诊断

- `core/atlas/kernel/model_call.py`、`core/atlas/kernel/loop.py`：失败模型请求写入最多 500 字符的异常类型/消息、类别、状态码和耗时；压缩事件记录触发来源、方式、token、裁剪/去重、恢复文件、摘要模型、质量缺项、无效次数、耗时和错误；接力事件仅在存在真实 run id 时写入。
- `scripts/diag/context_stats.py`：按日期汇总主对话请求量、输入 token 中位数/P75、按 purpose 的缓存命中、压缩方式/压缩比、无效压缩、质量拒绝、接力采纳率及常见模型错误。
- `core/tests/test_context_stats.py` 覆盖统计聚合、损坏行、异常字段和 CLI。

## 2. 新增 `[engine]` 配置及默认值

| 配置 | 默认值 | 用途 |
|---|---:|---|
| `prune_trigger_ratio` / `prune.trigger_ratio` | `0.55` | 裁剪检查阈值 |
| `summary_trigger_ratio` | `0.70` | 裁剪后摘要阈值 |
| `prune.enabled` | `true` | 启用输出裁剪 |
| `prune.protect_tokens` | `40000` | 保留最近上下文 |
| `prune.minimum_tokens` | `20000` | 最少回收 token 数 |
| `prune.protected_tools` | `[skill, use_skill]` | 裁剪保护工具 |
| `keep_recent_tokens` | `20000` | 摘要最近窗口 |
| `tool_serialize_max_chars` | `2000` | 工具结果摘要序列化字符上限 |
| `summary_model` | `null` | 默认使用当前主模型 |
| `summary_max_tokens` | `4096` | 摘要输出上限 |
| `summary_retry_count` | `1` | 摘要质量失败重试数 |
| `compaction_ineffective_limit` | `2` | 无效压缩熔断阈值 |
| `max_compaction_failures` | `3` | 压缩失败限制 |
| `restore_max_files` | `5` | 恢复修改文件数上限 |
| `restore_file_tokens` | `5000` | 单个文件 token 上限 |
| `restore_total_file_tokens` | `50000` | 文件恢复总 token 上限 |
| `restore_skill_tokens` | `5000` | 单个技能 token 上限 |
| `restore_total_skill_tokens` | `25000` | 技能恢复总 token 上限 |

## 3. 验证结果

- Python 聚焦新增测试：`py -3.14 -m pytest -q ... tests/test_context_compaction_v3.py tests/test_context_stats.py tests/test_handoff_metadata.py tests/test_read_dedupe.py`：**12 passed**。
- 前端完整测试：`npm test -- --reporter=dot`：**29 个测试文件通过，189 passed**。
- 前端构建：`npm run build`：成功。
- Python 新增文件 Ruff 检查：通过；`git diff --check`：通过。
- Python 全量套件未能完成。Python 3.11 的测试入口触发 Hermes bootstrap 重启，重启环境找不到 pytest；Python 3.14 在收集时有 **7 个导入错误**，涉及机器上的外部 Hermes runtime 源码与当前 checkout 不匹配（缺少/版本不一致的 `run_agent`、`hermes_state`、`hermes_constants`、`tools`/`agent` 模块），未进入完整测试阶段。忽略这些文件继续跑时，套件在约 49% 进度后长时间无进展并被中断，没有最终总数，因此不能把它记为通过或给出未观察到的总失败数。
- 一次较宽的压缩/模型 wiring 聚焦运行得到 **13 passed、6 failed**；失败涉及上述机器 Hermes 模块缺失/版本错配、旧测试夹具缺少 `_model_mgr` 等。当前运行环境不能证实这些失败在基线分支上的状态。任务书提到的 `test_c1_tool_workspace.py` 两个已知失败未能在可运行的全量套件中单独确认。

## 4. 未完成或偏离及原因

- 全量 Python 套件结果受外部 Hermes runtime 导入和长时间挂起阻断；已通过全部本次新增聚焦测试、前端完整测试和构建，未声称 Python 全量通过。
- 诊断脚本已实现并由测试验证，但“用一两天后”对比生产日志需要实际运行积累数据；本次不伪造运行效果数据。
- 未做 Claude 审查合并，也未执行“立即更新”；任务书将这两步留给后续人工操作。
- 任务书提及的 `session_id` 被写为 `cid.txt` 路径问题不在范围内；本次没有处理。

## 5. 提交哈希

`16b6fde9d76a1d5ba7f59327a222e5c670a911dc` (`feat(context): optimize compaction and handoff`)
