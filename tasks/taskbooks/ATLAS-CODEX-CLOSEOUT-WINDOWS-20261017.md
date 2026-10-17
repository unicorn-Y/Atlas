# ATLAS-CODEX-CLOSEOUT-WINDOWS-20261017
## Atlas 问题收尾 + Windows 落地施工任务书（Codex 执行）

状态：READY_TO_EXECUTE。任务是**干实际代码、做少量必要的真实运行检查、准备无损切换**，不是再开一轮全仓审查。

仓库：unicorn-Y/Atlas
主执行：Codex / GPT-6 Luna High；可用子代理尽量并行，互不踩热文件。
独立验收：网页 ChatGPT GPT-6。
起始代码：integration/atlas-fixes-20261017@f99bc248141c378a400052c24b4a1bbc1f17df8a。
基础代码：ui-redesign@0b1ba4114e25643369c95bfac85d37563788444f。
交付代码分支：继续使用 integration/atlas-fixes-20261017；子任务各自工作树分支，验收资料置于 tasks/results/atlas-closeout-20261017/。

### 已经做过，不要重新做

- 最初的 25 项问题总账：tasks/reviews/atlas-luna-20261017/02-ISSUES.md（审查分支 review/atlas-luna-global-audit-20261017）。
- 前三轮独立验收分别在 review/gpt6-integration-20261017、review/gpt6-integration-round2-20261017、review/gpt6-integration-round3-20261017。
- 最新第三轮报告：tasks/reviews/GPT6-INTEGRATION-ROUND3-20261017.md，分支 review/gpt6-integration-round3-20261017。
- 已有模型 W1 R1–R4、内核 Stop、Dream checkpoint/CAS、失败队列、准确来源 UID、搜索翻页、更新回滚等修复。上轮代码审核结论为 BLOCK-4/5 通过，**允许进入隔离 Windows 运行验收**，不是表示真实主机已部署。
- 原总账中大约 20 项已有对应修复代码、1 项是已规避的候选分支合并风险 ATL-004；尚需处置的是 ATL-007、ATL-015、ATL-016、ATL-017。这里的数字是代码交付口径，不是 25 项真实 E2E PASS。
- 405 项功能总表和 14 组独有分支另有任务；不许把其完成率虚构成这批 Bug 全部验收。此次不重新清点 405 项。

## 0. 硬约束

1. **速度优先**：复用现有代码、现成测试、已有 Windows 工程；针对性修复和冒烟，不跑无关全量测试、不做通用框架、不替换全部架构、不反复发计划。
2. 用户的日用 D:\Atlas 曾是 ui-redesign + 12 个 tracked dirty 文件及额外 untracked 研究功能，并有活跃 GUI/后端。该历史信息可能已过时，**先现场读取当前状态，再决定怎么做**。不许直接对日用目录执行 git reset --hard、clean、stash、checkout、pull、强行覆盖源码或编排自动更新；不得破坏当前运行进程、会话、SQLite、密钥、模型配置、研究工具或未提交内容。
3. 施工和故障注入全在 D:\Atlas 之外的独立 worktree / 临时数据根中进行。设置独立 ATLAS_DATA_DIR、缓存、端口、Electron profile 和 debug port；不能让隔离测试连接/修改日用 SQLite，也不能触发日用更新。
4. Atlas 保持唯一长期记忆主体。外部 Agent 为可调用工具，不能给它们建立第二个权威长期记忆库。本轮不实施全量 V4.1 记忆新架构，不做语音/视觉大升级。
5. **保留高权限本机 Computer Use / CDP**。用户不想因为泛化的权限/安全设计丢掉控制能力；不擅自关闭 9335、锁死调试、禁止本机 UI 自动化、改变默认全权限工具。对 ATL-017 用最小可配置能力解决真实风险或明确风险接受；先做真实 CUA 回归，不能牺牲可用性换“纸上合规”。
6. 不对真实 SessionDB 做 forget 清除、Git 历史改写、Power-loss 模拟、试验性数据库迁移；所有破坏性场景仅在临时复制或合成数据里执行。不得把任何密码、令牌、完整聊天原文上传 GitHub。
7. 各自修复 push 真正代码 commit；主控逐波 cherry-pick/merge 经验证小改动到集成分支。不要覆盖其他 worker 的未提交文件。不能测的如实标 NOT_TESTED/CONDITIONAL，不得写 PASS。

## 1. 工作分组与优先顺序

主控立即同时派发独立 worker，能开多少开多少，按热文件去冲突：

