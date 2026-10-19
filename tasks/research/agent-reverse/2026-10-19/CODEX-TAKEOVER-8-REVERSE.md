# Codex 接管｜8 个 Agent 产品真实发行包逆向研究续工（2026-10-19）

**立即执行的施工型研究任务，不是重新规划/只写资料总结。**
执行主体：本地 Windows Codex / Luna High，按可用能力尽可能多开并行子代理或会话。
仓库：`unicorn-Y/Atlas`；原始归档：https://github.com/unicorn-Y/Atlas/releases/tag/agent-client-packages-20261019 。
派工协议：`tasks/research/agent-reverse/2026-10-19/PROTOCOL.md`。
目标：接管已经推送的 8 个 **PARTIAL** 研究分支，补完真实发行物拆解、前端/后端/运行时机制与 Atlas 对照，最后由 GPT-6 复核成果。

## 0. 为什么要接管

此前 8 个网页 ChatGPT 会话已经完成一轮公开源码和 Atlas main 对照，也分别创建了独立的 `EXTRACTION-REQUEST.md`。**共同缺口**：不能读取私有 GitHub Release 的大体积二进制，因此不少研究还停在源码静态追踪；Claude Desktop 和 Codex Desktop 尤其缺主程序实物证据。现在由能访问 Windows 文件系统/终端/GitHub Release 的本地 Codex **从实物拆包一直研究到报告成品**，不再把 Codex 限定为机械搬运工，也不要求退回网页会话才能完成分析。

不要重写已有阶段报告、不要从零搜功能、不要只跑文件哈希或 grep 后说“完成”。必须接着分支最新成果做**代码级真实逆向 + 主动发现未知机制**。任何一个产品现有报告中的结论都不能未经取证就认定发布包真有。

## 1. 需要继续完成的 8 个产品与唯一写入分支

| lane | 研究范围 | 研究分支 | 当前阻塞的真实资产 |
| --- | --- | --- | --- |
| claude-desktop | Claude Desktop / Cowork | `research/agent-reverse-20261019-claude-desktop` | `claude-desktop-x64-2bf309665f.msix`、内嵌 app.asar、cowork-svc.exe |
| claude-code | Claude Code CLI / Agent engine | `research/agent-reverse-20261019-claude-code` | `claude-code-cli-core-ac1a6a3364.tgz`、`claude-code-cli-win32-x64-cd077f50f2.tgz` |
| codex-desktop | Codex / ChatGPT Windows Desktop | `research/agent-reverse-20261019-codex-desktop` | `ChatGPT-x64.msix`（官方 OpenAI.Codex 26.1013.4894.0） |
| codex-cli | Codex CLI / Code Mode Host | `research/agent-reverse-20261019-codex-cli` | `openai-codex-cli-x64-dabdb4d16a.zip`、`openai-codex-code-mode-host-x64-bc82fa6d8f.zip`、源码 ZIP |
| opencode | OpenCode Desktop + CLI | `research/agent-reverse-20261019-opencode` | `opencode-desktop-v2.0.32-c6beba4a54.exe`、v2 CLI TGZ、v2/v1 源码 ZIP |
| zcode | ZCode Desktop / Embedded Runtime | `research/agent-reverse-20261019-zcode` | `zcode-desktop-v3.15.3-bc8100ba43.exe`、`zcode-agent-runtime-embedded-v3.15.3-31965ce1d5.cjs`；3.15.1 开源快照作为对照 |
| dsh-core | DeepSeek Harness 官方 CLI/Core/Web | `research/agent-reverse-20261019-dsh-core` | `deepseek-harness-npm-cli-bd27847c44.tgz`、`deepseek-harness-source-dcc4cf8df9.zip`、`deepseek-harness-web-frontend-ccadad6dcb.tgz` |
| dsh-desktop | DSH 社区 Desktop 双项目 | `research/agent-reverse-20261019-dsh-desktop` | `dsh-desktop-anywhere-labs-03d18d13bb.zip`、`dsh-desktop-dongdong-agent-1dd3b7ded3.zip` |

每个 lane 在：
`docs/research/agent-reverse/2026-10-19/<lane>/`
已有 `START-HERE.md`、`DISCOVERY-LEDGER.md`、`IMPLEMENTATION-TRACE.md`、`UI-AND-WORKFLOWS.md`、`ATLAS-GAP.md`、`EVIDENCE-INDEX.md`、`EXTRACTION-REQUEST.md`（部分另有 BACKEND-EXTRA-DISCOVERIES 等）。
**这些是当前工作基线，先读取，再沿其中尚未解决的源码链路补证。**

