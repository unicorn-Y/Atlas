# ATLAS-HERMES-IMPLEMENT-20261017｜正式施工任务书：并行修复 + 选择性整合

状态：READY_TO_EXECUTE（立刻动代码，不是重复规划）。
主控：Hermes；执行：Hermes 子代理、可用 Codex 会话；独立验收：网页 ChatGPT GPT-6。
项目：unicorn-Y/Atlas；用户正在使用的 Windows 源码根 D:\Atlas。
原则：**速度优先、以用户真正能用为准；修具体 Bug，充分利用现成实现，不造无意义框架，不堆测试，不反复写报告。必须 push 真实代码并交 GPT-6 验收。**

## 0. 固定资料及前情：读完直接施工

来源审查分支：review/atlas-luna-global-audit-20261017，提交 87aed27c96498321572f324a511f88afeda154ff。
先按分工读取 tasks/reviews/atlas-luna-20261017/ 下：
- REVIEW-HANDOFF.md（总索引）；
- 02-ISSUES.md（21 项：P1 10项、P2 11项）；
- 03-FEATURE-405.md（405 项源码功能核验：已做107、部分218、未做67、原有13）；
- 05-INTEGRATION-PLAN.md（14 组尚有独有代码的候选分支）；
- 06-MODEL-RETRY-FIX.md（W1 已修、测试与未覆盖范围）；
- modules/W2-KERNEL.md、W3-FRONTEND.md、W4-TOOLS.md、W5-MEMORY.md、W6-STARTUP.md（各组只读对应模块）。

现有模型补丁分支：fix/atlas-model-retry-policy-20261017，提交 e259978420f944ef57bdb15ed22a8890486c018e。
整合起始代码基线：ui-redesign@0b1ba4114e25643369c95bfac85d37563788444f。
absorb-all@8d7b01d829f1332e9305fe8ee56758a6294139f7 含独有会话/自动化能力，不可直接用 main 代替或简单全分支 merge。

上轮已确认用户正在使用的 D:\Atlas 是 ui-redesign 且有 12 个 tracked dirty 文件、多个 untracked 研究/实验文件，运行进程从源码目录启动。必须保护：**禁止在 D:\Atlas 上做 reset/clean/stash/checkout/pull/覆盖文件、自动运行升级、测试修改真实数据；也不重启当前日用进程。** 所有修复在 D:\Atlas 之外独立 worktree，使用隔离 ATLAS_DATA_DIR、端口和测试目录。不得上传密钥或真实会话内容。

**本任务明确授权正式修复已确认的 Bug、整合有用的分支实现。** 不必重复75个分支梳理或405项全量审查；已有证据若与新代码冲突就局部复核。绝不以新一轮方案报告代替施工。

## 1. 主控立刻执行的五件事

1. 获取最新 refs，核对上面 SHA；如果发现别人在同一问题已有新提交，先吸收避免重复开发。
2. 从干净 ui-redesign 基线建 integration/atlas-fixes-20261017 和独立 worktree，先把已有 W1 模型补丁纳入待集成变更，保留所有其它功能。
3. **尽可能多地开启可用子代理/独立会话**，按 A-F 分工立刻干活。Codex 曾因误选模型而触发5小时额度；暂不可用就由 Hermes 和其他可用执行模型做，不必卡住等待；派会话前确认所选模型避免再浪费额度。
4. 任何两个 worker 不同时编辑同一热文件；所有人有独立 fix/atlas-20261017-<scope> 分支/worktree，各自完成后 push commit；主控按依赖先后整合并随时 push。
5. 每批只运行对该问题有意义的定向测试和一次隔离应用启动冒烟，不固定跑几千条回归，不做无关格式化和依赖升级。

## 2. A 组：模型故障策略补齐（ATL-001 / ATL-005 / ATL-006）

负责人专属修改模型相关文件、失败卡与队列失败分支，避免与 B 组并发改 kernel/loop.py。