- **A｜Windows 隔离实例 + 日用脏工作树保护 + 运行冒烟**：只负责工程实例、运行验证及落地脚本/说明，尽量不编辑 memory 核心。
- **B｜ATL-015 忘记语义和来源一致性**：专属 memory/library/forget、sources、相关 API 及测试。
- **C｜ATL-007 SSH LSP、ATL-016 多 writer 条件核对**：只改相关 SSH/LSP 或内存互斥所需的最小文件，与 B 撞 memory 文件时只提交证据/独立补丁再由主控顺序整合。
- **D｜ATL-017 CDP / Windows 调试连接**：独立检查/必要最小参数修复，和 A 的真实 CUA 冒烟共用可复现条件，不对日用 Electron 做无授权操作。

先把 A 的隔离环境建立起来，B/C/D 并行施工。A 冒烟有失败则修该具体失败，不启动全仓审查。B/C/D 完成后 A 再对新集成 tip 补一轮相关小冒烟。

## 2. A 组：Windows 隔离验收是这轮头号交付

### A0 只读检查日用 Atlas，不改现场

在 Windows 上记录这些可验证事实（但不要贴密钥/用户聊天正文）：

- D:\Atlas 当前 git HEAD、branch、tracked dirty 路径、untracked 路径数量、当前运行进程实际模块 __file__ / Electron 入口、是否连接真实数据根。
- config/atlas.toml 与 ATLAS_DATA_DIR 实际指向哪个目录；确认待测和日用目录完全分开。
- 若用户日用 dirty 文件与集成分支存在同路径修改，生成三方差异清单。注意旧审查里的“12项 dirty”只是旧时点记录。
- 将需要保存的工作区 patch、未追踪研究文件和本地配置以**非破坏性拷贝**放到用户机器隔离备份目录，附摘要/哈希/路径清单；不上传私人原文、数据和密钥；不触碰原工作树。备份失败时不继续切换。

### A1 从集成 tip 启动独立、隔离的完整桌面

使用新的 Windows worktree（不能直接让 D:\Atlas checkout），与日用不同的 ATLAS_DATA_DIR、端口和 Electron userData。切断与日用后端/数据库的共享；预检项目 Python 3.14、Node、lockfile、前端产物、Electron 主进程/preload 路径。

只测需要的最小路径：

1. Electron 能正常启动并进入聊天；API/WS 连通，Settings 和模型列表可打开；普通聊天用 fake 模型网关返回答复（如有可用真实测试配置可以额外跑一条，但不要求花 API token）。
2. 模型 503 触发固定所选模型、最多3次 HTTP 请求，最终失败显示 model、状态、尝试次数；失败后已排队消息暂停且保留；手动恢复不重复产生副作用。
3. 一条慢工具执行中 Stop：WS 发 run.cancel 后出现 run.cancelled，后续待调工具没有启动，不发送重复 tool_result。
4. 隔离 SessionDB 中“上一轮只留下用户『继续』后中断；下一轮另一个 run_id 再发『继续』”：新消息必须拥有新 UID，记忆 SourceRef 指向新 UID。
5. Dream 整理等待期间人为修改/删除项目页：不得覆盖用户改动，旧模型答案不回填；skipped 的 episode 后续可继续处理。
6. 更新器用故障注入验证第二 bundle 备份失败、激活后失败及 no-op；旧 HEAD、main/renderer/preload、lock/venv、build stamp 需可恢复。已有脚本 scripts/atlas-update-transaction.test.mjs 直接复用。
7. 对本轮 B/C/D 修改的功能各跑一条对应隔离测试；无需大范围 pytest/Vitest/性能基准。

记清每个检查：使用的 commit、运行程序路径、配置的数据根、测试命令、退出码、结果；测试生成的私人数据不要进仓库。

### A2 必须查明首次 Windows 冷启动是否真的安装锁文件

原代码 start-atlas.bat 先创建 venv 并 pip install -e core，之后 updater 才可能安装 core/requirements.lock。若首次执行在这之前就失败或出现版本漂移，只修 bootstrap 顺序/异常处理的小问题，不另换包管理器。通过即可标已有修复，不要为了“再保险”重构。

### A3 切换策略：先完成无损可回退方案，不直接强行部署

当且仅当隔离桌面通过，再拿已经保存的 dirty patch/研究文件对照最新集成 tip，在独立工作树语义合并、逐项处理可能的冲突。需要保留用户 D:\Atlas 现有 expert_harness、deep_research 与私有设置功能；content_filter 的既定决定仍为明确错误而不是改写重发。

