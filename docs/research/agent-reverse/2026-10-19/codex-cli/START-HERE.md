# Codex CLI / Code Mode Host — 0.163.0 实证研究

**状态：PARTIAL（固定 tag Rust 源码完成第一阶段机制取证；已收集的 Windows Release EXE 未能在本会话读取字节和执行；无动态 R 级验证）。**
**Atlas main：** `aa6196f550098cc46081dc6db2c376cb87ddffa5`（2026-10-19 查询 GitHub main ref）。
**Codex 固定源版本：** `rust-v0.163.0`，annotated tag `129b8ec7ee6f4511557a4856279f529025c25af4` 指向 commit `83086188ae0614bd882818ff1aa23f3194962012`；非后续 main。
**独立研究分支：** `research/agent-reverse-20261019-codex-cli`；父派工分支 `research/agent-reverse-dispatch-20261019`。

## 结论

最值得 Atlas 学习的不是某个按钮，而是 **Agent 运行控制面的分层设计**：Turn 采样/事件循环、可独立管理的 Thread/Agent 运行时、工具调用录制/取消/派发、Code Mode 的独立 V8 Host、持久化与恢复的分离、上下文窗口和后台压缩的边界，以及独立的 UI 事件投影。Codex 0.163.0 的具体源码存在这些路径，但此处不能据此声称已验证 Windows 包运行行为。

**特别需要消除的误解**：Atlas main **已经有** AgentOrchestrator、Hermes 执行、Checkpoint、子任务委派、MCP、会话分支和事件流。并非“一切都没有”；差距是机制级完整性和一致性：例如原生 Code Mode Host/session/cell 双向委派、Agent 子线程驻留与 mailbox、模型上下文世界状态差分、工具调度与执行结果的统一可追溯边界（见 ATLAS-GAP）。

## 真实材料的可达范围

- 已读取：用户仓库派工任务书、统一协议、包采集 `manifest.json`、`indexes/claude-codex-index.txt`、PACKAGE-INDEX、COLLECTION-STATUS；Codex 固定 tag 的**真实 Rust 文件内容**及精确行号；Atlas **main** 的 Python 文件、目录结构、函数实现。
- 已确认收集但本会话未能取回/反汇编：CLI ZIP、host ZIP、固定源 ZIP（资产大小及 SHA256 见 EVIDENCE-INDEX）。这三个 SHA 取自仓库采集清单，不冒称本会话重新算出。
- 固定源码从上游 pinned tag 直接读取，与用户仓库收集的 source ZIP 对应同一 **版本标签**；仍未独立对 ZIP 内容进行字节级比较。
- 未做本地 Windows 启动、网络 API 试验、UI 截图和 EXE imports/strings 验证。所有结论标 **S**（源码静态）、**I**（推断）、**U**（待补采）；无 **R**。
- 固定版本源文件体量大（采集索引计 9,176 项），本轮按可追踪的核心路径做实质抽查，不声称穷尽。
- CLI TUI 与 Desktop UI 严格分界。Desktop 程序由另一个会话研究，不用 CLI 源码推断 Desktop 功能。

## 阅读顺序

1. [DISCOVERY-LEDGER.md](DISCOVERY-LEDGER.md)：稳定 ID、已确认/限制，特别注明新发现。
2. [IMPLEMENTATION-TRACE.md](IMPLEMENTATION-TRACE.md)：从模型循环穿到工具、Host/cell、Agent 控制面与存储恢复的代码调用路径。
3. [ATLAS-GAP.md](ATLAS-GAP.md)：逐项与 Atlas main 的真实源码比较、分类、优先级。
4. [UI-AND-WORKFLOWS.md](UI-AND-WORKFLOWS.md)：CLI 命令/交互/动态事件，未动态验证。
5. [EVIDENCE-INDEX.md](EVIDENCE-INDEX.md)：版本、哈希、源码定位、S/R/D/I/U 边界及未查事项。
6. [EXTRACTION-REQUEST.md](EXTRACTION-REQUEST.md)：仅针对不可直接读取的两个 EXE 的机械补采，不让执行 Agent 代写结论。
7. [REUSE-CANDIDATES.md](REUSE-CANDIDATES.md)：Apache-2.0 下可参考的模块及适配范围。

## 阻塞与完成定义

这份提交交付的是**可核查的第一阶段深度静态研究**，不是完成 Windows 二进制逆向。完成二进制关联闭环至少还需取得：两份 EXE 的 PE 元数据、版本信息、导入库、导出/字符串、可重复的 host `--help` 与 CLI `--help` 输出（不登录）、与 tag 源码一致性记录。如果缺失，始终标 PARTIAL，不把源码功能自动等同 Release 确认可用。

## 研究边界

不修改 Atlas 正式业务代码、不向 main 或其他产品分支写入；不进行无意义大测试。权限/安全逻辑仅记录上游真实机制，不强加给 Atlas 的产品决策。 