- 继承 e259978：本轮用户指定模型仅对临时网络错误、408、429、500/502/503/504/529等有限重试，最多额外2次、总请求最多3次；429 Retry-After 超15秒立即报错，不长时间等待；400/401/402/403/404/413/422、内容过滤、模型不存在等不重试；已经有部分文字/思考/tool-call delta 时不能盲目重发；取消后立刻停止；绝不自动换模型。
- **独立审查发现的缺口必须补上：core/atlas/models/router.py 的 complete_for() 当前辅助模型调用仅请求一次。** 对纯模型推理的辅助请求（记忆抽取、标题、压缩等）按相同规则执行最多2次有限重试；选定的辅助模型 ID 始终不变。辅助功能事先独立配置的模型不等于失败后换模型，允许继续使用，严禁偷偷落到 DeepSeek 默认候选。
- 避免底层SDK/Hermes/HTTPX与新重试循环叠乘；实际上限3次。重试只重发无副作用的模型请求，不重跑已执行工具。
- 最终失败输出 model/provider/HTTP status/类别/脱敏原始报错/request ID/调用次数，并标记 failed；会话待发消息暂停但保留，模型切换与手动重试由用户决定。保留后端接口启动时的适度重试，不误杀非模型场景。
- 定向测试：瞬断后同模型重试成功、503总3次、429 2s和16s、401/404一次报错、已有partial delta不重发、取消、辅助模型不换模、失败队列暂停。假网关/假异常即可，不花真实 API token。
- 输出合入集成分支的实际代码提交，模型相关文件的热文件占用结束后再通知 B/E 继续集成。

## 3. B 组：Agent内核的取消和真实完成（ATL-002 / ATL-003 / ATL-004）

- **ATL-002 P1**：核实 kernel/loop.py 当前运行工具 batch 只等 tool_task 和 queue_get，Stop 设置的 run.cancel_event 无法在长时静默工具等待里及时被消费。复用模型流已有 cancel_waiter，让 Stop 能取消正在跑的工具、停止后续派发；保留已产生的部分输出和已完成工具记录，绝不重放写文件/执行命令等副作用。与用户 dirty 研究工具 deep_research 的取消入口对齐，但不覆盖未提交原文件；先做好可干净吸收的补丁。
- **ATL-003 P2**：把已有 agent/verification_stop.py 与改动文件记录的轻量提醒接到实际 AtlasKernel 的结束路径；改过代码而尚未检查时提醒一次即可，避免“啥都没验就说完成”。不要强制跑全套测试、无限追问或新建检查工作流。
- **ATL-004 集成保护条件**：旧 codex/desktop-repair-20261013 分支可能移除 forwarded_results 去重和 tool_preparing 进度语义。要移植它的其它有用东西，必须保留每个 call_id 单一最终工具事件与现有进度；如果不吸收旧分支，则没有当前 Bug 可修，不要为此改代码。
- 只做1组长工具 Stop 测试、1组无重复工具结果测试、1组修改后提醒测试。因为 A/B 同碰 kernel/loop.py，B 在独立分支施工，主控先吸收 A 后合 B，统一处理冲突。

## 4. C 组：记忆数据正确性（ATL-008 至 ATL-016）

Memory 模块独立 worker，绝不动真实长期记忆库。现有 W1/W2 Library 的数据不能因本轮修复丢失；Atlas 唯一长期记忆主体。完整原生记忆 V4.1 属于另一项目，本轮不借机重造记忆架构。

**必须实际修的缺陷：**
- ATL-008 P1：Dream 全局 checkpoint 可能越过扫描中途到达的迟到记录，也可能把尚未满足分组门槛的 1-2 天经历当作已处理。做最小 source/entry ID 级持久确认或等价无遗漏水位；只有成功写入对应结果才确认。复现迟到消息、重启与3天门槛后完整整理。
- ATL-009 P1：Dream 在调用模型之前读取项目页旧快照，耗时后把人工编辑覆盖。模型完成后在锁内读最新版本并合并，或复用已有 CAS/原子写；人工编辑优先，不写通用事务平台。
- ATL-010 P1：提炼 queue 失败3次不再出队，却无恢复路径；保留失败详情，提供显式的手动恢复/再试入口，不造 broker。
- ATL-011 P2：重启有 pending 时能在模型就绪后有界恢复 _drain，不必等新一轮聊天；重复日记、重复索引不可发生。
- ATL-012 P2：检索 src/from/to/project 过滤必须和总数及分页一致，不能固定取前1000后过滤导致漏项；复用当前 Keyword/Vector/Hybrid Index。
- ATL-013 P2：时间线同timestamp项目使用稳定 (at,id) 复合游标，不重复/跳过。
- ATL-014 P1：记忆引用精确绑定 SessionDB message_uid，不再用 nearest timestamp 猜来源。可选择性移植 mem-integrate 分支的 SourceRef；历史 timestamp 旧ref仍可打开但标识为 approximate，不能冒充 exact。
**条件性/边界：**
- ATL-015：当前 forget 明示不删除 canonical 原始会话；本轮不擅自删除用户原始聊天数据。保持 UI 说明准确，确保已有 tombstone 能防止被忘记派生记忆无意再次入库。未来是否源级删除属于另行用户决策。
- ATL-016：除非验证存在同一个 memory root 的多进程 writer，否则不增加整套跨进程锁；有真实风险时才加最小互斥。
验证只做隔离样本：迟到/跨天、编辑竞争、dead queue复活、启动drain、筛选总数、同秒游标、exact ref；真实数据禁止试验性忘记/历史改写。

