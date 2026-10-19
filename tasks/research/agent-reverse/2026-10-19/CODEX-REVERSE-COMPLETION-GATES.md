# Atlas 八项逆向续工：强制完工门槛与二次派工（2026-10-19）

## 指令优先级 / 当前状态

**本文件是针对已完成八份阶段报告后继续执行的强制补充任务，不是新一轮规划。** 与之前 `PROTOCOL.md` / `CODEX-TAKEOVER-8-REVERSE.md` 中允许因为本地可解决的阻塞而提交最终交接的部分发生冲突时，以**本文件的完成验收标准为准**。已有研究分支、哈希、固定源码版本、证据编号与研究目录不变。

执行者：本地 Codex（Luna High），按可用资源最大并行；可拆分多 worker / worktree。现有 closeout 仅是**阶段快照，禁止把它当八项研究已全部完成**。

**强制要求：不要再次只写解释、后续计划、EXTRACTION-REQUEST 或漂亮的总结。下一次提交必须是可复验的新分析证据、完整调用链、必要的运行观测或确凿的不可访问证据。**

## 一、真实根因与执行原则

前一轮已经做到：8/8 lane 有报告、固定发行物 SHA 已核、代码静态取证获得部分新发现。但每项仍 PARTIAL；特别是大型 ASAR 分析器超时、UI→IPC→Host→Agent 没闭合、真实任务运行缺失。**分析器超时不是“研究对象无法研究”**。包已经存在本机，应改用按文件/模块/入口切分的方式继续，不再反复对数百 MB 全包一次性做深度图而浪费时间。

闭源云端实现不可见，或某版桌面必须经过缺失的独立认证才能启动，可以如实记为边界；但**未做、没有换工具、一次 timeout、grep 没匹配、只看目录名、已有文档说了**，都不是已尽力的客观阻塞。

每个 lane 保留自己的分支 `research/agent-reverse-20261019-<slug>`，仅在 `docs/research/agent-reverse/2026-10-19/<slug>/` 增加/更新研究文件。绝不修改 Atlas 正式业务代码，也不合并 main；不要重复上传大体积闭源整包、用户配置、密钥、聊天数据。

## 二、共通硬验收 G0–G7：八个 lane 各自都必须过

### G0 实物身份
固定发行包版本、SHA、来源与实际运行二进制关联；版本不同的源码对照标注 matched/changed/unknown。保留现有记录，不做第二遍无意义下载。完整记录包的入口、真正需要研究的代码/资源构成。

### G1 全部**可执行**前后端代码的可审计覆盖，而不是抽样
- 枚举并分组所有 JS/TS/CJS/HTML 路由/CLI command / host preload / service binary / plugin/extension registrations / renderer chunks；图片、字体、locale 和重复资源只做清单/分类，不要求逐张“语义解读”。
- 对**代码文件、菜单/命令/路由/IPC/event/register/feature flags**做分批符号解析或注册表枚举，写 `COVERAGE.md`：每组代码路径、模块数、总字节、已扫描/未扫描及其原因、入口引用、静态解析成功/失败、发现的新能力 ID。不得把“抽了 35 模块 / 41 chunks”称为覆盖 20,000 assets。
- 超时或堆内存溢出：先按目录、chunk、入口、模块大小分拆，再按原生解析器/AST/局部格式化、源码映射、增量/纯静态字符串+上下文回退，保存报错与实际替代办法。持续处理其他模块。只有切分、替代工具仍无法解析的目标才能列 U，并给精确文件/失败与理由。

### G2 UI ↔ IPC/RPC ↔ Host/Agent ↔ 事件/持久化双向完整链
- 建立 `SURFACE-MAP.tsv`：可达操作、路由或组件、触发回调、ipc channel / RPC method、处理者、状态写入/事件消费、用户可见反馈及来源偏移。无 UI 的 CLI 命令用 command-to-runtime 替代。
- 不能只出现 backend API 字符串；必须至少闭合该产品主要执行路径（新建会话、发消息、工具、子代理/子会话、队列/steer、后台运行、恢复、审批、插件/UI 动态资源）各一条真代码链。**不支持/不存在也要给出检查范围和可证据化结论**。
- 从后端 command/event/schema 反查前端调用、注册、feature gate；主动发现任务书没列的能力。缺一段用 UNKNOWN 标明，而不是以无根据的箭头补全。

