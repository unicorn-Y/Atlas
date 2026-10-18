# ZCode Desktop / Agent Runtime 逆向研究 — START HERE

> **阶段结论：PARTIAL / BLOCKED（3.15.3 二进制直接验收未完成）。** ZCode 3.15.1 公开完整源码显示一套比“多 Agent 聊天”复杂得多的执行系统：有独立 turn loop、带命令队列的父子代理通信、受 journal 约束的可重放工作流、弹性并发、Electron 多进程宿主和 MCP Apps 沙箱。已追查这些源码及 Atlas main 的具体实现；不能以较旧源码冒充 3.15.3 实物。

## 研究基线、产物与边界

- 目标：ZCode Desktop Windows x64 **3.15.3**，安装包 SHA256 **bc8100ba4377256fbe1531d549b4775f18e3ba21768b6294ca50751cd461faca**；内嵌 resources/glm/zcode.cjs 15,127,039 bytes，SHA256 **31965ce1d5d4a808ef156784f67996de42ccab335591d2386a61ea8f6f506a54**。这是收集分支索引的机械提取记录，不是本会话亲自解析 CJS 的结果。
- 本次**实际读取并分析**：zai-org/ZCode 固定源码提交 **aac4755666d09fdcd70272fcf063c077a639015f**（root package.json 为 3.15.1）；以及 Atlas main **aa6196f550098cc46081dc6db2c376cb87ddffa5** 的代码与树。
- 研究分支从 research/agent-reverse-dispatch-20261019 建立；**没有修改 Atlas 业务源码**。
- 覆盖：3.15.1 核心 turn loop、subagent、dynamic workflow、SQLite journal、上下文、MCP、插件、Electron 进程、UI、后台调度，以及 Atlas main 对照（全部静态证据 S）。没有在本环境启动 Windows Electron/ZCode 3.15.3，不存在运行证据 R。
- 尚欠：3.15.3 CJS 内的函数符号、入口/版本差分；同版 app.asar 组件/IPC 的实物对照；Windows 运行日志/任务恢复实操。GitHub 连接可读源码文本，但不支持 Release 大型二进制直接获取。精确机械补采见 EXTRACTION-REQUEST.md。

## 报告导航

| 文件 | 内容 |
|---|---|
| [DISCOVERY-LEDGER.md](DISCOVERY-LEDGER.md) | 逐项发现、25 条 3.15.1 源码确认事实、版本证据等级与盲区 |
| [IMPLEMENTATION-TRACE.md](IMPLEMENTATION-TRACE.md) | 从交互/父子任务到模型工具调用、journal、IPC、异常恢复的调用链 |
| [UI-AND-WORKFLOWS.md](UI-AND-WORKFLOWS.md) | 能找到的页面、可操作动作、流式状态、后台工作流及待实测路径 |
| [ATLAS-GAP.md](ATLAS-GAP.md) | Atlas main@aa6196f 的正反对照；已接线、部分功能、缺口及吸收锚点 |
| [EVIDENCE-INDEX.md](EVIDENCE-INDEX.md) | 包 SHA、源码固定路径与行号、调查范围和未触达部分 |
| [EXTRACTION-REQUEST.md](EXTRACTION-REQUEST.md) | 给本地 Codex 的限定式、可机械执行的 3.15.3 取证/上传任务 |
| [REUSE-CANDIDATES.md](REUSE-CANDIDATES.md) | Apache-2.0 源码复用边界与 Python/Electron 适配建议 |

## 重要结论与可行动作

1. **先按真实数据链抄，别只抄 UI。** workflow 子进程经 NDJSON 把 ask 请求送给父进程的 WorkflowEngine，driver 对接持久 journal；失败、停止和恢复是数据协议，不是用户界面状态。参考 IMPLEMENTATION-TRACE 的链路 C。
2. **把后台结果回流做成明确命令。** ZCode 子代理完成事件经运行时命令队列重新进入父 agent 的后续模型请求，且用 branchGeneration 避免旧分支结果污染新上下文；不是单纯滚动显示通知。
3. **可复用机制不是“模型强弱”。** 自适应并发在 429 降为 0.75 倍、连续 4 次成功且存在等待请求时加 1，5 分钟拒绝记忆影响 seed；有准确源码证明。
4. **Atlas 不能按“有没有这个按钮”打缺口。** Atlas 已有 Hermes 真正运行、工具、MCP、持久 SessionDB、后台 Hub、scheduler、分支、子代理 worktree、插件等；缺口必须具体到结构化工作流 journal、沙箱 UI、ZCode 原生会话适配，而不是粗暴说 Atlas 没 Agent。
5. **先完成 3.15.3 的机械提取，再谈同版落地。** 已固定三个资产哈希；本次未读取二进制，不允许由 3.15.1 的源码推断 3.15.3 的确切执行行为或二者实现一致。

## 交付状态

**静态源码阶段：完成初轮取证与 Atlas main 对照，25 个 ZCODE-001..025 源码证据条目。3.15.3 Release 实物深度逆向：BLOCKED；补采请求已写入。** “S”只说明可定位源码行为，不表示当前安装包或动态运行已验证。这里的状态是阶段性研究提交，不是最终穷尽产品能力。

源代码固定快照：[ZCode v3.15.1](https://github.com/zai-org/ZCode/tree/aac4755666d09fdcd70272fcf063c077a639015f) · [Atlas main 基准](https://github.com/unicorn-Y/Atlas/tree/aa6196f550098cc46081dc6db2c376cb87ddffa5) · [原包归档](https://github.com/unicorn-Y/Atlas/releases/tag/agent-client-packages-20261019)