## 5. D 组：启动、更新与产物一致性（ATL-017 至 ATL-020）

- **ATL-018 P1**：源码更新失败（fetch/pull/安装/构建）不能自动启动半更新版本。最好复用现有 build-stamp、updater状态、暂存构建再切换；失败仍能用旧版，并展示真正失败原因。只在临时工作树/临时源目录模拟一次构建失败，不碰 D:\Atlas 的更新。
- ATL-019 P2：首次创建虚拟环境需正确使用现有 core/requirements.lock，使首次源码启动依赖可复现；不要迁移整个包管理体系。
- ATL-020 P2：判断dist完整时必须检查Electron主进程、preload、renderer需要的 bundle；只凭stamp相同却缺 main.js 不能直接启动。
- **ATL-017 CDP**：用户在开发阶段允许高权限控制，需要保留 Computer Use / CDP 工作流；不可为了抽象安全收紧而让 Atlas 不能控制电脑。只修真正影响本机使用的配置/绑定问题，必要时将调试参数可配置；不建大套权限平台。
验证隔离源码启动、backend就绪、前端加载、更新失败不毁旧可用版本。安装包/签名和商业发布不是本轮优先级。

## 6. E 组：小修和实际界面体验（ATL-021）

- ATL-021 P2：VoiceOverlay.tsx 在取消/关闭后 getUserMedia 晚返回导致流track没有释放；做最小 effect cleanup，关闭时停止流tracks/AudioContext，不实施新的低延迟语音系统。
- W1错误卡/失败队列必须在隔离 Electron 里至少走通一次 UI 事件投影和手动恢复。不要重画 UI 风格；沿用已有组件。
- UI侧其它补功能只针对 F 组已确认可接入的功能，空壳页面不算交付。

## 7. F 组：从独有分支选择性吸收成熟可用功能

从 05-INTEGRATION-PLAN 的14个“代码候选”出发，**不是把14个分支全部 git merge**。工作目标是把已经做出来、对用户日用有用、但分散在不同分支的东西真正接到统一 Atlas；每项做到入口→API→执行→事件→结果展示，确认再打勾。按模块可另开多个 worker：

优先吸收：
- absorb-all：独立可回查子Agent会话、会话间消息与回报、后台活动、hooks、任务栏状态、send_user_file，当前ui-redesign不存在的部分才移植。
- card-b-tc-10 与 ctx-opt：有真实价值的模型诊断/后台进程状态、上下文恢复/handoff。
- feat/personal-todos：已有小范围待办 UI/API，验证接线后可快速吸收。
- f2-c、card-c-tc-04：MCP OAuth/设置等当前真正缺的能力；按实际可用性优先，避免无用户价值的插件平台大工程。
- wip/c3-frontend-from-laptop：TeamBoard等，如果后台调用链完整才落地。
- memory-w2-ui、memory-w2-fix、mem-integrate：涉及记忆的代码必须由 C 组选最小等价补丁，不能第二个worker同时改同一存储/数据契约。
- wip/kernel-deep-research-20261015 与 D:\Atlas 用户已有 untracked 研究工具：只读对照，处理取消和可靠性后择优吸收，绝不覆盖主目录原稿。
- memory-v1/w1、wip/f4-bc-20261009、fix-p1-audit 及其它旧分支：只挑尚未具备且不造成倒退的能力；等价/已被吸收的 SKIP 并写一句理由。

