# ZCode Desktop / Agent Runtime 逆向研究 — START HERE

> **阶段结论：PARTIAL（3.15.3 实物已取得并完成 runtime AST 与关键机制锚点；app.asar 深度图、全量 UI/IPC 和运行实测仍未完成）。** ZCode Desktop 3.15.3 的真实 Windows x64 EXE、独立嵌入 CJS 和 3.15.1 源码快照均已按 manifest 字节数/SHA256 核实。3.15.3 CJS 经 Acorn 8.16.0 成功解析；首轮已证实 tool schedule/queued/execute、child background detach、branchGeneration 任务状态、workflow journal/schema 和 Retry-After helper 的打包代码锚点。旧源码快照仍为 3.15.1，不代表 3.15.3 全部源码。

## 研究基线、产物与边界

- 目标：ZCode Desktop Windows x64 **3.15.3**，安装包 SHA256 **bc8100ba4377256fbe1531d549b4775f18e3ba21768b6294ca50751cd461faca**；内嵌 resources/glm/zcode.cjs 15,127,039 bytes，SHA256 **31965ce1d5d4a808ef156784f67996de42ccab335591d2386a61ea8f6f506a54**。本会话独立重算三资产 SHA/大小并实际解析 CJS，同时静态检查 retained main/host/preload/scheduler bundles；来源/完整性边界见 EVIDENCE-INDEX。
- 本次**实际读取并分析**：zai-org/ZCode 固定源码提交 **aac4755666d09fdcd70272fcf063c077a639015f**（root package.json 为 3.15.1）；Atlas main **aa6196f550098cc46081dc6db2c376cb87ddffa5**；以及官方 3.15.3 Windows x64 安装包和其中 `resources/glm/zcode.cjs` 的真实字节。
- 研究分支从 research/agent-reverse-dispatch-20261019 建立；**没有修改 Atlas 业务源码**。
- 覆盖：3.15.1 核心 turn loop、subagent、dynamic workflow、SQLite journal、上下文、MCP、插件、Electron 进程、UI、后台调度，以及 Atlas main 对照；3.15.3 CJS AST 统计和字节偏移锚点；PE 资源静态清单。REA 对 `resources/glm` 扫描含 360 个相关文件、294 个成功解析 JS、186 个模块、0 个 parse failure；语义图 coverage partial。没有运行未知 EXE，也没有启动 Electron；R=0。
- 已发现但尚欠闭环：retained `app.asar.extracted/out` 真实含 main/host/preload/renderer/scheduler 与 plugin-sandbox bundle；本轮核到 main fork Host、MessageChannelMain 双端 transfer、renderer reload AttachServicePort、typed Host facade、sandbox ipc bridge、部分导航 schema。尚欠逐文件 ASAR entry integrity 对照、完整 UI surface / host event subscriptions、3.15.1 同名源码映射及 Agent/task 异常恢复。全 application 目录 REA 与单独 app.asar 调用均超时；严格 ASAR 校验发现 unpacked `node-pty` companion integrity mismatch，必须保留未解决状态。

## 报告导航

| 文件 | 内容 |
|---|---|
| [DISCOVERY-LEDGER.md](DISCOVERY-LEDGER.md) | 逐项发现、25 条 3.15.1 源码确认事实、版本证据等级与盲区 |
| [IMPLEMENTATION-TRACE.md](IMPLEMENTATION-TRACE.md) | 从交互/父子任务到模型工具调用、journal、IPC、异常恢复的调用链 |
| [UI-AND-WORKFLOWS.md](UI-AND-WORKFLOWS.md) | 能找到的页面、可操作动作、流式状态、后台工作流及待实测路径 |
| [ATLAS-GAP.md](ATLAS-GAP.md) | Atlas main@aa6196f 的正反对照；已接线、部分功能、缺口及吸收锚点 |
| [EVIDENCE-INDEX.md](EVIDENCE-INDEX.md) | 包 SHA、源码固定路径与行号、调查范围和未触达部分 |
| [EXTRACTION-REQUEST.md](EXTRACTION-REQUEST.md) | 给本地 Codex 的限定式、可机械执行的 3.15.3 取证/上传任务 |
| [REUSE-CANDIDATES.md](REUSE-CANDIDATES.md) | Apache-2.0 源码复用边界与 Python/Electron 适配建议 |
| [extracted-3153/DESKTOP-IPC-ANCHORS.md](extracted-3153/DESKTOP-IPC-ANCHORS.md) | 同版 retained desktop bundle 的 hash、main/host/preload RPC 和 sandbox 静态锚点 |
| [ATLAS-GAP.md](ATLAS-GAP.md) | 本轮按 Atlas main 实际代码复核的 Agent、事件、journal、retry 与 MCP Apps 对照 |
| [extracted-3153/TRACE-3153-PLUGIN-UI.md](extracted-3153/TRACE-3153-PLUGIN-UI.md) | 3.15.3 MCP Apps host/RPC/registry/sandbox 的逐节点部分链和 UNKNOWN 边界 |
| [extracted-3153/TRACE-3153-AGENT.md](extracted-3153/TRACE-3153-AGENT.md) | 3.15.3 tool queue/execute 与 background child 的字节锚点 |
| [extracted-3153/TRACE-3153-WORKFLOW.md](extracted-3153/TRACE-3153-WORKFLOW.md) | 3.15.3 journal migration/replay helper 的字节锚点 |
| [COVERAGE.md](COVERAGE.md) | G1 package inventory, byte totals, parser failures and ASAR mismatch boundary |
| [SURFACE-MAP.tsv](SURFACE-MAP.tsv) | Machine-readable 3.15.3 desktop/runtime and Atlas UI/service surfaces |
| [END-TO-END-TRACES.md](END-TO-END-TRACES.md) | Packaged MCP App/task paths and bounded startup probe |
| [ATLAS-IMPLEMENTATION-BACKLOG.md](ATLAS-IMPLEMENTATION-BACKLOG.md) | Research-only Atlas comparison backlog against pinned main |
| [FINISH-GATES.md](FINISH-GATES.md) | Current G0–G7 status and explicit WIP stop conditions |