### G3 Agent 核心真实语义
- 把 Agent loop（turn/step/attempt/tool）、模型路由/context/cache/token、并发/取消、child lifecycle/message inbox/任务板、持久化/恢复、异常重试、MCP/Skills/plugins、进程宿主和运行实例写成有执行顺序、数据结构、状态转移、失败路径的机制图。
- 关键功能在真实分发版本的实现要有文件+函数+偏移/行号，而不只写旧版开源源码；旧版只能另列参考。
- 明确区分已持久化会话/后台任务、能恢复地址/界面、能继续执行尚未完成模型/工具；不可把事件重新订阅包装成执行冷恢复。

### G4 少量实际执行验证（非形式主义）
- **优先使用本机可用且合法授权的现有测试环境和已登录软件**，只用新建的合成工作区与合成数据，观察一次真实 Agent→模型→工具/子代理；记录进程、IPC/协议或非敏感事件、实际行为和可重放操作。不会操作已有用户会话/个人文件，不上传 Cookie/Token/账号私密数据。
- 每个能运行的桌面应用至少验证：入口/真实 UI 可见性与点击、消息运行+工具、子代理/任务状态或标“不支持”的证据、一次暂停/关闭/恢复/中断场景。CLI 至少一条合成 Agent turn+tool，Host transport 如无需账户可单独跑最小协议请求。
- 若确实缺授权账号、地区不开放、依赖云服务、安装要求不可满足、或非 Windows 能力本机不存在，记录**实际已尝试的步骤、明确错误、被阻塞的具体测试和不用绕过限制的解锁条件**。可以维持 R=0，但**不能仅因为“动态测试可选”就什么也不试**。
- 不搞大规模无意义回归。一次小型合成工作流比几百条 help 输出更有价值。

### G5 Atlas main 真代码对照
读取当前 `origin/main` 并固定 SHA；逐机制给出 Atlas 前端入口→adapter/API→引擎/状态的实际代码锚点，分类：等价 / 机制不同 / 功能不完整 / 只有 UI / 只有 API / 真缺失 / 未充分确认。主动发现缺口，不以原清单为天花板。输出 `ATLAS-IMPLEMENTATION-BACKLOG.md`，只做研究和实现设计，不改业务代码：优先级、可借用具体源码、依赖、license、预计对 Atlas 主引擎需要改动的路径。多个产品共有机制只在各自 lane 标识，不在本阶段贸然合并主引擎。

### G6 证据抽查和完整结果
提交 `COVERAGE.md`、`SURFACE-MAP.tsv`（或同等机器可读数据）、`END-TO-END-TRACES.md`、`ATLAS-IMPLEMENTATION-BACKLOG.md`、`FINISH-GATES.md` 并同步更新现有 START-HERE/LEDGER/IMPLEMENTATION-TRACE/UI-AND-WORKFLOWS/ATLAS-GAP/EVIDENCE-INDEX。每项 G0–G5：PASS / PARTIAL / BLOCKED，每个结论有真实文件/偏移或可重现实测；不知道的继续 U。证据总账保留 S（包/源码静态）、R（真正实测）、D（官方声明）、I（推断）、U（未知），禁止将 strings 命中或 help 命令算成“Agent 执行 R”。

### G7 最终验收与停机条件
- 可以持续 push `CHECKPOINT`，但每个 checkpoint 必须写目前仍开的门槛；**不得以 8/8 文件都有、8/8 commit 都有或报告字数很多为理由关闭研究**。
- 只有当 G0–G6 目标范围内可本地研究的项全部 PASS，且剩余 U 有真正外部不可取得的明确证据，才允许标记 **RESEARCH COMPLETE WITH EXTERNAL LIMITS**；云端闭源实现不要求非法访问，且不能宣称“已穷尽所有能力”。
- 如果还有本机可继续解析的代码、没枚举的 UI action、没闭合的核心机制或未经尝试的可测运行路径，必须保持 **WORK IN PROGRESS** 并继续执行；不能改名为 DONE/阶段交接完毕。
- 不能取得环境时必须明确交付 `BLOCKED WITH REPRODUCIBLE CAUSE`，不把阻塞伪装为 PASS。总协调分支汇总仅写实际完成门槛和待做项，不做最终“完工”宣传。

## 三、当前八个分支需要立刻补的具体硬缺口