405项功能中的67个未做和218个部分，不等于本轮需要全部新开发。**优先把已经存在于独有分支、可很快落地的高价值功能接齐；不要为了凑数量重写其它公司的全部工具。**
ATL-007 的 SSH远端LSP 属于条件性L级缺口，若未证明用户正在实际需要，可标 DEFERRED；不许凭这个任务书造第二套远端 language server。

## 8. 多会话协作与热文件分配

主控 Hermes 尽可能开当前额度和并发允许的最大数量；小任务合并给同一 worker，实质上避免多个子代理同时改相同文件：
- A独占 model_call/router 与失败卡；B独占 kernel tool batch取消；同碰 loop 时独立提交由主控合流。
- C独占 memory/library 与 memory API，F组移植 SourceRef 归C处理。
- D独占 launcher/updater/Electron main；E独占 VoiceOverlay与无冲突renderer；F独占各自能力相关文件。
- 共享文件由主控单人集成，严禁worker force-push别人分支；分批尽早push，不积累几十个worktree。
- Codex额度用完由Hermes接手时必须复用现有commit，不回到零重新做“再审查一轮”。

## 9. 最小质量门槛

不为防御而增加泛化抽象，不额外引入大量管理类、adapter、配置层、权限流程；不运行无关大测试、不刷覆盖率、不重构整仓、不扩建CI、不全量升级依赖、不无缘无故加断言。**但任何修复必须有一条能说明目标行为确实改变的定向验证**，构建/类型检查仅在修改前端时执行，真实 UI 需要一轮小范围隔离冒烟。

必须确认：
1. 主/辅助模型同模型有限重试（≤3请求）、失败明确报错、无自动换模、无重复工具副作用；
2. 点击Stop能及时结束静默长工具，保留已完成记录；
3. 记忆不会被Dream checkpoint跳过、手工编辑不被覆盖、队列重启可继续、失败可手动恢复；
4. 查询筛选、同秒分页、来源 UID都准确；
5. 更新坏了不破坏旧可运行版本；
6. 每个移植功能具备真正可调用入口，而非静态存在；
7. 原日用 D:\Atlas 工作树、运行进程与实际记忆未受影响。

## 10. GitHub交付与审查

统一合流分支：integration/atlas-fixes-20261017（基于ui-redesign干净基线）。
worker 分支：fix/atlas-20261017-<scope>。每完成一组 push，可用 cherry-pick 或按文件吸收。
在 tasks/results/atlas-implementation-20261017/ 最终只提交四份精简文件：
- IMPLEMENTATION-STATUS.md：ATL-001～021 每项 FIXED/NOT_APPLICABLE/DEFERRED/BLOCKED+commit；吸收哪些已有功能、哪些旧分支跳过。
- TEST-EVIDENCE.md：实际运行的最少必要验证和结果，已知失败及未测边界，不吹“全绿”。
- INTEGRATION-DIFF.md：从ui-redesign基线实际改了什么、重要冲突及怎样未来安全吸收 D:\Atlas dirty/实验内容。
- REVIEW-HANDOFF.md：最终commit SHA、所有worker提交、关键核查点、真实应用是否跑过、D:\Atlas仍未部署、状态 AWAITING_GPT6_REVIEW。

**必须交代码，不接受只交规划文档。** 不自己写 PASS，不自动合并到 main，不直接部署/覆盖用户正在使用的D:\Atlas。完成一个波次立即push，主控持续整合直至主要已确认缺陷修复完或真实环境阻塞；如果发现审查误报，则拿代码证据明确NOT_APPLICABLE，不做不存在的问题。

## 11. 立即启动命令（给Hermes主控）

读取本文和原审查报告后**马上并行派工施工**。先A/B/C/D/F并行改代码，各自push；主控尽快合并；之后E接UI验证与功能接线。不要再出一份数十页规划，不需要问用户已有答案，不用大量Token跑全量测试。最后给出整合代码分支、SHA、已修ATL编号、吸收功能、测试摘要和交GPT-6审查的链接。

本次重点是：**让Atlas实际得到修复后的可用代码，而不是“下一步建议修复”。**
