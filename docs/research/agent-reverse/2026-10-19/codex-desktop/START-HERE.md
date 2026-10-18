# Codex / ChatGPT Windows Desktop — 逆向研究入口（2026-10-19）

**结论：PARTIAL / DESKTOP PACKAGE EXTRACTION BLOCKED。** 已对官方 MSIX 的采集原始记录做逐项核对，阅读同版本固定快照的 Codex App Server **真实源文件与调用逻辑**，并对 Atlas main 的相关前后端实际代码进行差异追踪；**尚未亲自解包 949 MB 桌面主程序，未做 Windows 客户端运行时验证**。本阶段不能声称掌握 Codex Desktop 完整前端、IPC、动态卡片或所有隐藏能力。下一步由本地 Codex 按 EXTRACTION-REQUEST.md 做机械提取，研究者再继续解析，不将协议接口当作客户端已实现。

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

连接的 GitHub 文件接口支持读取代码文本但不提供近 1 GB 的私有 Release 二进制流；本运行环境网络下载不可用、不是 Windows，也没有 Codex Desktop 运行态。故最关键缺口为 **MSIX 全目录及前端静态代码/源码映射/EXE 证据**。执行 EXTRACTION-REQUEST.md 将解锁 UI 组件和 JSON-RPC 实际桥接的进一步阅读。其后仍需真实 Desktop 的**去敏测试运行日志**才能判定 R 级行为。

本阶段为**已实做代码追踪的研究 checkpoint**，不是研究终版，不得合并成“Codex Desktop 功能已经对齐”。
