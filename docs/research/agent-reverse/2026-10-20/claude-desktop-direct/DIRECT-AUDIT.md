# Claude Desktop / Cowork — GPT-6 direct research, checkpoint 01 (2026-10-20)

**研究执行者：本 ChatGPT 会话直接读取用户私有 GitHub 仓库并独立进行目录差集与覆盖审查。未派工给 ZCode、Codex、DSH 或本地执行 Agent。**

**状态：PARTIAL（初次独立清点，不是完整解剖）。**

## 1. 固定样本与材料来源
- 包版本：Claude Desktop Windows x64 enterprise `2.42304.0`。固定 MSIX：`claude-desktop-x64-2bf309665f.msix`。
- 上游包登记：`docs/research/agent-clients/2026-10-19/manifest.json`（`research/agent-client-packages-20261019`）。
- 来源安装包大小：297,191,037 bytes；来源登记 SHA256：`2bf309665f0de4eaa76a7e64033594e6f73ceb6413c60080f72f3ce640fa24ee`。
- 上一轮取证目录：`docs/research/agent-reverse/2026-10-19/claude-desktop/evidence/`（`research/agent-reverse-20261019-claude-desktop`）；目录文件、IPC/Runtime/UI TSV 和已有静态 trace 通过 GitHub 连接直接读取。
- **重要限制**：本会话所用 GitHub 连接支持私有仓库文本，但不能下载 GitHub Release 的 297 MB 二进制；本会话未直接打开 MSIX/ASAR 原始字节、未运行 Claude.exe，不能把过去会话的二进制分析当作本人重新解析。本次独立复核对象是已上传的完整路径索引与短证据记录。

## 2. 本次独立计算的覆盖数据
| 取证对象 | 本次独立计算 | 解释 |
|---|---:|---|
| MSIX 文件索引 | 4443 行 | 从仓库的 msix-tree.tsv 计行；未独立重哈希 MSIX 原件 |
| ASAR 全部路径 | 548 条 | 直接逐行清点已有 asar-tree.txt |
| ASAR 目录路径 | 42 条 | 依据已有路径集合的前缀关系判断 |
| ASAR 文件路径 | 506 条 | 独立求出非目录条目 |
| 本会话输出对象账 | 548 条 | 每条已有 ASAR 路径都分配唯一 ID，逐条列名/类型/分层/未解析状态 |

ASAR 文件条目按目录归属：`electron-main-preload-worker` 380；`renderer-ui` 60；`package-root-or-other` 4；`third-party-runtime` 45；`bundled-resource-extension` 17。这只表示存量文件结构，不代表已解释对应功能。

## 3. 找到的实物级模块族（由真实路径名确认存在）
| 层 | 文件示例 | 可确认的事实 | 功能验证 |
|---|---|---|---|
| Electron main/preload | `.vite/build/index.chunk-lzaSYO3Q.js`, `.vite/build/mainView.js` | 主进程 bundle 与 preload 文件存在；旧研究对 IPC wrapper 有定位 | **需本会话复核原始代码** |
| Artifact/Cowork bridge | `.vite/build/coworkArtifact.js` | 实际存在该模块；既有 trace 记载 callMcpTool / askClaude / runScheduledTask / navigateHost / openExternalUrl | **既有追踪，尚非本人字节级复核** |
| Computer Use | `.vite/build/computerUseTeach.js`, `.vite/build/computerUseWatchRecord.js` | 这两个具有 computerUse 名称的模块已打包 | **文件名不足以证明实时操作能力** |
| 渲染界面 | `.vite/renderer/main_window/`, `quick_window/`, `buddy_window/`, `about_window/`, `find_in_page/`, `local_exec_consent/` | 六组渲染 HTML/asset 入口 | **UI 操作和状态关联未全部闭合** |
| Worker | `.vite/build/file-index-worker/fileIndexWorker.js`, `.vite/build/heavy-work-worker/heavyWorkWorker.js` | 文件索引与后台重任务 worker 模块存在 | **调用覆盖未独立验证** |
| MCP | `.vite/build/mcp-runtime/nodeHost.js`, `directMcpHost.js` | MCP host 模块存在 | **宿主差异与完整 tool 语义待复核** |
| Skills | `resources/bundled-skills/{docx,pptx,xlsx,pdf,pdf-reading,frontend-design}.skill` | 6 个具体内置技能文件存在 | **是否均可用需运行验证** |
| 内置连接组件 | `resources/github-mcp/github-mcp-server.exe`, `resources/office365-mcp/*` | 打包了 GitHub、Office365 相关可执行/依赖组件 | **部署/注册/使用条件未知** |
| Windows service | MSIX: `app/resources/cowork-svc.exe` | 存在 13,761,360 字节服务映像，已有 Go/VM trace | **本会话未直接反汇编** |

