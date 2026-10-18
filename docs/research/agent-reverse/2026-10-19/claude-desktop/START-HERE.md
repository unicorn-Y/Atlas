# Claude Desktop / Cowork — checkpoint 1（2026-10-19）

**结论：PARTIAL / BLOCKED，绝非已完成安装包深度逆向。** 已核验产品归档清单、官方 2026 年架构变更，并逐文件核对 Atlas main 的进程、事件、会话、恢复与 UI 代码；但本会话的 GitHub 文本接口拒绝非 UTF-8 / 超大二进制，未实际读取 297 MB MSIX 内的 app.asar 或 cowork-svc.exe，也未运行 Claude Desktop。因此**Claude 内部 IPC、渲染器实现和本地 Cowork service 的代码级结论为零**，不能杜撰调用链。最小机械取证要求见 [EXTRACTION-REQUEST.md](./EXTRACTION-REQUEST.md)。

## 固定样本
- 仓库：`unicorn-Y/Atlas`，基线分支 `research/agent-reverse-dispatch-20261019`。
- Claude Desktop enterprise Windows x64 MSIX **2.42304.0**，Release 文件 `claude-desktop-x64-2bf309665f.msix`，297,191,037 bytes，SHA256 `2bf309665f0de4eaa76a7e64033594e6f73ceb6413c60080f72f3ce640fa24ee`。
- 归档：<https://github.com/unicorn-Y/Atlas/releases/tag/agent-client-packages-20261019>。源索引：`docs/research/agent-clients/2026-10-19/manifest.json`、`indexes/claude-codex-index.txt`。采集记录声称 MSIX 展开 4,443 个文件，但完整树文本仍在**采集机器本地 staging**，目前未上传。
- Consumer Setup **未取得**，`region_unavailable`；企业版与 consumer 二进制等价性 UNKNOWN。不要假定企业版包完整承载 2026 年新版云 Cowork。
- Atlas `main` 固定于 `aa6196f550098cc46081dc6db2c376cb87ddffa5`（读取时的 HEAD）。

## 目前真正做过的事情
1. 用已连接 GitHub 权限读取派工协议、任务书、manifest、index、收藏状态、实际 main tree（1,412 个条目）及多份 Atlas 真实源码的精确行段。
2. 在 Atlas 主进程确认 `before-quit -> stopManagedBackend`；独立 Hub 另可存活，不应混为一谈。
3. 在 Atlas 运行时确认 `runtime_runs` 持久化元信息，重启对 active run 直接标 `failed`；WebSocket `resume` 只重放当前 `run.events`；`resume_from` 有计划恢复入口，但不能算自动续执行。
4. 在 Atlas 的 `backend-adapter/src/client.ts` 查到本机 WS 重连、指数退避、游标存 localStorage；`run.start`、approval、steer、subtask、作业时间线确有前后端接线。不能因 UI 简单就认定所有是空壳。
5. 发现竞品**2026-09-16 聊天与 Cowork 逐步合流**、**2026-10-06 后 cloud/local 执行边界改变**，并从官方架构文档确认云端会话、按需本机设备代理、跨端持续执行。本部分仅 **D 级官方声明**，并非本 MSIX 的可执行实现证据。

## 阅读顺序
- [DISCOVERY-LEDGER.md](./DISCOVERY-LEDGER.md)：发现 ID、来源与可确认级别
- [IMPLEMENTATION-TRACE.md](./IMPLEMENTATION-TRACE.md)：官方可确认链路；Atlas 真正可追踪链路；未知接口
- [UI-AND-WORKFLOWS.md](./UI-AND-WORKFLOWS.md)：交互与任务时序（标注尚未动态验证）
- [ATLAS-GAP.md](./ATLAS-GAP.md)：逐文件对照 main，不以旧矩阵定性
- [EVIDENCE-INDEX.md](./EVIDENCE-INDEX.md)：包、官方文档、精确源码锚点与证据边界
- [EXTRACTION-REQUEST.md](./EXTRACTION-REQUEST.md)：交本地 Codex 的最小取证（不负责研究结论）
- [REUSE-CANDIDATES.md](./REUSE-CANDIDATES.md)：可合法吸收的设计、接口或开源实现方向

## 阻塞与验收状态
- **未完成**：MSIX 实体结构独立 hash、asar 展开、打包 JS 的精确调用链、Cowork exe 静态符号/协议、RPC 流/状态库、UI 路由真实枚举、启动运行/断网重启实验、云端服务器内部实现。
- **已完成**：真实性标注、Atlas 明确缺口核实、官方架构差异识别、可执行机械取证任务。
- **下一验收门**：本地 Codex 仅提取经过脱敏的代码片段、符号、文件树并上传本独立分支；此会话再根据实物证据增补 S 类 ID，后才可声称“深度逆向”。

研究中不修改 Atlas 正式源码，不把官方网页宣传当作 app.asar 逆向。