- 优先交付一个带明确备份路径、前置检查、失败可回滚的**可执行切换脚本或步骤**，让日用代码在准备好后能安全切入；不要以 git reset --hard D:\Atlas 为部署办法。
- 不允许因为更新成功便自动删除旧工作树或旧数据。若无损替换需要用户关闭当前 Atlas 进程或有不可自动解决的语义冲突，留出 **READY_FOR_CUTOVER** 状态和准确的人工动作，不能偷改日用目录。
- 一旦本机已经通过用户明确执行的切换动作，另实测版本路径和最小聊天恢复；否则必须明确报告 **NOT_DEPLOYED**，不能冒充上线成功。

## 3. B 组：ATL-015 记忆忘记的完整语义（P2）

当前 forget_entry 会删派生记忆、匹配日记和记忆库 Git 历史，并返回 not_covered，原始 SessionDB 会话仍可被 kind=raw 搜索；若同一原文再次被抽取，存在重新出现风险。最小方向不是“一删记忆就物理摧毁原聊天”。

需做到：

1. 确立并在 UI/API 文案中区分 **「不再作为记忆使用」** 与 **「删除原始会话」**。默认“忘记这条记忆”不隐式销毁完整会话、其它无关消息或用户备份。
2. 为能得到精确 SourceRef(message_uid) 的忘记动作建立持久、可查询的 source-level tombstone / memory-exclusion（沿用 MemoryStore 现有 tombstone/精确 provenance，避免第二套大数据库）；使 memory recall、派生索引、memory-kind raw 检索和后续提炼**不能悄悄把同一被忘记来源重新当成有效记忆**。注意手动浏览原始会话与用于记忆召回不是同一语义；按用户可见的 UI 描述选择，不能暗中隐藏用户原始聊天记录。
3. 没有 exact SourceRef 时仅使用已有派生文本 tombstone 能力，明确 not_covered，不可按关键词模糊删除别的会话。
4. 如果已有真正的「删除原始会话」用户动作，检查删会话后记忆引用会正确失效，不自动清除其它相关会话；不要为完成 ATL-015 新增任意跨会话整库物理删除接口。
5. 小测试：忘记某条有 exact 来源的记忆后，用户普通聊天、记忆搜索及再次 extraction 不恢复；两个不同消息同文不会误删另一个；原始 SessionDB 仍在且可以人工打开；没有 UID 时按文案说明边界。若 API 能力达不到，返回 PARTIAL 并明确差在哪里，不能强行记 25/25。

交付：最小可用的前后端/API补丁＋测试；不做真实用户记忆删改。

## 4. C 组：ATL-007 / ATL-016

### ATL-007 SSH workspace / LSP

- 先看 core/atlas/engine/tool_registry.py 现有 NATIVE_FILE_TOOLS 分支：本地编辑会 pre/post LSP，ssh:// 不走这一处理；确认 SSH workspace 真的能走已有远端执行/文件映射路径。
- **首选复用现有 LSP bridge 的可用远端能力**。若当前无远端 language server/session transport，绝不为一个 P2 写完整 SSH LSP 平台。至少在远端写工具结果和对应 UI 明确提示「远端编辑未提供 Atlas LSP 诊断」，不误报为已做静态检查；必要时提供一个可选配置或诊断执行命令入口。
- 若通过现有能力可以少量接线完成远程诊断，则接线并给一个隔离 SSH/mock remote 用例；否则把状态诚实标为 PARTIAL/DEFERRED，并附最少的实际缺失依赖及后续触发条件。
- 不要影响本地 Windows 文件工具、写入校验、LSP 和 CUA。

### ATL-016 memory-root 多进程写与 Git 历史改写

- 先证明部署形态：是同一个进程中的单个 MemoryStore，还是多个 worker/process 能够同时写相同 memory root；只读检查锁、writer 生命周期与 root。
- 若没有多写者，原审查明确是 CONDITIONAL，标 NOT_APPLICABLE_CURRENT_DEPLOYMENT，不造跨进程锁，不改 forget 历史算法。
- 若确有同目录多写者：沿用现有实例锁、备份与 rollback，只加一层最小的目录级进程互斥覆盖「编辑/忘记/Git history swap」一致性窗口；在临时 Git memory root 做两条故障注入（swap 前失败、swap 后恢复失败），写出恢复位置。不得在真实 memory root 测试。
- 不可将可能性的理论风险写成已在用户主机复现。

## 5. D 组：ATL-017 CDP，保留完整电脑控制

