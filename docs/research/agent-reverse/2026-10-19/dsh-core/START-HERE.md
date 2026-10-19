# DSH 官方 Agent Core — 源码逆向阶段报告

> 状态：**PARTIAL / ARTIFACT-AND-SOURCE-VERIFIED**。三个 Release 资产现已实物下载、哈希核验、解包和静态拆解；固定源码调用链亦已审查。**S = 实际文件/源码，U = 未验证**。未经运行验证不写 R。

## 一句话结论
DeepSeek Harness 的核心不是单一的聊天循环，而是 **Cordis 可组合插件服务 + Session 事件日志/投影 + Agent Turn/Step 循环 + 多 provider 子代理生命周期 + Typert 远程控制与 Web 投影**。最值得 Atlas 吸收的是：模型请求与工具事件的可恢复边界、子代理持久地址/冷热驻留分离、并发执行而顺序提交的工具调度、浏览器子 Session 可观察和可干预的真正端到端路径。

## 严格版本表
| 材料 | 身份 | SHA256/commit | 审查状态 |
|---|---|---|---|
| 官方 CLI npm | `@deepseek-ai/dsh@0.2.0-rc.2`, 24,265 bytes | `bd27847c445cd68a565ac1f91c06bbbcc7639ef93071f678bb59c5ebaff38859` | **S，已校验、解包；静态读入口与 profile bootstrap** |
| 官方源码固定快照 | root/CLI/Web `0.2.1-rc.2` | `687f282e8625c6b8d11ff58211a90524be2e4317`；ZIP `dcc4cf8df9c3cbb3d57726b7a1ad5a52c16a754dcdbc2c0a0836788976090d9f` | **S，ZIP SHA 验证并实际解包源码** |
| 官方 Web UI npm | `@deepseek-ai/dsh-web-frontend@0.0.1-rc.5`, 1,428,754 bytes | `ccadad6dcbb6f9a3c7a57802c3c2bb5958c2104ca33e9fb88135634b6d7b1516` | **S，已校验、解包 dist 并索引 chunk；源映射缺失** |
| Atlas baseline | `main` | `aa6196f550098cc46081dc6db2c376cb87ddffa5` | **S，抽查相关真实模块** |

发行物清单：`docs/research/agent-clients/2026-10-19/manifest.json`、`indexes/dsh-index.txt`，派工分支 `research/agent-reverse-dispatch-20261019`。官方上游 `https://github.com/deepseek-ai/deepseek-harness/tree/687f282e8625c6b8d11ff58211a90524be2e4317`。**版本边界不可合并：CLI npm 0.2.0-rc.2、Web npm 0.0.1-rc.5，较新源码 ZIP 0.2.1-rc.2；名字相似只作调用角色相关，不证明逐构建配对。** 上游含 `apps/desktop` 源码，不能因为本次没有官方 Desktop Windows 发行包就误称官方完全没有桌面代码；第三方 DSH Desktop 另案。

