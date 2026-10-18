# DSH 官方 Agent Core — 源码逆向阶段报告

> 状态：**PARTIAL / SOURCE-VERIFIED**。此为实质性源码阶段结论，并非二进制全量验收；**S = 已读取固定源码并核查符号/调用链，U = 未验证**。未经运行验证不写 R。

## 一句话结论
DeepSeek Harness 的核心不是单一的聊天循环，而是 **Cordis 可组合插件服务 + Session 事件日志/投影 + Agent Turn/Step 循环 + 多 provider 子代理生命周期 + Typert 远程控制与 Web 投影**。最值得 Atlas 吸收的是：模型请求与工具事件的可恢复边界、子代理持久地址/冷热驻留分离、并发执行而顺序提交的工具调度、浏览器子 Session 可观察和可干预的真正端到端路径。

## 严格版本表
| 材料 | 身份 | SHA256/commit | 审查状态 |
|---|---|---|---|
| 官方 CLI npm | `@deepseek-ai/dsh@0.2.0-rc.2` | `bd27847c445cd68a565ac1f91c06bbbcc7639ef93071f678bb59c5ebaff38859` | U，归档确认，发行内容待提取 |
| 官方源码固定快照 | root `0.2.1-rc.2` | `687f282e8625c6b8d11ff58211a90524be2e4317`；ZIP `dcc4cf8df9c3cbb3d57726b7a1ad5a52c16a754dcdbc2c0a0836788976090d9f` | **S，已实际逐文件读源码** |
| 官方 Web UI npm | `@deepseek-ai/dsh-web-frontend@0.0.1-rc.5` | `ccadad6dcbb6f9a3c7a57802c3c2bb5958c2104ca33e9fb88135634b6d7b1516` | U，产物/源码版本差异待解包 |
| Atlas baseline | `main` | `aa6196f550098cc46081dc6db2c376cb87ddffa5` | **S，抽查相关真实模块** |

发行物清单：`docs/research/agent-clients/2026-10-19/manifest.json`、`indexes/dsh-index.txt`，派工分支 `research/agent-reverse-dispatch-20261019`。官方上游 `https://github.com/deepseek-ai/deepseek-harness/tree/687f282e8625c6b8d11ff58211a90524be2e4317`。**只将固定源码上的能力归属于源码快照，不假定旧版 npm 一致。** 上游含 `apps/desktop` 源码，不能因为本次没有官方 Desktop Windows 发行包就误称官方完全没有桌面代码；第三方 DSH Desktop 另案。

## 已明确核查的机制
1. Agent `ReactLoopAgent` 的 durable `turn/start → step/start → request/header → assistant/attempt|message → tool/call/result → step/end → turn/end`。
2. 工具 `executionMode` 动态 barrier/rolling bounded pool，提交结果与上下文维持模型顺序。
3. 子代理 `SubagentManager` local/external provider、durable parent linkage、子 Session、并发占位、cold resume、delivery 与生命周期事件。
4. 子代理可由浏览器导航进入独立 Session，通过 `subagents.prompt/interruptByParent` 走父子路由；不是 UI 假树。
5. Web `/api/remote.mux` WebSocket 多路复用，Session follow/control 基线与 live projection 分离。
6. JSONL event stream 的 write-behind、单 writer 跨进程 lease、事件格式版本迁移。
7. token-meter 按已完成 attempt 的事实汇总输入/输出/cache/reasoning；缺资料返回不可精确统计，而不是估造“精确”。
8. 额外发现：实验性 Agent Team 的任务 DAG、事件持久化；后台 jobs 的非消费式 Web follow；PTC runtime；独立 Schedule、Goal round driver、工具结果剪裁，MCP 动态重连/工具重同步，Trajectories 事件时间线。

## 阅读路线
- [DISCOVERY-LEDGER.md](DISCOVERY-LEDGER.md)：`DSH_CORE-NNN` 主账（各项版本/证明级别）
- [IMPLEMENTATION-TRACE.md](IMPLEMENTATION-TRACE.md)：核心链路、输入输出、状态时序与故障边界
- [UI-AND-WORKFLOWS.md](UI-AND-WORKFLOWS.md)：可见操作到 Host 控制的双向追踪
- [ATLAS-GAP.md](ATLAS-GAP.md)：仅以 Atlas main 代码作部分/缺口/未知定级
- [EVIDENCE-INDEX.md](EVIDENCE-INDEX.md)：精确文件路径、符号和未覆盖边界
- [REUSE-CANDIDATES.md](REUSE-CANDIDATES.md)：移植、依赖、许可证
- [EXTRACTION-REQUEST.md](EXTRACTION-REQUEST.md)：CLI 和 Web 发行包补采机械任务

## 重要限制与尚未完成
- 未直接解包或动态运行 **npm CLI 0.2.0-rc.2**、**Web UI 0.0.1-rc.5**；发行产物实际 feature flags、内置包是否等于固定源码都属于 **U**。
- 已读固定源码中多条重要调用链，但对接近两万个 tracked paths 没有声称“全面读完”；仍需穷举命令、全量 UI slots、RPC endpoints、权限与各外部 Agent provider 边界，及实际断网/重启/并发竞争的 R 证据。
- 子代理 cold resume 已证实，**任意活跃计算跨 Host 进程崩溃无缝接续尚未证实**；WebSocket carrier 可重连不表示原 stream 自动恢复。
- Atlas 比对是有范围的代码抽查，未做启动 E2E，不把未搜索完的机制判定为全项目不存在。
