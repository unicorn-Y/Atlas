# Codex / ChatGPT Windows Desktop — 逆向研究入口（2026-10-19）

## 实物取证 checkpoint（本段取代下文中“尚未亲自解包”的历史状态）

**PARTIAL。** 本 lane 已亲自校验 MSIX：OpenAI.Codex `26.1013.4894.0`，948,993,815 bytes，SHA-256 `e2d892e6c22310e4b1a2928b0d3a29a066e0863d3a333754d6585c77cdafbe7f`；REA 对解包的 3,651 files / 2,346,419,207 bytes 核验通过。实际检查了 35 个 Electron build 模块和 41 个定向 webview chunks，静态确认 app-server JSON-RPC/WebSocket、`0.141.0` 协议版本常量、thread/turn mutation、contextBridge IPC 与 chunk ack、Windows computer-use pipe host 生命周期线索和 runtime executable path 映射。**静态 S；应用没启动，R=0。**

完整 app.asar 深析超时；app.asar 独立 native addon integrity mismatch 已记录，不能和 MSIX 解包检查通过混为一项。ASAR 共 21,396 项、20,362 webview assets，均未全量语义扫描；当前 chunk 调查有明确抽样边界。尚未把单一具体 UI action 从 renderer 组件闭环到 RPC，也未动态证明 `codex.exe` / runner / host 实际启动次序。见 IMPLEMENTATION-TRACE §8–9 与 EVIDENCE-INDEX 的 size/hash 表。

**历史 checkpoint 状态（已被本文件顶部实物取证段更新）：** 当时仅有采集记录和公开 App Server 源码，尚无 MSIX 解包。本次已完成精确发行包验证及有界 ASAR 模块静态分析；仍未做 Windows 客户端运行时验证。

## 固定事实与范围

- 研究分支：research/agent-reverse-20261019-codex-desktop；从 dispatch 分支 51894bbcc3dfe1ea18a6e4be25483290cbc5a0e1 建立。
- Atlas 比较基线：**main@aa6196f550098cc46081dc6db2c376cb87ddffa5**；没有修改业务代码。
- OpenAI Codex Windows x64 MSIX：OpenAI.Codex，26.1013.4894.0；948,993,815 bytes；SHA-256：e2d892e6c22310e4b1a2928b0d3a29a066e0863d3a333754d6585c77cdafbe7f。
- 固定 CLI/App Server 上游源码：openai/codex 标签 rust-v0.163.0；**仅把公开 App Server 协议及该服务器的实际实现作为独立参照**，不越界研究 Codex CLI 整体运行时，也不假定 Desktop MSIX 内置这一精确源码版本。
- MSIX 原资产：https://github.com/unicorn-Y/Atlas/releases/download/agent-client-packages-20261019/ChatGPT-x64.msix
- 采集材料：docs/research/agent-clients/2026-10-19/ 下的 manifest.json、RECOVERY-CODEX-CLAUDE.md、indexes/claude-codex-index.txt。它们**不是本会话再次解包得到的证据**。
- 目前验证层级：MSIX 版本与树形结构=历史采集机械元数据；开源 App Server=固定 tag 源码 S；官网行为=D；Desktop 具体 UI、运行时=U。**R（本版本动态运行）证据为零**。

## 已经追到而且容易漏掉的能力

1. 后台 daemon 线程 ID 快照 + cold-resume，非单纯重新建立 WebSocket；恢复不等同于不间断续跑执行中的工具。
2. 在既有活动线程上，将恢复历史回包与事件订阅原子安排，减少状态同步窗口；监听器世代与退出 drain。
3. 每线程已读位置和 revision CAS 冲突处理，区分已经读过与继续产生的结果。
4. 线程内部可持久排队、重排、删除、主动发起后续任务（实验协议）。
5. 结构化 turn/item 事件、补丁增量、PTY 交互、动态工具 client RPC、MCP widget 资源指针及 inline/fullscreen 偏好。
6. 宿主接口中 plugins、Apps、MCP、文件监视、进程/PTy、工作区设置各是不同生命周期，不应压扁成一个“插件”。
7. 工具执行分出沙箱 command/exec 和实验性的非沙箱 process/spawn，必须区分执行边界。
8. 独立 App Server shutdown admission、用户审批取消和异步外发等状态；不是看到“失败重试”就代表有相应恢复。

以上 1–8 **属于固定版本开源 App Server 的真实机制**，尚未证明 Codex Windows Desktop 对应功能被激活和怎样可视化。

## 文件索引

- [DISCOVERY-LEDGER.md](DISCOVERY-LEDGER.md)：CODEX_DESKTOP-001 起的事实、候选、证据等级。
- [IMPLEMENTATION-TRACE.md](IMPLEMENTATION-TRACE.md)：启动→通信→消息→任务→异常→恢复的代码与契约、关键机制。
- [UI-AND-WORKFLOWS.md](UI-AND-WORKFLOWS.md)：官方可见操作 vs 包内/动态未证的 UI 清单，追踪路径。
- [ATLAS-GAP.md](ATLAS-GAP.md)：**直接读过 main** 的相应 Atlas 前后端调用链，不把按钮误当等价实现。
- [EVIDENCE-INDEX.md](EVIDENCE-INDEX.md)：包、源码、行号、缺失与核查顺序。
- [EXTRACTION-REQUEST.md](EXTRACTION-REQUEST.md)：本地 Windows Codex 可机械执行、返回可审计文件的取证单。
- [REUSE-CANDIDATES.md](REUSE-CANDIDATES.md)：开源代码、协议/范式及授权边界。

## 当前阻塞与解锁

当前仍缺 **完整 ASAR/webview 资产覆盖与 Windows 运行态**；全量 ASAR 深析超时，因此已有 JS 检查是抽样静态证据。完整 UI→RPC action 链及真实 Desktop 的去敏运行日志仍需后续取得，才能判定 R 级行为。

本阶段为**已实做代码追踪的研究 checkpoint**，不是研究终版，不得合并成“Codex Desktop 功能已经对齐”。
