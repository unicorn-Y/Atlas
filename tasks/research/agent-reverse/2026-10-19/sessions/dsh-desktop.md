# 独立会话任务：DSH 社区桌面封装双项目

**研究编号：dsh-desktop；波次：Wave 1。本 ChatGPT 新会话专职研究此产品体系。**
**开始前必读：** [统一协议](../PROTOCOL.md)、[派工入口](../START-HERE.md)。
**仓库：** `unicorn-Y/Atlas`。
**派工与原包索引所在分支：** `research/agent-reverse-dispatch-20261019`（已经包含 `research/agent-client-packages-20261019` 的归档清单）。
**本会话独立研究分支：** `research/agent-reverse-20261019-dsh-desktop`（从派工分支创建）。
**研究输出目录：** `docs/research/agent-reverse/2026-10-19/dsh-desktop/`。
**Archive：** https://github.com/unicorn-Y/Atlas/releases/tag/agent-client-packages-20261019

## 本会话应该拿到哪些材料
dsh-desktop-anywhere-labs-03d18d13bb.zip、dsh-desktop-dongdong-agent-1dd3b7ded3.zip；官方 core/Web UI 是关联参考，但另由 dsh-core 调研。

读取 `docs/research/agent-clients/2026-10-19/manifest.json` 找实际 `releaseAssetUrl`、SHA256 与版本，再看对应 `indexes/` 中目录线索。必须以真实包/源码为第一手事实，外部网页只能辅助。

## 特别应该钻进去研究的入口（不是功能数量上限）
1. 将两个社区桌面项目分别读取入口、运行时架构、嵌入 Web UI、子代理工作台、可点入节点、消息/进度/Token 详细面板
2. 对两个封装建立互不混淆的能力清单，追 UI↔事件↔DSH 引擎或其他后端接口
3. 找出封装额外实现、与官方共用的组件、可直接吸收 Atlas 的开源代码及许可
4. 对比多层子代理展开、状态追踪、实时刷新和用户干预；无法实际运行的交互需降级标注

**范围分界：**不是把两个社区项目冒充同一官方客户端；不重复执行整个官方核心引擎逆向。

## 执行要求
1. **主动扩展发现范围**：不仅从前端界面向后端追，也从后台服务、数据模型、RPC、事件协议、插件注册/动态装载反向发现隐藏能力。不要因为上面没有写，就不研究其他模块。
2. 解包/阅读足量真实文件；识别版本、来源、调用链以及无法验证之处。拿不到 Release 二进制时优先利用可访问源码和索引，随后写可直接交本地 Codex 执行的最小机械提取 `EXTRACTION-REQUEST.md`，不要凭空推断。
3. 每个关键发现建立 **`DSH_DESKTOP-NNN`** ID，记录具体入口、行为、实现证据、运行时生命周期、依赖和可移植途径；将静态/动态/官方声明/推断严格区分。
4. 用 Atlas `main` 的真实源码做对应性追踪，记录查到的 HEAD SHA；区分“有 UI、接口但空接线、部分可用、真实等价”，不能照抄旧功能矩阵的状态。
5. 写 `START-HERE.md`, `DISCOVERY-LEDGER.md`, `IMPLEMENTATION-TRACE.md`, `UI-AND-WORKFLOWS.md`, `ATLAS-GAP.md`, `EVIDENCE-INDEX.md`，必要时 `EXTRACTION-REQUEST.md` / `REUSE-CANDIDATES.md`，均落在本目录。
6. **研究完成或实质性阶段结论必须 push 到本会话独立分支**，回传 commit + `START-HERE.md` 链接；不得改其他分支或 Atlas 正式代码。

最重要：**不是只调研上面列的点，而是通过包、源码、运行逻辑发现你原本不知道存在的能力。** 不准用文字堆满名单后声称逆向完成。完整审查规则见 PROTOCOL.md。

## 可直接粘贴进新会话的启动语
“研究 Atlas 竞品：DSH 社区桌面封装双项目。仓库 unicorn-Y/Atlas，读取分支 research/agent-reverse-dispatch-20261019 下的 `tasks/research/agent-reverse/2026-10-19/sessions/dsh-desktop.md` 及统一 PROTOCOL.md。只负责该产品，深入分析真实发行物/源码/机制、发现未知功能，和 Atlas main 核对，研究报告推送独立分支 research/agent-reverse-20261019-dsh-desktop。不要仅规划或复述功能清单，按任务书实做；需要本地机械提取时给出精确 EXTRACTION-REQUEST.md。”
