# 独立会话任务：Cline VSIX + CLI Runtime

**单独新建 ChatGPT 会话执行，Wave 2，研究代号 `cline`。**
**必须先读：** `tasks/research/agent-reverse/2026-10-19/PROTOCOL.md`。
**仓库：** `unicorn-Y/Atlas`；**所有任务和采集目录所在分支** `research/agent-reverse-dispatch-20261019`。
**本会话分支（从派工分支创建）：** `research/agent-reverse-20261019-cline`。
**本会话专用报告目录：** `docs/research/agent-reverse/2026-10-19/cline/`。
**原发行包归档：** https://github.com/unicorn-Y/Atlas/releases/tag/agent-client-packages-20261019

## 确认分析的材料
Cline-vsix-aac83af051.vsix（4.1.25）、cline-npm-f8c8b3a701.tgz 与 cline-cli-windows-x64-npm-bca9c4be2d.tgz（3.0.73）。

先看 `docs/research/agent-clients/2026-10-19/manifest.json`、`PACKAGE-INDEX.md` 和 `indexes/`。确定真实包名/SHA、发行者/版本/源码快照；没有提供的相关源代码或运行时应留缺口，不得凭想象补齐。

## 本产品独特调查路线（这些不是功能清单上限）
1. 解开 VSIX 的真实 webview UI、任务链路、自动工具调用、审批/计划/执行模式、恢复与 UI 状态
2. CLI、extension host、agent runtime、MCP/Skills、browser/computer/terminal 与消息协议
3. 分析 token/context usage、缓存与费用统计及会话历史内部机制
4. 识别插件为宿主加的能力，与 Cline 原生能力、第三方扩展区分。

**边界：** VSIX 与 CLI 版本不同，不得宣称每项 Webview 能力都已在 CLI 3.0.73。

## 必须落实的工作而不是口头规划
- 真实查看包内部结构、JS/TS/源代码、native 入口、协议/事件/命令、程序状态与存储；动态执行不可用则说明，不能将仅能在服务端的行为归到客户端。
- **主动发现未知机制**，每个发现都有 `CLINE-NNN` ID、文件路径+函数/事件或可复现操作、证据等级 S/R/D/I/U；从 UI→后端、后端→UI 双向追踪，查后端状态生命周期、并行、重试、失败和数据流。
- 对 Atlas 最新 `main@SHA` 实际代码做差距分析，明确“没有/只画 UI/半接线/可用但不等价/已对标/未知”，给重用现成代码路径及许可，不能只拿旧任务书结论充数。
- **拿不到二进制时不要卡死**：在本分支生成 `EXTRACTION-REQUEST.md`，写可直接让本地 Codex 下载对应 Release asset、解包并上传指定必要文件/索引的机械命令和输出位置；如无法查证则标 BLOCKED，不准伪装研究完成。
- 输出且推送 `START-HERE.md`、`DISCOVERY-LEDGER.md`、`IMPLEMENTATION-TRACE.md`、`UI-AND-WORKFLOWS.md`、`ATLAS-GAP.md`、`EVIDENCE-INDEX.md` 到专用目录，必要时 `REUSE-CANDIDATES.md` 与提取指令。
- 可以边研究边 checkpoint/push；不修改 Atlas 业务代码或 main，独立会话不得向其他会话研究分支写文件。最终提供分支、commit、结果入口与未验证内容。**写几页无证据清单不算完成。**

## 直接粘贴至新会话的启动语
“开始 Atlas 竞品逆向：Cline VSIX + CLI Runtime。请读取 GitHub 私库 unicorn-Y/Atlas 的 research/agent-reverse-dispatch-20261019 分支中 `tasks/research/agent-reverse/2026-10-19/sessions/cline.md` 与统一 PROTOCOL.md。严格按真实包、源码、运行机制深入研究并主动查漏，对照 Atlas main，成果 push 到独立分支 research/agent-reverse-20261019-cline 的专用目录。只干这一产品，不要只写规划。”