### 代码优先级
1. 优先 `claude-desktop`、`codex-desktop`：上一轮几乎没有主程序包内源码证据；必须先把真实 UI/IPC/renderer/服务资源分析出来。
2. 然后 `zcode`（重点实际 3.15.3 CJS）、`claude-code`（原生执行器）、`opencode`（v2 真实 desktop/CLI）。
3. `dsh-core`、`dsh-desktop`、`codex-cli` 已有较丰富的固定源码 S 级结果，仍需发行物对照、未覆盖模块挖掘和适量真实运行证据。

**并行优先，以上只是机器资源抢占顺序，不强迫串行。**

## 2. 每个 lane 的实际执行流程

### A. 获取发行物、校验和解包
- `git fetch origin` 获取每个分支最新 HEAD，不创建覆盖既有分支的新基线，不清理/覆盖其他 Agent 的本地修改。
- 使用 **8 个独立 git worktree（或等价隔离 checkout）**：一 lane 一 worker 一分支；避免在同一个 D:\Atlas 工作树反复切分支。下载/解压 scratch 目录在仓库外，允许复用旧 `D:\agent-client-staging` 缓存，但必须对照 `docs/research/agent-clients/2026-10-19/manifest.json` 的精确 SHA256/size。
- 通过 `gh release download agent-client-packages-20261019 -R unicorn-Y/Atlas -p <asset>` 拉取实际字节；找不到就检索本机已有归档。**不使用其他版本“凑数”。**
- EXE/MSIX/ASAR/ZIP/TGZ/CJS/VSIX 根据真实类型拆解；输出文件树、SHA、package/entrypoints、PE imports/metadata、主/预加载/渲染层、脚本/资源/服务启动。保留版本差异；闭源缩混代码可用 parser、AST、sourcemap、局部格式化及 byte offset 辅助。**不能只有 keyword grep 或仅 strings 的词频统计。**
- 各自原 `EXTRACTION-REQUEST.md` 是最小取证要求，**不是研究工作的上限**；可根据实际发现继续展开模块/事件/路径。
- 大文件只留本机或既有 Release，Git 只提交可核查的必要短代码引用、带路径/偏移/哈希的证据索引和自己的原创分析。不要上传整包闭源文件、原机账号/Key/Cookie/个人会话/敏感 Profile。

### B. 完整深入研究，不只机械提取
按真实调用关系**双向遍历**，而非只研究用户举过的功能：
- 枚举全部可发现界面/交互/动态组件/命令、状态视图、会话和任务操作；从每个 action 沿 renderer → preload/IPC/RPC → host/agent runtime → tool/model/session/DB/events/恢复制约追调用链。
- 从后端反查：Agent turn/step/attempt、工具调度、子代理与 Agent tree、任务委派和并行/独立上下文、队列与 checkpoint/持久化、后台 job、重启冷恢复、交互式消息/组件、MCP UI/Skills/扩展宿主、事件流、上下文/Token/cache/usage、模型调用/路由、执行失败/重试/取消、进程与生命周期，以及任何**主动新发现的机制**。此枚举绝不是研究范围上限。
- 实现链必须指明实际文件+函数/符号+行号或字节偏移；如属 D(官方文档) / I(推断) / U(未知)，绝不可提升为 S(源码实证)或 R(运行实测)。
- 对源码和发行版本不同的情况，一定对照**真实二进制**判定 matched / changed / unknown；尤其 ZCode 3.15.3 vs 源码 3.15.1、DSH CLI/源码/Web 不同发布版本、OpenCode v2/v1。
- 当前环境能在无敏感项目的测试配置下运行时，采集少量真正有价值的 R 级操作（例如新建任务、一个子代理、工具调用与进度、后台进程、关开/断线/恢复），记录步骤/事件与结果；条件不可用标 U，不作无意义的大批量验收。
- 对 Atlas `main` **重新读取当前实际 SHA 的源码**，不止复述旧 ATLAS-GAP。区分“无/只有 UI/只有 API/未完整接线/可用但不等价/等价/未知”；沿主代码调用实际验证、必要时少量隔离测试。寻找能原生吸收的成熟机制、具体可复用文件与许可证、必要依赖，不要求 Atlas 设计也做成插件。

