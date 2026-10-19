# Codex CLI / Code Mode Host — 0.163.0 实证研究

**状态：PARTIAL（固定 tag 源码已深追；3 个原始归档均独立验哈并展开；CLI 版本/帮助和 Host 帮助有受限 R 级实测；没有登录后 Agent turn、IPC 帧或故障恢复的动态证据）。**
**Atlas main：** `aa6196f550098cc46081dc6db2c376cb87ddffa5`（2026-10-19 查询 GitHub main ref）。
**Codex 固定源版本：** `rust-v0.163.0`，annotated tag `129b8ec7ee6f4511557a4856279f529025c25af4` 指向 commit `83086188ae0614bd882818ff1aa23f3194962012`；非后续 main。
**独立研究分支：** `research/agent-reverse-20261019-codex-cli`；父派工分支 `research/agent-reverse-dispatch-20261019`。

## 结论

最值得 Atlas 学习的不是某个按钮，而是 **Agent 运行控制面的分层设计**：Turn 采样/事件循环、可独立管理的 Thread/Agent 运行时、工具调用录制/取消/派发、Code Mode 的独立 V8 Host、持久化与恢复的分离、上下文窗口和后台压缩的边界，以及独立的 UI 事件投影。Codex 0.163.0 的具体源码存在这些路径，但此处不能据此声称已验证 Windows 包运行行为。

**特别需要消除的误解**：Atlas main **已经有** AgentOrchestrator、Hermes 执行、Checkpoint、子任务委派、MCP、会话分支和事件流。并非“一切都没有”；差距是机制级完整性和一致性：例如原生 Code Mode Host/session/cell 双向委派、Agent 子线程驻留与 mailbox、模型上下文世界状态差分、工具调度与执行结果的统一可追溯边界（见 ATLAS-GAP）。

## 真实材料的可达范围

- 已读取：用户仓库派工任务书、统一协议、包采集 `manifest.json`、`indexes/claude-codex-index.txt`、PACKAGE-INDEX、COLLECTION-STATUS；Codex 固定 tag 的**真实 Rust 文件内容**及精确行号；Atlas **main** 的 Python 文件、目录结构、函数实现。
- CLI、Code Mode Host 和 source ZIP 的本机 SHA/size 都与 `manifest.json` 一致；已展开为 47 个 CLI 文件、1 个 Host EXE、9,176 个 source 文件。证据清单在 `extractions/`。
- CLI 真实包 `--version` 输出 `codex-cli 0.163.0`；CLI/Host `--help` 返回码均为 0。已读取 PE 导入表、签名身份和目标字符串偏移；没有反汇编，也不声称逐指令确认 Rust tag 与 Release EXE 完全一致。
- CLI 包内 `codex-resources/voice/manifest.json` 将 app 版本和 x64 target 标为 0.163.0，并给出 build commit `83086188ae0614bd882818ff1aa23f3194962012`，和 pinned source tag 一致；该字段不等于可重复构建证明。
- 上述 `--version/--help` 是仅实际启动的二进制操作（R）；未登录、不执行 Agent prompt、不启动 sandbox/voice helper，不做外部服务请求或数据写入。
- 固定版本源文件 9,176 项，按完整调用链深查重点模块，同时以包内源路径字符串核验发布包组成；本轮仍不声称全仓穷尽。
- CLI TUI 与 Desktop UI 严格分界。Desktop 程序由另一个会话研究，不用 CLI 源码推断 Desktop 功能。

## 阅读顺序

1. [DISCOVERY-LEDGER.md](DISCOVERY-LEDGER.md)：稳定 ID、已确认/限制，特别注明新发现。
2. [IMPLEMENTATION-TRACE.md](IMPLEMENTATION-TRACE.md)：从模型循环穿到工具、Host/cell、Agent 控制面与存储恢复的代码调用路径。
3. [ATLAS-GAP.md](ATLAS-GAP.md)：逐项与 Atlas main 的真实源码比较、分类、优先级。
4. [UI-AND-WORKFLOWS.md](UI-AND-WORKFLOWS.md)：CLI 命令/交互/动态事件，未动态验证。
5. [EVIDENCE-INDEX.md](EVIDENCE-INDEX.md)：版本、哈希、源码定位、S/R/D/I/U 边界及未查事项。
6. [EXTRACTION-REQUEST.md](EXTRACTION-REQUEST.md)：原补采阻塞现已解除，逐项取证和未观察范围均有状态记录。
7. [REUSE-CANDIDATES.md](REUSE-CANDIDATES.md)：Apache-2.0 下可参考的模块及适配范围。

## 阻塞与完成定义

这份提交交付的是**包级校验、模块/资源结构与调用链研究**，不是登录态功能验收或完整 Windows 二进制逆向。仍需实际 Code Mode request/cell/wait/terminate trace、Daemon 恢复、TUI 交互事件、动态 voice 路径与无凭据可复现的工具/子 Agent 演示，才能把这些部分从 S/U 提升为 R；服务端内部仍在 U 边界内。

## 研究边界

不修改 Atlas 正式业务代码、不向 main 或其他产品分支写入；不进行无意义大测试。权限/安全逻辑仅记录上游真实机制，不强加给 Atlas 的产品决策。 

## 第二轮主动反向发现

新增的 CODEX_CLI-028—033 确认 Agent durable graph、Message Board 多后端、PendingSpawn 失败清理、Daemon 后台冷恢复、MCP 取消重刷新及 retained-context checkpoint 线性化。见 [BACKEND-EXTRA-DISCOVERIES.md](BACKEND-EXTRA-DISCOVERIES.md)。该段记录续工前状态；本轮新增/升级项和当前数量见下方“发行包续工增补”。

## 发行包续工增补

本次对照真实 CLI/Host/source ZIP 新增 CODEX_CLI-034—037：发行包组件身份/签名/版本关联、app-server RPC 序列化队列与 drain admission、CLI 同机 daemon/remote 控制入口、以及独立 realtime voice host 的 WebRTC/音频控制链。Host 的独立 transport/OTEL flags 另以真实 `--help` 记录。现有 app-server 026 提升为“源码链闭合、help 确认入口；方法行为未动态 R”，027 仍为可选/默认启用未知。账本含 36 项 S 级机制/包证据；另有 3 个受限 R 操作（version、CLI help、Host help），没有登录后 Agent R。