注：引用以前的 `module-traces.md` / `trace-snippets/renderer-ipc.md` 只作已发现线索，不提升为本会话亲自验证的原始代码结论。

## 4. 已有结果为何未达到“一个不漏”的验收
我直接读取了四份现有 TSV，记录数量为：
- `ipc-map.tsv`：**8** 条；主进程动态 IPC 大量没有 registerer/caller/params 配对。
- `ui-route-action.tsv`：**8** 条；部分界面仅列出 unresolved。
- `runtime-map.tsv`：**8** 条；cloud agent loop 和服务启动/持久化尚未闭合。
- `event-schema.tsv`：**7** 条；明确没有全部 agent event union。

这四份表不是全部实装能力的列表，只是少量已追踪样本。也不能拿静态分析器报告的 437 个 JS 解析成功直接换算为 100% 语义覆盖。

## 5. 逐项验收缺口（当前全部保持 OPEN）
1. `[OPEN-BINARY]` 本会话对固定 SHA 的原始 MSIX、ASAR 与 cowork-svc.exe 独立解析（当前 GitHub 连接无法提供 Release 二进制）。
2. `[OPEN-FILE]` 506 个 ASAR 文件路径逐项语义解释：目前已建对象清单，但多数仅有路径与粗层级。
3. `[OPEN-UI]` 所有 HTML/renderer bundles → 页面/菜单/点击动作 → 状态写入 → IPC/网络调用。
4. `[OPEN-IPC]` 生成式 channel 的注册、preload wrapper、发送者、事件消费者完整配对。
5. `[OPEN-AGENT]` chat/cloud Cowork 的 agent loop、工具调用、上下文、持久化/恢复与云端边界。
6. `[OPEN-SVC]` app/service 启停、Windows SCM、Go handler、VM 生命周期和错误路径。
7. `[OPEN-RUNTIME]` 无人值守的隔离运行：启动/任务/取消/重启/断线/跨端恢复。现有研究 R=0，本次也未运行。
8. `[OPEN-CHANNEL]` Consumer Setup 与 enterprise MSIX 的版本、组件和账号 rollout 差异。

## 6. 下步实际取证的边界与交付
- 我不会让别的 Agent 代替做研究。这个分支单独保存我亲自分析的对象登记和结论。
- 在能访问原始包字节之前，可继续从仓库既有文件路径、静态短证据和官方公开文档逐项核查；必须把这种分析标为二次核验，不写成独立二进制逆向。
- **要由本会话真正拆进每个函数/调用链，需要可在此会话直接读取的原始 MSIX/ASAR 或提取文件**。GitHub Release 网页链接本身不等于二进制已读。
- 无论后续多少阶段，最终交付保持：全部文件→全部可解析类/函数→UI/IPC→运行时→用途→调用关系→依据→未知项，机械计算覆盖率而非宣称“100% 全破解”。

## 数据账入口
- [ASAR 548 条完整对象账](./ASAR-OBJECT-LEDGER.tsv)
- [旧 MSIX 4443 条原始索引](../../2026-10-19/claude-desktop/evidence/msix-tree.tsv)
- [旧 ASAR 原始路径索引](../../2026-10-19/claude-desktop/evidence/asar-tree.txt)

**研究判定：目录覆盖可核对；机制覆盖尚未验收。**