## 重要结论与可行动作

1. **先按真实数据链抄，别只抄 UI。** workflow 子进程经 NDJSON 把 ask 请求送给父进程的 WorkflowEngine，driver 对接持久 journal；失败、停止和恢复是数据协议，不是用户界面状态。参考 IMPLEMENTATION-TRACE 的链路 C。
2. **把后台结果回流做成明确命令。** ZCode 子代理完成事件经运行时命令队列重新进入父 agent 的后续模型请求，且用 branchGeneration 避免旧分支结果污染新上下文；不是单纯滚动显示通知。
3. **可复用机制不是“模型强弱”。** 自适应并发在 429 降为 0.75 倍、连续 4 次成功且存在等待请求时加 1，5 分钟拒绝记忆影响 seed；有准确源码证明。
4. **Atlas 不能按“有没有这个按钮”打缺口。** Atlas 已有 Hermes 真正运行、工具、MCP、持久 SessionDB、后台 Hub、scheduler、分支、子代理 worktree、插件等；缺口必须具体到结构化工作流 journal、沙箱 UI、ZCode 原生会话适配，而不是粗暴说 Atlas 没 Agent。
5. **先完成 3.15.3 的机械提取，再谈同版落地。** 已固定三个资产哈希；本次未读取二进制，不允许由 3.15.1 的源码推断 3.15.3 的确切执行行为或二者实现一致。

## 最新续工状态 (2026-10-19)

此节覆盖上文首次 checkpoint 的陈旧限制说明。3.15.3 ASAR 包含 27,856 个文件条目，其中 22,902 个 JS/TS/HTML 家族条目；Acorn 8.16.0 从归档逐文件解析了 18,936/18,943 个 JS/CJS/MJS 输入；`out/` 下 2,794 个代码模块全部解析通过。MCP Apps 的 host RPC → 主进程 provenance-bound registry → sandbox SDK 有新增同版链路，renderer event consumer 已补到 `notifyAppToolCall`，但 UI attach、service producer、模型工具注入和 result return 仍未知。

本地启动观察到 ZCode 3.15.3 Electron 页面（`ev_49e6e6ea5689b868e98358ce0348ca05ec529fb74d25a2ad8391cf86c235c0d2` / `ev_dc5735b0dfdda2f1527d9551626b2ed373b9d12085b6a5b4ce9474316277f966`），但六个子进程显示默认 `C:\Users\25011\AppData\Roaming\ZCode` profile，与请求的 worktree profile 不一致；已立即结束，没有运行 Agent turn。该运行证据仅证明启动/page 可见，不证明真实任务，G4 仍 partial/unsafe。

ASAR metadata 申报的 node-pty 两个 unpacked binary 与留存文件的大小和 SHA 均不匹配；差异限于这两个 native companion。完整 gate 与边界见 [FINISH-GATES.md](FINISH-GATES.md)。

## 交付状态

**WIP：原 25 个 ZCODE-001..025（3.15.1）+ 3.15.3 同版观察 ZCODE-028..039；本轮新增 ZCODE-040..048。** 3.15.3 真实 Runtime/ASAR/renderer page 均有静态或有限启动观察；完整 UI-action/RPC 目录、ASAR per-entry integrity、MCP App result loop、Agent 实测仍未完工，不得宣称穷尽。

源代码固定快照：[ZCode v3.15.1](https://github.com/zai-org/ZCode/tree/aac4755666d09fdcd70272fcf063c077a639015f) · [Atlas main 基准](https://github.com/unicorn-Y/Atlas/tree/aa6196f550098cc46081dc6db2c376cb87ddffa5) · [原包归档](https://github.com/unicorn-Y/Atlas/releases/tag/agent-client-packages-20261019)

当前仍存在本机可继续调查的模块和调用链，状态为 **WORK IN PROGRESS**。
