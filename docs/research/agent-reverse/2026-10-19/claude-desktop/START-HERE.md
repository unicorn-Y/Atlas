# Claude Desktop / Cowork — checkpoint 1（2026-10-19）

**结论：WORK IN PROGRESS / PARTIAL，尚未最终验收。** 固定 MSIX 与 ASAR 静态身份已复核；补入 452 个相关文件的解析覆盖数据和 artifact scheduled-task 的 renderer bridge→generated IPC→guarded main handler→scheduler 闭环。REA 全包分析的语义图受限而截断，故生成 IPC/主聊天 route/action、Go service handler 与状态持久化仍未闭合。无受控运行证据。详见 [COVERAGE.md](./COVERAGE.md) 与 [FINISH-GATES.md](./FINISH-GATES.md)。

## 固定样本
- 仓库：`unicorn-Y/Atlas`，基线分支 `research/agent-reverse-dispatch-20261019`。
- Claude Desktop enterprise Windows x64 MSIX **2.42304.0**，Release 文件 `claude-desktop-x64-2bf309665f.msix`，297,191,037 bytes，SHA256 `2bf309665f0de4eaa76a7e64033594e6f73ceb6413c60080f72f3ce640fa24ee`。
- 归档：<https://github.com/unicorn-Y/Atlas/releases/tag/agent-client-packages-20261019>。源索引：`docs/research/agent-clients/2026-10-19/manifest.json`、`indexes/claude-codex-index.txt`。MSIX 已核对并展开 4,443 个文件，清单已上传为 [evidence/msix-tree.tsv](./evidence/msix-tree.tsv)，共 4,443 个文件条目。
- Consumer Setup **未取得**，`region_unavailable`；企业版与 consumer 二进制等价性 UNKNOWN。不要假定企业版包完整承载 2026 年新版云 Cowork。
- Atlas `main` 固定于 `aa6196f550098cc46081dc6db2c376cb87ddffa5`（读取时的 HEAD）。

## 目前真正做过的事情
1. 用已连接 GitHub 权限读取派工协议、任务书、manifest、index、收藏状态、实际 main tree（1,412 个条目）及多份 Atlas 真实源码的精确行段。
2. 在 Atlas 主进程确认 `before-quit -> stopManagedBackend`；独立 Hub 另可存活，不应混为一谈。
3. 在 Atlas 运行时确认 `runtime_runs` 持久化元信息，重启对 active run 直接标 `failed`；WebSocket `resume` 只重放当前 `run.events`；`resume_from` 有计划恢复入口，但不能算自动续执行。
4. 在 Atlas 的 `backend-adapter/src/client.ts` 查到本机 WS 重连、指数退避、游标存 localStorage；`run.start`、approval、steer、subtask、作业时间线确有前后端接线。不能因 UI 简单就认定所有是空壳。
5. 发现竞品**2026-09-16 聊天与 Cowork 逐步合流**、**2026-10-06 后 cloud/local 执行边界改变**，并从官方架构文档确认云端会话、按需本机设备代理、跨端持续执行。本部分仅 **D 级官方声明**，并非本 MSIX 的可执行实现证据。

## 阅读顺序
- [COVERAGE.md](./COVERAGE.md)：固定包覆盖数量、解析结果、限制与 G0-G6 状态
- [SURFACE-MAP.tsv](./SURFACE-MAP.tsv)：已追踪 UI/API surface 和明确 U 项
- [END-TO-END-TRACES.md](./END-TO-END-TRACES.md)：计划任务、MCP tool、legacy VM service 的静态调用链与断点
- [ATLAS-IMPLEMENTATION-BACKLOG.md](./ATLAS-IMPLEMENTATION-BACKLOG.md)：对 Atlas main 的机制差异与候选实现议题
- [FINISH-GATES.md](./FINISH-GATES.md)：G0-G7 的当前验收状态与未完成项
- [DISCOVERY-LEDGER.md](./DISCOVERY-LEDGER.md)：发现 ID、来源与可确认级别
- [IMPLEMENTATION-TRACE.md](./IMPLEMENTATION-TRACE.md)：官方可确认链路；Atlas 真正可追踪链路；未知接口
- [UI-AND-WORKFLOWS.md](./UI-AND-WORKFLOWS.md)：交互与任务时序（标注尚未动态验证）
- [ATLAS-GAP.md](./ATLAS-GAP.md)：逐文件对照 main，不以旧矩阵定性
- [EVIDENCE-INDEX.md](./EVIDENCE-INDEX.md)：包、官方文档、精确源码锚点与证据边界
- [EXTRACTION-REQUEST.md](./EXTRACTION-REQUEST.md)：交本地 Codex 的最小取证（不负责研究结论）
- [REUSE-CANDIDATES.md](./REUSE-CANDIDATES.md)：可合法吸收的设计、接口或开源实现方向

## 阻塞与验收状态
- **已实证（S）**：固定包/核心文件哈希、manifest/文件树、ASAR入口、ClaudeVM→命名管道 RPC 协议、Cowork artifact 的排程任务及 MCP tool handler、服务身份连接门禁、MCPB验签与 TOCTOU guard、PTY/file-index worker 等（见 `evidence/`）。
- **未完成 / U**：完整动态 IPC handler 配对、所有 renderer routes/状态reducers、端到端 session/event 持久化/recovery、service 安装/启动父进程和 Go handler 全调用图、consumer 包等价性、真实应用运行及云服务内部协议。
- **当前可继续项**：补齐 route/action 和 dynamic IPC 调用配对；用 Go-aware tooling 还原服务函数入口与调用链；若合规独立空白 Windows profile 可用，再做有限启动/关闭观察。云端实现继续标 U。
- **新增 checkpoint**：提交 `60a624b2e741fef1377a31169a19d7daa9b7564a`。REA 在精确包上解析 437 个 JS-bearing 文件、0 parse failures；语义图 partial/truncated。不要把 coverage count 当作所有机制已检查。

研究中不修改 Atlas 正式源码，不把官方网页宣传当作 app.asar 逆向。