## 已明确核查的机制
1. Agent `ReactLoopAgent` 的 durable `turn/start → step/start → request/header → assistant/attempt|message → tool/call/result → step/end → turn/end`。
2. 工具 `executionMode` 动态 barrier/rolling bounded pool，提交结果与上下文维持模型顺序。
3. 子代理 `SubagentManager` local/external provider、durable parent linkage、子 Session、并发占位、cold resume、delivery 与生命周期事件。
4. 子代理可由浏览器导航进入独立 Session，通过 `subagents.prompt/interruptByParent` 走父子路由；不是 UI 假树。
5. Web `/api/remote.mux` WebSocket 多路复用，Session follow/control 基线与 live projection 分离。
6. JSONL event stream 的 write-behind、单 writer 跨进程 lease、事件格式版本迁移。
7. token-meter 按已完成 attempt 的事实汇总输入/输出/cache/reasoning；缺资料返回不可精确统计，而不是估造“精确”。
8. 额外发现：实验性 Agent Team 的任务 DAG、事件持久化；后台 jobs 的非消费式 Web follow；PTC runtime；独立 Schedule、Goal round driver、工具结果剪裁，MCP 动态重连/工具重同步，Trajectories 事件时间线。
9. 实际 CLI tarball 是 launcher 而非完整 Agent runtime：82 个 direct npm dependencies 未包含在 tarball；实物 `bin.js` 把 profile 解析、pnpm 插件管理、配置 dump 与真实 app 参数透传分派给外部依赖。源码快照比 npm 新一个 rc，不能据源码包冒认 npm 的完整 profile 装配。
10. 实际 Web npm 是静态 Vite SPA（index + 25 个 JS + 两 CSS 等资源，86 个 asset），无 source map；旧 dist 的字符串索引不能证明或否定较新源码中 subagent/trajectory/team/job 等组件是否在该旧包中运行。
11. 主动发现 Profile 是分层 plugin runtime composition，不只是预设名称：有序 bundle patch、profile patch、跨 profile home patch、argv overlay 与 telemetry 最终合成；安装 package 与 profile package 各有 resolver anchor；不兼容插件可逐包跳过，用户 profile/patch 损坏仍启动失败。
12. Host boot 固定环境 snapshot 后先安装 `.env` proxy，再 mount plugins；启动窗口内也处理 SIGTERM/SIGINT，coalesce fiber+proxy shutdown，5 秒超时后强退。均是 0.2.1 源码证据，旧 npm bundle 等价性未知。
13. 版本对照排除了把 source ZIP 当作 CLI runtime：CLI 82 个发布依赖中 73 个 DSH package name 在 ZIP 也有，但 source package 均已到 0.2.1-rc.2，而 CLI 实际 pin 在 0.2.0-rc.2；Web client package 也不在发布版本范围。

## 阅读路线
- [DISCOVERY-LEDGER.md](DISCOVERY-LEDGER.md)：`DSH_CORE-NNN` 主账（各项版本/证明级别）
- [IMPLEMENTATION-TRACE.md](IMPLEMENTATION-TRACE.md)：核心链路、输入输出、状态时序与故障边界
- [UI-AND-WORKFLOWS.md](UI-AND-WORKFLOWS.md)：可见操作到 Host 控制的双向追踪
- [ATLAS-GAP.md](ATLAS-GAP.md)：仅以 Atlas main 代码作部分/缺口/未知定级
- [EVIDENCE-INDEX.md](EVIDENCE-INDEX.md)：精确文件路径、符号和未覆盖边界
- [REUSE-CANDIDATES.md](REUSE-CANDIDATES.md)：移植、依赖、许可证
- [EXTRACTION-REQUEST.md](EXTRACTION-REQUEST.md)：三个发行资产已补采完成及证据限制
- [extracted/version-diff.md](extracted/version-diff.md)：发布版本与源码快照差异裁定；`extracted/` 保存校验、树、构件、资源及符号索引

## 重要限制与尚未完成
- 已安装确切 **CLI 0.2.0-rc.2** manifest 所需 runtime 依赖并静态检查关键旧版编译包；launcher `--version` / `--help` 实际运行通过。未动态 boot CLI profile/Agent，也未运行 **Web UI 0.0.1-rc.5**；完整 82 依赖审阅、profile composition/default mounts、旧 Web TypeScript/source identity 和 UI feature flags 仍为 **U**。Web dist 无 sourcemap，REA 静态图对 main entry 达到 heap 限制而 partial。
- 已读固定源码中多条重要调用链，但对接近两万个 tracked paths 没有声称“全面读完”；仍需穷举命令、全量 UI slots、RPC endpoints、权限与各外部 Agent provider 边界，及实际断网/重启/并发竞争的 R 证据。
- 子代理 cold resume 已证实，**任意活跃计算跨 Host 进程崩溃无缝接续尚未证实**；WebSocket carrier 可重连不表示原 stream 自动恢复。
- Atlas 比对是有范围的代码抽查，未做启动 E2E，不把未搜索完的机制判定为全项目不存在。