### C. 报告更新（每 lane）
直接在**当前研究分支**增补原报告与新证据，必要时创建 `evidence/`、`extracted/` 等，保留此前 ID 对照，新增发现沿用原前缀编号，避免同一个 ID 重新解释另一个功能。必须更新：
- `START-HERE.md`：实际研究状态、范围、包版本、深度、最重要发现和仍不可见之处；
- `DISCOVERY-LEDGER.md`：逐条证据 ID，新发现不受上限；
- `IMPLEMENTATION-TRACE.md`：可复核前端到后端调用链、后台机制、状态生命周期；
- `UI-AND-WORKFLOWS.md`：真实菜单/组件/动态交互/子会话/运行状态；
- `ATLAS-GAP.md`：真实 Atlas main@SHA 代码差距，区分外壳/接线/原生实现质量；
- `EVIDENCE-INDEX.md`：原始文件/hash/真实源码路径+偏移/实操日志；
- `REUSE-CANDIDATES.md` 或新增字段：成熟源码位置、依赖、移植方案、license；
- 提取文本及 `EXTRACTION-REQUEST.md` 完成情况：已解决的标 resolved，仍需额外材料的给具体后续步骤。

`S` 代表对应版本的真实源码/打包代码证据，`R` 是真实运行证据。**哪怕 S 很多也不代表整个发布程序功能已经穷尽**；最后明示扫描覆盖范围、未查模块和关键盲点。

## 3. 并行与提交纪律

- 可用最大并发 worker/子代理分配到各 lane；某个任务失败不能中断所有 lane。控制的是分支写入冲突，不是人为限制 Agent 数。
- 每个 worker 只能 push 自己的 `research/agent-reverse-20261019-<lane>`；如已有该分支改动，先 pull/rebase 其最新已推提交，**不能 force push、不能重写别的研究结果**。各 lane 工作目录相互隔离。
- 能完成一段可审计证据就 commit/push checkpoint，保证被中断也不丢成果。**别把 checkpoint 写成 ALL COMPLETE**。
- **禁止修改 Atlas 正式业务源文件、禁止 merge 到 main**；研究产物只落在 `docs/research/agent-reverse/2026-10-19/<lane>/`。这个任务仅做逆向调查和 Atlas 缺口分析，不做功能施工。
- 速度和实际质量优先，不做无意义的复杂防御代码、套娃任务书、海量测试、表面 checklist、漂亮但无证据的空报告。
- 本机 Codex 现在是全流程研究执行者，**不是仅机械提取者**；不用等网页 ChatGPT 挨个读完提取报告才继续下一步。可自主下载、解包、分析、整理并 push。

## 4. 汇总交付与审查门

每完成一 lane，输出：
`<lane> | branch | HEAD commit | START-HERE URL | analyzed real package(s) | S/R evidence count | newly discovered mechanisms | still U/blockers`

最后在**独立总协调分支** `research/agent-reverse-20261019-codex-closeout`（基于派工分支建立，不含 8 lane 的改动）提交：
`docs/research/agent-reverse/2026-10-19/_codex-closeout/START-HERE.md`
`docs/research/agent-reverse/2026-10-19/_codex-closeout/BRANCH-STATUS.md`
`docs/research/agent-reverse/2026-10-19/_codex-closeout/UNRESOLVED.md`
`docs/research/agent-reverse/2026-10-19/_codex-closeout/REVIEW-ENTRY.md`

总协调目录**只列真实已推的成果、每个 HEAD SHA、研究覆盖差异与遗留问题**，不将 8 条报告合并成一份模糊的大功能清单；别代替后续 GPT-6 做最终质量审查，更不要自行声称 Atlas 已复刻所有能力。

验收标准：
1. 每个 lane 是否确实读取其指定的**真实发行物**；提供可重验的字节/SHA + 包内模块/符号证据。
2. 前端入口 + 后端执行 + 运行状态生命周期有证据链，而不仅是产品描述。
3. 有主动发现的未知能力及对 Atlas main 的源码对照，不遗漏上游成熟底层实现。
4. 阻塞明确，可继续调查；无证据的不能填 COMPLETE。
5. 所有分支已 push，所有报告入口真实存在。

**完成后给用户**：8 lane 汇总、commit、总协调报告链接，以及还须继续研究的部分。再由 GPT-6 集中审查、退回遗漏和制定 Atlas 施工任务。

## 启动提示
执行本文件时按 A→B→C 真实作业；可组织并行分工。不要先反问用户是否批准普通下载/分析/推送。当前指令明确授权执行研究与研究分支提交；不涉及真实用户敏感数据或生产代码修改。