现状 scripts/atlas-update.mjs 的 launch 默认开放 CDP 9335 + --remote-allow-origins=*。这确实增大本机调试面的风险，但用户明确要求 Atlas 能完全控制电脑，**“关闭 CDP”不是合格修复**。

- 先在隔离桌面证明现有 CUA / CDP 对 Atlas 的实际连接是否需要这个参数以及能否限定监听主机，同时支持桌面操作；绝不简单砍掉调试端口或任意Origin后自称修复。
- 可以最小化提供 debug host、port、enable 的配置和运行态自检；仅在功能不受损且有证据时收紧不必要的外部网络监听。若限制 Origin 导致内部控制器连接失败，保留原行为并告知风险。
- 不得改变权限模式或工具的本地完整控制授权；不要引入用户每步确认的弹窗。
- 若只选择显式接受现有调试风险：标 **RISK_ACCEPTED_NOT_FIXED**，不要伪称漏洞修完；提供观察到的回环/外部暴露证据供用户以后取舍。

## 6. 25项问题完整状态收尾

交付一份**唯一**的机读+人类可看简表（不是重新全仓扫描）。逐项列 ATL-001～025：
- CODE_FIXED / TESTED_ISOLATED / VERIFIED_WINDOWS / NOT_DEPLOYED / PARTIAL / NOT_APPLICABLE / RISK_ACCEPTED 采用适用的多个维度，不要一个 PASS 掩盖整个问题。
- ATL-004 属旧分支集成风险，当前保留去重即可记 INTEGRATION_RISK_AVOIDED，不是实体漏洞。
- ATL-015 若只做到派生忘记而 raw/再提炼仍会回来，必须 PARTIAL。
- ATL-016 单 writer 形态应 NOT_APPLICABLE_CURRENT_DEPLOYMENT，不要编造跨进程验证成功。
- ATL-017 不关闭高权限 CDP 时记 RISK_ACCEPTED_NOT_FIXED 或根据实际配置修复证据标 PARTIAL。
- 405项功能和14组候选独有分支另起下一批，这批不是“405功能全量关闭”。
- 记住前三轮 GPT-6 代码评审只放行到 Windows 隔离实测阶段。

## 7. 交付、推送和验收标准

**严格优先产物**：
1. 集成分支 integration/atlas-fixes-20261017 最新可比较 SHA，代码修复按范围分提交、push；
2. tasks/results/atlas-closeout-20261017/IMPLEMENTATION.md（各组 DONE / PARTIAL / DEFERRED 与 commit）；
3. tasks/results/atlas-closeout-20261017/WINDOWS-SMOKE.md（逐项命令、路径、退出码、断言、实际 Windows 实例是否成功；不能上传敏感 log）；
4. tasks/results/atlas-closeout-20261017/ISSUE-25-STATUS.md（25项最终状态，不要再把已修问题重新列成待施工）；
5. tasks/results/atlas-closeout-20261017/CUTOVER.md（当前 D:\Atlas dirty 情况、无损备份位置、真实冲突、可回退切换方案、是否 NOT_DEPLOYED/READY_FOR_CUTOVER）；
6. 若有效：隔离故障测试/小脚本，优先复用现有脚本。

测试只需相关功能的针对性单测和**一次有实际证据的隔离 Windows 桌面冒烟**，先基本能用再补遗漏；不要每条功能都要求上百用例。任何“成功”必须来自命令/实例实测而不是写报告时想象。前端若失败，给简要复现与对应小修。

**验收门**：
- 阻断：真实记忆/私有数据受损，日用 dirty/研究代码丢失，更新后无法回到旧版，CDP/CUA 被破坏，错误模型换模、Stop 后继续副作用、重复 SourceRef 错认。
- 条件放行：ATL-007 远端 LSP 尚无现成 transport、ATL-016 单写者条件不成立、ATL-017 高权限 CDP 由用户需求保留、ATL-015 源级物理删除需另作决定；这些必须准确说明，不应无限阻止已修主路径投入日用。
- 对尚未运行的真实 provider、Electron 麦克风/语音、真实数据原位迁移等明确列 NOT_TESTED，禁止写“全系统最终 PASS”。

完成后设置 AWAITING_GPT6_WINDOWS_REVIEW，提供 commit SHA、报告路径及一条最小复现命令。网页 GPT-6 仅复核这轮代码/日志和部署准备，不得再以老问题反复无限扩大验收范围。

**结束条件：把上一轮审查通过的修复真正带到可验证的 Windows 整合版本，交出无损切换的方法；四项未收尾问题给出可执行改动或明确的条件性结论。不以新任务书、方案报告、未推送本地代码代替施工。**