1. **codex-desktop**（最高优先级）：真正枚举 20,362 webview assets 中的**代码性 JS/chunks 和 UI/action 注册**；解析 Electron ASAR 内 main/preload/renderer 至 UI menu/action → `electronBridge` → JSON-RPC `thread/turn`、queue、approval、MCP app/动态 widget、computer-use host 的完整链。当前仅抽查 35 build 模块和 41 chunk，禁止以此收工。补独立 `evidence/` 目录/索引与至少一个真实 UI action 闭合。
2. **zcode**：3.15.3 同版 `app.asar` 主/host/renderer/scheduler/plugin UI 逐 chunk；解决或界定 node-pty integrity mismatch 对解析的影响，针对 MCP App sandbox→renderer→host RPC→App Tool/model result 逐段闭合；3.15.1→3.15.3 source/bundle anchors 标明真正匹配。
3. **opencode**：ASAR 依代码模块分段完成，别再触发整包 REA 超时；枚举 GUI Extensions、renderer→sidecar/server、BrowserPlugin/CDP attach、session/queue/tool/subagent/events 的双向路径；对 OpenConsole integrity mismatch 做受限独立复核而不停止其他模块；使用合成 scratch API session 验证可测试的操作。
4. **claude-desktop**：覆盖生成的 dynamic IPC channels 及全部关键 renderer route/action，Cowork Artifact 调用、schedule、ClaudeVM named-pipe install/start/stop + 服务进程静态 Go 调用入口，服务消息/状态映射；企业版/consumer 差异继续明示。不能因为已找到 VM pipe 就称所有 Cowork 后端已掌握。
5. **claude-code**：从 2.1.302 的真实内嵌源码/原生程序推进 worker spawn→inbox writer/read/ack→parent notification→job/subagent lifecycle 和 daemon restart；按实际可达环境做合成模型/工具 turn。CLI version/help 已完成，不再在 help 消耗主要精力。
6. **codex-cli**：对固定源码中的 Code Mode Host transport/cell/message broker、agent graph/mailbox、daemon 恢复和工具结果流，补实际发布包组合与可运行协议；进一步研究尚未穷举的独立注册入口。CLI/Host help 已完成。
7. **dsh-core**：已实物验证 CLI/Web/source；现在按发布版本逐个核对 profile plugin mounts、旧 CLI 与新源码差异、Web JS route/组件/控制台和真实 `session/updateQueue` /subagent 路由；在合成运行环境跑小型 Agent/子代理状态变化，不能只验 `--help`。
8. **dsh-desktop**：两个社区项目分别定位 Electron/Tauri 真实 UI 调用与官方 DSH runtime 的边界；A 的实际按钮到 `session/updateQueue` 交互未闭合，优先做。官方的子 Session/sidebar 特性不得算作第三方客户端自创。

## 四、执行与报告纪律

1. 现在立即按现有 8 分支继续，而**不是创建另八个任务书/只输出新规划**；Codex 同时负责解包、分析和交付，不再要求退回网页聊天研究。
2. 尽可能多用并行子代理/worker，Windows 下隔离 worktree，一 worker 一 lane；避开相互覆盖和 force push。中途失败优先重试/换工具/缩小分析批次，不因某 lane 卡住中止其他 lane。资源不足做轮换。
3. 每个 lane 的主研究者自己核对真假；对 S 结论提供确切包源和可复核引用，另由 GPT-6 统一复审。不要做冗余形式化审计，但最低必要证据必须齐。
4. 针对有许可证或闭源发布包的内容，研究可依法取得的包；不绕过登录、授权、加密，Git 只上传原创机制总结/小范围必要引用和哈希索引。
5. 只在自己 lane 分支提交 research docs 与证据；完成一个真实机制闭环就 commit+push，绝不改 Atlas 业务代码。若所有可执行研究完毕，更新 `research/agent-reverse-20261019-codex-closeout` 的各 lane 门槛、证据与未解决项，保留真实状态。

## 五、最终回传模板（必须有真实证据）

`lane | HEAD SHA | G0-G7 status | code modules covered/total | UI actions linked/total | lifecycle traces completed | Agent R evidence or exact blocker | genuinely inaccessible U | ATLAS backlog path`

**不再接受“包已解开 + 报告已写 + 状态 PARTIAL”作为本轮最终答复。必须继续把尚能调查的部分做掉，或者交出可独立复现的真正阻塞原因。**
