# 独立会话任务：DeepSeek Harness (DSH) 官方核心

**研究编号：dsh-core；波次：Wave 1。本 ChatGPT 新会话专职研究此产品体系。**
**开始前必读：** [统一协议](../PROTOCOL.md)、[派工入口](../START-HERE.md)。
**仓库：** `unicorn-Y/Atlas`。
**派工与原包索引所在分支：** `research/agent-reverse-dispatch-20261019`（已经包含 `research/agent-client-packages-20261019` 的归档清单）。
**本会话独立研究分支：** `research/agent-reverse-20261019-dsh-core`（从派工分支创建）。
**研究输出目录：** `docs/research/agent-reverse/2026-10-19/dsh-core/`。
**Archive：** https://github.com/unicorn-Y/Atlas/releases/tag/agent-client-packages-20261019

## 本会话应该拿到哪些材料
deepseek-harness-npm-cli-bd27847c44.tgz（npm 0.2.0-rc.2）、deepseek-harness-source-dcc4cf8df9.zip（对应固定源码；仓库 root 标识 0.2.1-rc.2）、deepseek-harness-web-frontend-ccadad6dcb.tgz（0.0.1-rc.5）。

读取 `docs/research/agent-clients/2026-10-19/manifest.json` 找实际 `releaseAssetUrl`、SHA256 与版本，再看对应 `indexes/` 中目录线索。必须以真实包/源码为第一手事实，外部网页只能辅助。

## 特别应该钻进去研究的入口（不是功能数量上限）
1. 从官方 core 找 agent loop、state machine、子代理树/委派/执行流、可观察性、上下文与模型 token 计量、错误恢复
2. Web UI 事件/后端接口/会话树节点如何连接，查看子代理实际运行和分层状态的技术链路
3. 分析 registry/plugin/skill/扩展桥接、流式事件、持久化与重连行为
4. 分别标注三个源码/发布版本的不一致，不把社区 Desktop 的能力归为官方原生

**范围分界：**社区 DSH 桌面封装完全在 dsh-desktop 会话。

## 执行要求
1. **主动扩展发现范围**：不仅从前端界面向后端追，也从后台服务、数据模型、RPC、事件协议、插件注册/动态装载反向发现隐藏能力。不要因为上面没有写，就不研究其他模块。
2. 解包/阅读足量真实文件；识别版本、来源、调用链以及无法验证之处。拿不到 Release 二进制时优先利用可访问源码和索引，随后写可直接交本地 Codex 执行的最小机械提取 `EXTRACTION-REQUEST.md`，不要凭空推断。
3. 每个关键发现建立 **`DSH_CORE-NNN`** ID，记录具体入口、行为、实现证据、运行时生命周期、依赖和可移植途径；将静态/动态/官方声明/推断严格区分。
4. 用 Atlas `main` 的真实源码做对应性追踪，记录查到的 HEAD SHA；区分“有 UI、接口但空接线、部分可用、真实等价”，不能照抄旧功能矩阵的状态。
5. 写 `START-HERE.md`, `DISCOVERY-LEDGER.md`, `IMPLEMENTATION-TRACE.md`, `UI-AND-WORKFLOWS.md`, `ATLAS-GAP.md`, `EVIDENCE-INDEX.md`，必要时 `EXTRACTION-REQUEST.md` / `REUSE-CANDIDATES.md`，均落在本目录。
6. **研究完成或实质性阶段结论必须 push 到本会话独立分支**，回传 commit + `START-HERE.md` 链接；不得改其他分支或 Atlas 正式代码。

最重要：**不是只调研上面列的点，而是通过包、源码、运行逻辑发现你原本不知道存在的能力。** 不准用文字堆满名单后声称逆向完成。完整审查规则见 PROTOCOL.md。

## 可直接粘贴进新会话的启动语
“研究 Atlas 竞品：DeepSeek Harness (DSH) 官方核心。仓库 unicorn-Y/Atlas，读取分支 research/agent-reverse-dispatch-20261019 下的 `tasks/research/agent-reverse/2026-10-19/sessions/dsh-core.md` 及统一 PROTOCOL.md。只负责该产品，深入分析真实发行物/源码/机制、发现未知功能，和 Atlas main 核对，研究报告推送独立分支 research/agent-reverse-20261019-dsh-core。不要仅规划或复述功能清单，按任务书实做；需要本地机械提取时给出精确 EXTRACTION-REQUEST.md。”
