# Atlas Engine V1 执行结果

## 交付

- 在隔离 worktree `D:\atlas-engine` 的 `engine-v1` 分支接入 Atlas 内核：回合状态、模型流式调用与恢复、工具调度、进程管理、上下文压缩、提示词、文件编辑、计划、子 Agent、卡住检测和结构化运行日志。
- 保留 Atlas 的模型路由、SessionDB、工具注册、权限审批、事件协议和 Electron 后端生命周期；通过现有 Hermes SessionDB API 读写会话。
- 补齐四个上游项目的许可证和固定提交说明，移植文件均在源码头标出来源。

## 文件来源映射

固定上游：Codex `openai/codex@806d9732c974bc8a51b8317c1bd8985544fe627c`（Apache-2.0）；ZCode `zai-org/ZCode@29628c9acdb81b703bbd4080c207a0e7ce5e276ede`（Apache-2.0）；DeepSeek Harness `deepseek-ai/deepseek-harness@d743267388641bc76f17c45ce8b4c231aed1d32c`（MIT）；OpenHands SDK `OpenHands/software-agent-sdk@1cfba2117e92730b0fe1c32520a39aad8611bb8c`（MIT）。Claude Code 行为依据 v2.1.296 官方文档，具体链接列在相应文件头。

| 文件 | 来源 |
| --- | --- |
| `THIRD_PARTY_NOTICES.md` | 上述四个固定上游提交及其许可证文本链接。 |
| `config/atlas.example.toml` | Atlas 本地配置；新增 Engine V1 配置项，没有复制外部代码。 |
| `core/atlas/agent/__init__.py` | Atlas 原有 Agent 入口；接入 `kernel.loop`。 |
| `core/atlas/agent/enrichment.py` | Atlas 原有工具结果增强；接入内核输出与安全策略。 |
| `core/atlas/agent/run_phases.py` | Atlas 原有运行阶段；接入内核、模型用量和生命周期回调。 |
| `core/atlas/agent/tool_node.py` | Atlas 原有工具执行入口；接入内核调度、目标复核、安全审批和检查点。 |
| `core/atlas/engine/hermes_runtime.py` | Atlas 适配层；复用 `unicorn-Y/hermes-agent@562ad75baec0c8360f6ce2d48b7d9de56506956c` 的运行时、提示词、压缩和 SessionDB API，没有复制 Hermes 内核文件。 |
| `core/atlas/engine/session_sync.py` | Atlas 适配层；复用同一 Hermes 提交中的 `hermes_state.py::SessionDB` 和 `hermes_state_rewind.py`。 |
| `core/atlas/kernel/context.py` | ZCode `compact/policy.ts`、`compact/microcompact.ts`；Codex `codex-rs/core/src/compact.rs`；Claude Code v2.1.296 行为文档。 |
| `core/atlas/kernel/edit.py` | Codex `codex-rs/apply-patch/src/{parser,streaming_parser,file_update,seek_sequence,text_file}.rs`；ZCode `tool/edit-matchers.ts`、`tool/read-file-state.ts`。 |
| `core/atlas/kernel/exec.py` | Codex `codex-rs/core/src/unified_exec/{process_manager,head_tail_buffer}.rs`；ZCode `tool/bash-timeout-policy.ts`。 |
| `core/atlas/kernel/loop.py` | ZCode `agent/turn-machine.ts`；Codex `codex-rs/core/src/session/turn.rs`；Claude Code v2.1.296 行为文档。 |
| `core/atlas/kernel/model_call.py` | Codex `codex-rs/core/src/responses_retry.rs`。 |
| `core/atlas/kernel/plan.py` | Codex `models-manager/src/collaboration_mode_presets.rs`、`core/src/tools/handlers/plan.rs`；Claude Code v2.1.296 工作流文档。 |
| `core/atlas/kernel/prompt.py` | Codex `codex-rs/core/src/agents_md.rs`；ZCode `context/builder.ts`；Claude Code v2.1.296 memory 和 skills 文档。 |
| `core/atlas/kernel/repair.py` | DeepSeek Harness `packages/core/session/src/repair.ts`；Codex `codex-rs/core/src/session/turn.rs`。 |
| `core/atlas/kernel/state.py` | ZCode `agent/turn-state.ts`；Codex `codex-rs/core/src/session/turn.rs`。 |
| `core/atlas/kernel/stuck.py` | OpenHands `openhands-sdk/openhands/sdk/conversation/stuck_detector.py`。 |
| `core/atlas/kernel/subagents.py` | Codex `codex-rs/core/src/agent/control.rs`、`core/src/tools/handlers/multi_agents.rs`；ZCode `subagent/runner.ts`。 |
| `core/atlas/kernel/tools.py` | Codex `codex-rs/core/src/tools/{parallel,orchestrator}.rs`；ZCode `tool/scheduler.ts`。 |
| `core/atlas/logs.py` | Atlas 按 ENGINE-V1 计划实现的每次运行 JSONL 日志，没有复制外部代码。 |
| `core/atlas/server.py` | Atlas 原有应用装配；注册内核和日志服务。 |
| `frontend/src/main/backendProcess.ts` | Atlas 原有 Electron 后端进程管理；转发隔离后端日志。 |
| `tasks/results/ATLAS-ENGINE-V1.result.md` | 本任务生成的结果记录，没有复制外部代码。 |

具体的完整来源路径、许可证标记和 Claude Code 文档链接也保留在各内核模块头部；第三方许可证汇总见 `THIRD_PARTY_NOTICES.md`。

## 验收

- 后端从 `D:\atlas-engine` 启动；隔离数据根为 `D:\atlas-engine-runtime`。`/api/health` 返回 `status=ok`，组件全部为 `ready`。
- 运行 `npm ci --ignore-scripts --no-audit --no-fund` 后，`npm --prefix frontend run build` 通过。构建有 Vite 弃用提示和大 chunk 提示，无构建错误。
- 真实模型运行：`deepseek-v4.1-flash`，run `ca88e50e-865b-490f-9dc5-6381bc317d92`，状态 `completed`，耗时 `12941 ms`；累计输入 `28081`、输出 `675` tokens。模型先后调用只读 `local_file` 的 `list` 和 `read`，列出 `D:\atlas-engine` 顶层条目并读取 `README.md`。
- 运行日志：`D:\atlas-engine-runtime\data\logs\runs\2026-10-10\ca88e50e-865b-490f-9dc5-6381bc317d92.jsonl`。包含 `run_start`、`model_request`、两组 `tool_start`/`tool_end` 和 `run_end=completed`；单次运行日志记录用量与事件摘要，没有记录完整模型回复或 API 密钥。
- 按要求未新增测试、未运行测试套件。后端已停止；隔离副本 `D:\atlas-engine-runtime\data\user-settings.json` 已删除；`D:\Atlas` 未编辑。

## 已知非阻塞警告 / 未完成项

- 主模型运行和文件读取均成功。Hermes 自动标题的派生标题事件已产生，但其可选模型升级在后端日志报 `Messages.stream() got an unexpected keyword argument 'output_config'`；这是当前 Hermes 辅助标题调用与已安装客户端接口不匹配，本轮未修改 Hermes 源码或依赖。该警告不影响本次运行结果。
- SQLite 运行时提示链接版本 `3.50.4` 存在 WAL-reset 风险，已自动采用 `journal_mode=DELETE`，后端仍正常启动和完成运行。
- 除上述环境 / 辅助标题警告外，ENGINE-V1 计划中的本轮验收项均已完成。测试套件依照用户要求不运行。

## SHA

- 实现提交：`8ae4525c39da8235abe6f944865ad22451933356`
