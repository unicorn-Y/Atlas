# 独立会话任务：Windsurf / Devin Desktop 及可得官方扩展

**单独新建 ChatGPT 会话执行，Wave 2，研究代号 `windsurf`。**
**必须先读：** `tasks/research/agent-reverse/2026-10-19/PROTOCOL.md`。
**仓库：** `unicorn-Y/Atlas`；**所有任务和采集目录所在分支** `research/agent-reverse-dispatch-20261019`。
**本会话分支（从派工分支创建）：** `research/agent-reverse-20261019-windsurf`。
**本会话专用报告目录：** `docs/research/agent-reverse/2026-10-19/windsurf/`。
**原发行包归档：** https://github.com/unicorn-Y/Atlas/releases/tag/agent-client-packages-20261019

## 确认分析的材料
windsurf-devin-desktop-win-x64-1f9d06554f.exe（官方页面实际跳转 Devin Desktop 3.10.67）；Windsurf-Visual-Studio-Plugin-IDE-plugin-source-snapshot--2ba56c1e67.tar。VS Code/JetBrains 插件及 MCP catalog 尚未采集。

先看 `docs/research/agent-clients/2026-10-19/manifest.json`、`PACKAGE-INDEX.md` 和 `indexes/`。确定真实包名/SHA、发行者/版本/源码快照；没有提供的相关源代码或运行时应留缺口，不得凭想象补齐。

## 本产品独特调查路线（这些不是功能清单上限）
1. 先确认品牌/产品版本关系，仔细核实 Windsurf→Devin 的重定向是否意味着完全相同功能、不同产品或仅下载导航变化
2. IDE 辅助与独立 Agent 的所有工作流、后台任务、上下文感知、编辑工具、计划、规则、模式、模型路由
3. 安装包内部组件、IDE 插件协作、双向消息/状态/会话持久化及 remote executor 的调用协议
4. 明确未知与缺包，对 VS Code/JetBrains 插件与 MCP catalog 形成最小补采请求。

**边界：** 不要把 Windsurf、Devin、Visual Studio 插件硬合成一套已确认相同的内核。

## 必须落实的工作而不是口头规划
- 真实查看包内部结构、JS/TS/源代码、native 入口、协议/事件/命令、程序状态与存储；动态执行不可用则说明，不能将仅能在服务端的行为归到客户端。
- **主动发现未知机制**，每个发现都有 `WINDSURF-NNN` ID、文件路径+函数/事件或可复现操作、证据等级 S/R/D/I/U；从 UI→后端、后端→UI 双向追踪，查后端状态生命周期、并行、重试、失败和数据流。
- 对 Atlas 最新 `main@SHA` 实际代码做差距分析，明确“没有/只画 UI/半接线/可用但不等价/已对标/未知”，给重用现成代码路径及许可，不能只拿旧任务书结论充数。
- **拿不到二进制时不要卡死**：在本分支生成 `EXTRACTION-REQUEST.md`，写可直接让本地 Codex 下载对应 Release asset、解包并上传指定必要文件/索引的机械命令和输出位置；如无法查证则标 BLOCKED，不准伪装研究完成。
- 输出且推送 `START-HERE.md`、`DISCOVERY-LEDGER.md`、`IMPLEMENTATION-TRACE.md`、`UI-AND-WORKFLOWS.md`、`ATLAS-GAP.md`、`EVIDENCE-INDEX.md` 到专用目录，必要时 `REUSE-CANDIDATES.md` 与提取指令。
- 可以边研究边 checkpoint/push；不修改 Atlas 业务代码或 main，独立会话不得向其他会话研究分支写文件。最终提供分支、commit、结果入口与未验证内容。**写几页无证据清单不算完成。**

## 直接粘贴至新会话的启动语
“开始 Atlas 竞品逆向：Windsurf / Devin Desktop 及可得官方扩展。请读取 GitHub 私库 unicorn-Y/Atlas 的 research/agent-reverse-dispatch-20261019 分支中 `tasks/research/agent-reverse/2026-10-19/sessions/windsurf.md` 与统一 PROTOCOL.md。严格按真实包、源码、运行机制深入研究并主动查漏，对照 Atlas main，成果 push 到独立分支 research/agent-reverse-20261019-windsurf 的专用目录。只干这一产品，不要只写规划。”
