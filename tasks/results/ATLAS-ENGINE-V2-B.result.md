# ATLAS-ENGINE-V2-B 接线结果

## 范围

- 工作树：`D:\atlas-engine3`
- 分支：`engine-v2b`
- 基线：`origin/track-upstream`，`873c721d6a1ef662b0ad1c4a756b59207d2cd443`
- 功能实现提交 SHA：`a156f0eeac3bc7629f77e4cae0ce5228f06e9357`
- `D:\Atlas` 未作仓库文件修改；真实运行使用独立数据目录 `D:\atlas-engine3-runtime`。

## 实现内容

### 仓库地图

- `core/atlas/engine/tool_registry.py` 将 `REPOMAP_TOOL_SPEC` 接入 Hermes 兼容工具绑定，处理器以当前工作区为根目录调用 `build_repo_map`。
- `core/atlas/kernel/tools.py` 将 `build_repo_map` schema 和 dispatch 接入 Atlas 新内核；`core/atlas/kernel/loop.py` 将结果和错误写入现有工具事件流。
- 两条路径都使用同一 RepoMap 实现。

### 检查点与回退

- `core/atlas/api/run_drive.py` 在每回合执行前调用 `checkpoint_before_turn`。
- `core/atlas/api/conversations_router.py` 将列出、预览和回退请求转到 `atlas.rewind` 的 `list_points`、`preview`、`rewind`，支持 `code`、`conversation`、`both`；旧路径、请求形式和返回字段继续兼容，并通过适配器调用现有对话截断逻辑。

### DAG 工作流

- `core/atlas/kernel/tools.py` 向新内核注册 `workflow` 工具；`core/atlas/kernel/workflow_tool.py` 调用 `plan_workflow` 与 `run_workflow`，也支持从 journal 恢复。
- `core/atlas/kernel/subagents.py` 为每个 DAG 节点创建子 agent，并通过 `core/atlas/agent/__init__.py` 的 Atlas kernel loop 执行。最大并行数读取 `[engine].workflow_max_parallel`，默认 4；`config/atlas.example.toml` 增加该配置项。
- workflow 进度映射到已有 run 事件。父 run 的取消事件和暂停事件传到 planner、子 agent；暂停恢复时清除 journal 暂停标记，若调度器已返回暂停则等待 run 恢复后继续同一 DAG。

### 自动标题 SDK 兼容

- `core/atlas/engine/hermes_runtime.py` 在 Atlas 侧包装 Hermes 辅助翻译调用，将旧 `output_config` 参数适配到 Anthropic SDK 0.76.0 支持的请求扩展字段；未修改 Hermes 仓库。
- `frontend/src/main/electron.ts` 导入 `node:timers` 的 `setImmediate`，修正 Electron 主进程 build 的类型错误。

## 验证

- 未新增或运行测试及测试套件，按任务要求执行。
- Python 改动文件通过 `py_compile`；`git diff --check` 通过。
- `npm --prefix frontend run build` 通过：Vite 8.3.4，renderer 转换 4694 个模块，build exit code 0。为补齐工作树 `node_modules` 内不完整的类型文件和 Windows native package，依赖修复仅落在忽略目录；未修改 `package.json` 或 lock 文件。
- 隔离后端 `/api/health` 返回 `ok`。
- 真实模型消息完成：run `bfd7aa0a-ca39-48a2-8f75-4e3d9b3c25d8`，模型调用一次 `build_repo_map`，日志为 `tool_start` 后接 `tool_end` 状态 `completed`。JSONL 位于 `D:\atlas-engine3-runtime\data\logs\runs\2026-10-10\bfd7aa0a-ca39-48a2-8f75-4e3d9b3c25d8.jsonl`。
- 标题适配器日志确认 SDK 参数兼容路径已执行；随后辅助标题请求收到上游 `Model is unavailable` 400。因此原 SDK 参数异常已绕开，但标题生成成功仍未确认。

## 未完成与限制

- 没有单独运行真实模型 DAG 工作流；工作流接线及暂停、恢复、取消路径做了静态审查和 Python 语法检查。
- 后端日志另有 Playwright MCP 命令不可用的环境告警；RepoMap 实际调用和 run JSONL 写入成功。
- 本文件的功能提交 SHA 指向上方实现提交。此结果记录随后作为独立提交加入分支；最终分支 HEAD SHA 在提交后回报。
