# 独立会话任务：Roo Code VSIX

**单独新建 ChatGPT 会话执行，Wave 2，研究代号 `roo-code`。**
**必须先读：** `tasks/research/agent-reverse/2026-10-19/PROTOCOL.md`。
**仓库：** `unicorn-Y/Atlas`；**所有任务和采集目录所在分支** `research/agent-reverse-dispatch-20261019`。
**本会话分支（从派工分支创建）：** `research/agent-reverse-20261019-roo-code`。
**本会话专用报告目录：** `docs/research/agent-reverse/2026-10-19/roo-code/`。
**原发行包归档：** https://github.com/unicorn-Y/Atlas/releases/tag/agent-client-packages-20261019

## 确认分析的材料
Roo-Code-vsix-caf96d596d.vsix（3.54.0，收集时标为可得的历史版本）。

先看 `docs/research/agent-clients/2026-10-19/manifest.json`、`PACKAGE-INDEX.md` 和 `indexes/`。确定真实包名/SHA、发行者/版本/源码快照；没有提供的相关源代码或运行时应留缺口，不得凭想象补齐。

## 本产品独特调查路线（这些不是功能清单上限）
1. 从 VSIX 的 extension host、webview、commands、modes、task manager、tools、MCP/Skills 逐层追真实实现
2. 代理模式/自定义模式/任务分派/用户交互/失败回退/持久化/上下文等完整能力
3. 历史扩展迁移或停运的版本边界：该包是否包含仍可工作的代码，哪些依赖在线服务
4. 对 IDE 专用设计与 Atlas 可复用核心分离；保留许可和包版本证据。

**边界：** 不假定 2026 年该产品仍有持续发布；不混同 Kilo/Cline 同源实现。

## 必须落实的工作而不是口头规划
- 真实查看包内部结构、JS/TS/源代码、native 入口、协议/事件/命令、程序状态与存储；动态执行不可用则说明，不能将仅能在服务端的行为归到客户端。
- **主动发现未知机制**，每个发现都有 `ROO_CODE-NNN` ID、文件路径+函数/事件或可复现操作、证据等级 S/R/D/I/U；从 UI→后端、后端→UI 双向追踪，查后端状态生命周期、并行、重试、失败和数据流。
- 对 Atlas 最新 `main@SHA` 实际代码做差距分析，明确“没有/只画 UI/半接线/可用但不等价/已对标/未知”，给重用现成代码路径及许可，不能只拿旧任务书结论充数。
- **拿不到二进制时不要卡死**：在本分支生成 `EXTRACTION-REQUEST.md`，写可直接让本地 Codex 下载对应 Release asset、解包并上传指定必要文件/索引的机械命令和输出位置；如无法查证则标 BLOCKED，不准伪装研究完成。
- 输出且推送 `START-HERE.md`、`DISCOVERY-LEDGER.md`、`IMPLEMENTATION-TRACE.md`、`UI-AND-WORKFLOWS.md`、`ATLAS-GAP.md`、`EVIDENCE-INDEX.md` 到专用目录，必要时 `REUSE-CANDIDATES.md` 与提取指令。
- 可以边研究边 checkpoint/push；不修改 Atlas 业务代码或 main，独立会话不得向其他会话研究分支写文件。最终提供分支、commit、结果入口与未验证内容。**写几页无证据清单不算完成。**

## 直接粘贴至新会话的启动语
“开始 Atlas 竞品逆向：Roo Code VSIX。请读取 GitHub 私库 unicorn-Y/Atlas 的 research/agent-reverse-dispatch-20261019 分支中 `tasks/research/agent-reverse/2026-10-19/sessions/roo-code.md` 与统一 PROTOCOL.md。严格按真实包、源码、运行机制深入研究并主动查漏，对照 Atlas main，成果 push 到独立分支 research/agent-reverse-20261019-roo-code 的专用目录。只干这一产品，不要只写规划。”
