# ZCode 执行任务书：Claude Desktop / Cowork 全量静态解剖（安装包 + 内部实现）

**任务日期：2026-10-20**  
**唯一目标：Claude Desktop（以 Windows 版为主，包含其中真实交付的 Chat、Cowork、Agent、服务、工具、前端和宿主层）；本轮不拆其他产品。**  
**总负责人兼执行者：ZCode，优先使用其接入的 DeepSeek V4.1 Flash 执行。**  
**仓库：`unicorn-Y/Atlas`。**  
**唯一工作分支：`research/zcode-claude-desktop-anatomy-20261020`。**  
**源材料分支：`research/agent-client-packages-20261019`、`research/agent-reverse-20261019-claude-desktop`、`research/claude-desktop-gpt6-direct-20261020`。**  
**报告路径：`docs/research/agent-reverse/2026-10-20/claude-desktop-zcode/`。**  
**本地目录（原包与解包可保存在 Git 忽略目录）：`D:\Atlas\_research\claude-desktop\2026-10-20`，若实际机器路径不同，记录实际绝对路径。**

## 最高优先级纠偏（2026-10-20；覆盖下文所有冲突要求）

**任务只拆真实 Claude Desktop 发行包。不得再打开 Claude 窗口、截图、点 UI、尝试登录、连接 API、使用账号或要求用户提供认证。用户选择拆包就是为了避开未登录导致功能不可见的问题。**

- 所有研究依据优先来自 MSIX、ASAR、源码 bundle、Native/Go/PE 反编译、符号、AST、配置、IPC/RPC schema、静态调用关系。功能需要登录也要从静态代码找到客户端的完整实现入口、参数、状态、边界和调用链；不可得的服务器内部代码标 `CLOUD-UNAVAILABLE`，绝不凭空推测。
- 对前端也只做**代码级解剖**：HTML、JS/React 组件、布局、路由、菜单、事件、调用关系。可根据源码制作离线布局视图，但禁止把未登录软件截图作为研究成果。
- **阶段 P7 原“运行时取证”要求取消；不要求实际启动、测试、进程观测或操作 Claude，也不将缺少动态 R 级实证列为完成障碍。** P7 改为从静态实现构建启动/任务/退出/异常恢复的代码级时序图，并列明不可证实项。旧文中所有“实操、截图、登录环境、run ID、必须动态验证、W7 运行时取证”等冲突要求一律作废。
- ZCode 继续全面拆包：逐文件逐模块确认作用和层级，追调用者与被调用者，穷举动态生成 IPC、Agent/Cowork 的客户端路径、Go service、MCP、Skills、Worker、前端等。不能用关键词、文件清单、空泛介绍代替完整代码追踪。
- **不得为了运行观察花费资源、不得因没有 Claude 账号/API 停工或向用户索要这些条件。** 当前阶段只以静态证据和剩余未知项的透明列账验收。
- 已经制作的截图仅归档为 `out-of-scope`，不计入完成率；立即转入原包/反编译器/AST 分析。每阶段保存本地、push 仓库；无需再询问，直接继续。

## 0. 任务定义及不可误解的要求

这不是“研究 Claude 有哪些功能”，不是找几个有名的能力写文章，更不是先给出一个固定分类清单然后每类查几条。

目标是像解剖人体一样，**把每一个实际取得的文件、代码模块、后台组件、UI 入口、运行过程、协议、数据结构、依赖与资源先全部清点，然后逐项查清：它是什么，在哪里，干什么，如何工作，由谁调用，又调用谁，谁持久化状态，出错如何处理，能够从哪里在界面或运行时观察到。**

执行遵守以下硬规则：

1. **先穷举实际对象，再做语义研究**。禁止只用关键词搜索、只看 README、只照用户举例或旧功能矩阵查。
2. **发现什么就登记什么**：没有解析出来的对象也必须在账上，注明「未知/待解释」和原因。不能删除、隐匿、按“没用”过滤掉。
3. **不得把一个文件等于一个功能，或把函数总数等于功能数**。分别维护文件总账、符号/模块总账、功能总账、运行行为总账，彼此建立外键/证据关系。
4. **既从 UI 向下追，又从代码、服务和协议向上反查**，直到源与汇成链，不得停在“存在按钮/有接口”。
5. 每个事实指向**真实包 SHA、路径、行号或 byte/character offset、符号/调用点、实际日志/截图/可复现动作**。纯字符串、推断、官方介绍不许冒充源码/运行实证。
6. 研究结果必须**同时保存在本地和 GitHub 分支**。大体积原包/解包源码保留在本地研究目录；GitHub 保存合法可共享的目录、哈希、结构化索引、简短证据摘录、研究报告、截图和浏览器，不无必要地把数百 MB 闭源代码重新提交。
7. **不修改 Atlas main、不改正式业务源码、不实施复制功能、不扩散至 Codex/ZCode/OpenCode 等其它竞品**。此次只是解剖 Claude Desktop 的实际产品体系。内置 Claude Code 桥接可以查，但不要扩展成独立 Claude Code CLI 全包研究。
8. 速度优先。允许尽量多的并行子任务、成熟工具和机械脚本；分工互不覆盖。不要反复写空计划、做形式化验收、过度防御性编程或大量无价值回归。
9. 非必要不要停下询问。确实必须用户提供原包、可登录测试环境或权限时，只提出**具体不可替代的缺口**，同时继续推进不受阻的静态研究。
10. **绝不能用“100% 已破解/所有云端能力都拿到了”作为包装**。真正可验收的是可得工件逐项登记处理、每个已发现的入口和注册点有追踪状态、剩余未知可计数可定位。

## 1. 必读资料：先核对真实版本与旧研究

立即读取：

- `docs/research/agent-clients/2026-10-19/START-HERE.md`
- `docs/research/agent-clients/2026-10-19/manifest.json`
- `docs/research/agent-clients/2026-10-19/PACKAGE-INDEX.md`
- `docs/research/agent-clients/2026-10-19/COLLECTION-STATUS.md`
- `docs/research/agent-clients/2026-10-19/indexes/claude-codex-index.txt`
  （以上来自 `research/agent-client-packages-20261019`）
- `docs/research/agent-reverse/2026-10-19/claude-desktop/START-HERE.md`
- `docs/research/agent-reverse/2026-10-19/claude-desktop/COVERAGE.md`
- `docs/research/agent-reverse/2026-10-19/claude-desktop/FINISH-GATES.md`
- 该目录中的 `evidence/` 全部索引、`DISCOVERY-LEDGER.md`、`IMPLEMENTATION-TRACE.md`、`EXTRACTION-REQUEST.md`
  （来自 `research/agent-reverse-20261019-claude-desktop`）
- `docs/research/agent-reverse/2026-10-20/claude-desktop-direct/DIRECT-AUDIT.md`
- `docs/research/agent-reverse/2026-10-20/claude-desktop-direct/ASAR-OBJECT-LEDGER.tsv`
  （来自 `research/claude-desktop-gpt6-direct-20261020`，本工作分支已继承）。

已有基线样本：

- Windows x64 **企业版** Claude Desktop `2.42304.0`，Release asset `claude-desktop-x64-2bf309665f.msix`。
- 固定 MSIX **297,191,037 bytes**，SHA256 `2bf309665f0de4eaa76a7e64033594e6f73ceb6413c60080f72f3ce640fa24ee`。
- MSIX 中 `app/resources/app.asar` **49,338,428 bytes**，SHA256 `8f4d3dec5e4f3ddffb150321060b18807d83a40f3a65618fe4f29325379da9db2`。
- `app/resources/cowork-svc.exe` **13,761,360 bytes**，SHA256 `934e5b671813ef3d5684c0ee0d1d18835af74e9ecfb114575e0d8fdbb663ba8f`。
- 历史取证：MSIX 文件清单 **4,443** 条；ASAR 路径 **548** 条（此前独立复核为 **506 文件 + 42 目录**）；旧解析器显示 437 个 JS 执行解析成功，记录 1,535 IPC 相关操作，但**动态通道、符号语义、服务和运行时根本未穷尽**。
- Consumer Setup/消费者版当时获取失败，返回 `region_unavailable`；**不能默认企业版与消费者版相同**。
- 旧 REA 全局语义图被 100,000 节点预算截断、单次语义输出不足，**不得把“437 个 JS parse success”写成“437 文件全部理解”**。
- 原包归档：`https://github.com/unicorn-Y/Atlas/releases/tag/agent-client-packages-20261019`。

**首先主动查证截至实际执行日官方可获得的版本**（官网、已安装应用和合法可获取的发行通道，记录版本/发布日期/来源）。已有 2.42304.0 是**固定基准**不是未经核实的“最新版”。新版本可得则分析最新实物，并将 2.42304.0 作为历史比对；拿不到新版必须明确写“latest unverified”，继续解析固定样本。不要编造下载成功。

## 2. 总体产出：四种完整账 + 三种关系图

必须建立**四份彼此关联的机器可检索总账**：

A. **对象账（物理层）**：包 / 文件 / 目录 / 嵌套容器 / 运行时新下载文件 / 模块 / 扩展 / 二进制；每项有稳定 ID。

B. **符号与实现账（代码层）**：导出 API、模块初始化、类、函数、注册器、事件、IPC、路由、状态存储、Native imports/exports、Go 符号等；每项必须关联 A 的位置。对大型第三方库可逐文件分类、逐 API 关联关键调用，避免毫无意义地人工描述 Chromium 的每个内部函数，但**物理账任何文件都不能消失**。

C. **能力与交互账（产品层）**：每一个发现的实际 UI 入口、动作、工作流、工具、Agent 能力、插件、开关、后台机制、实验入口。其成员不限于最初列举的分类。

D. **运行行为账（动态层）**：时间线、进程、线程/worker、窗口、数据事件、资源加载、网络访问模式、持久化文件、失败/中断/恢复、开关差异，运行不可及的项明确 U。

形成至少三种链接：

1. **组件依赖与调用图**：谁加载/调用谁，含跨进程边界。
2. **UI → 状态 → IPC/API → 主进程 → 服务/云 → 数据库/结果** 的端到端图。
3. **启动/任务/终止/恢复时序图**：包括正常、失败、断线、重启、取消路径。

单条对象的最少字段：

`id, product_version, source_package_sha256, path, layer, kind, symbol_or_offset, name, purpose, trigger, inputs_outputs, calls, called_by, state_owner, persistence, ui_entry, runtime_observation, evidence, confidence, status, unresolved_reason`

不适用字段写 `N/A`；未查明写 `UNKNOWN`，不可混用。长正文可以拆表，通过 ID 引用。

## 3. 阶段 P0 — 包获取、真实性、版本与完整性

- 优先使用已归档 Release 与本机合法缓存；确认真实包内容与 SHA；检查官方 Consumer 下载通道、现有安装目录、本地更新缓存。记录 `consumer`、`enterprise`、`channel`、`arch`、`platform`，切忌跨版本拼证据。
- MSIX、内嵌 ASAR、`asar.unpacked`、`EXE`、`DLL`、`.node`、`.jsc`、`.wasm`、`pak`、skills、资源、生成 web bundles：递归列路径/大小/SHA/格式/嵌套关系/签名/入口。
- 清点 Windows 服务和安装/更新组件；明确什么随包交付，什么首次启动动态获取，什么仅云端存在。
- 生成机器可计算的 `PACKAGE-MANIFEST.tsv`、`FILE-LEDGER.tsv`、`ARCHIVE-NESTING.tsv` 和 `VERSION-MATRIX.md`。
- 将已有 4,443 与 548 条基线逐项 diff，新增、删除、路径编码差异、解包失败必须逐行列出。不要只说“差不多一致”。
- 无法获取 consumer 包，列具体 URL/响应/时间/哪一种环境可能补采；仍继续企业版。macOS 如果不同，做平台差异线索表，**不得以 macOS 线索冒充 Windows 实装**。

**P0 成果**：所有已取得实物可被重新定位与哈希复验；每一条已归档路径有对应记录。

## 4. 阶段 P1 — 静态代码全覆盖发现（不要让大模型读完整巨型 bundle）

依照包真实入口构建程序链：`AppxManifest.xml → Claude.exe → package.json → .vite/build/index.pre.js → main chunks/preloads/workers → renderer HTML/chunks`。不要根据文件名想象调用关系。

- 使用成熟工具组合：ASAR、AST parser（OXC/Acorn/SWC/Tree-sitter 等选一两种）、ripgrep、sourcemap 工具（仅当实际有 map）、Ghidra/REA、PE/Go 符号工具；可写小型提取脚本，不重造 REA。
- **逐文件/逐 chunk** 抽取 import/export、function/class、方法注册、上下文桥、IIFE 工厂、动态载入、事件订阅、feature gate、schema/type、存储 API、进程 API、网络 API，并建立交叉引用。
- 对打包混淆、生成式 API 或三百万字符以上的块，用 AST/调用点与 offset 做可续跑的分段扫描；**不要再次整包塞给一个有节点上限的语义图然后把 truncated 结果当全量**。
- 明确 `native`、`.jsc`、编译缓存和第三方依赖的可解析边界；原生程序至少做 imports、exports、strings、控制流/关键函数的实物追踪。无源码也不许省略。
- 静态字符串可能是死代码、兼容层或实验开关；标注 `registered / referenced / gated / orphan / unobserved`，不能直接认定可用。
- 对全部 506 个既有 ASAR 文件条目，逐条填写**用途分类 + 是否经实际代码确认 + 未解原因**；新增版本按实际数量替换。
- 建 `MODULES.tsv`、`SYMBOLS.tsv`、`CALL-EDGES.tsv`、`DYNAMIC-IMPORTS.tsv`、`UNRESOLVED-SYMBOLS.tsv`。

**P1 成果**：每个已取得文件已处理或明确解释为何不可能解释；关键第一方业务代码不允许仅标“JS bundle”。

## 5. 阶段 P2 — 前端、全部窗口、所有交互及界面还原

从现有全部 renderer HTML 和 BrowserWindow 入口实物穷举，不只主页面：

- 主聊天、侧栏、会话列表、搜索、项目、文件、附件、代码块、工件、交互文档/表格/幻灯片等**以实际源码发现为准**。
- quick/about/buddy/find-in-page/local-exec-consent/design、所有弹窗、菜单、托盘、右键菜单、快捷键、命令面板、拖放与通知。
- Cowork、Chat、任务卡、会话跳转、后台任务、定时任务、Agent 状态、审批、进度、token/usage 统计、计算机操作实时画面——只有找到相应代码/运行证据才列为实现。
- 动态组件、Markdown/HTML/Artifact 渲染、iframe/webview、工具回执、文件树、任务历史及错误 UI。
- 每一入口追踪 `window/route/component → event handler → state change → preload/API → host handler → reply/event → UI state`；不能只写截图或组件名称。
- 给 UI 元素建立可按窗口浏览的 `UI-SURFACES.tsv`、`UI-ACTIONS.tsv`、`HOTKEYS.tsv`、`UI-STATE-LINKS.tsv`。
- 禁止启动软件或截图。基于实际 renderer HTML、bundle、CSS、组件、路由创建有代码锚点的静态 UI 结构目录，必要时生成离线预览。
- 为用户制作**可离线打开的 HTML 浏览器**：树状导航 → 点击模块/页面 → 功能用途、关联源码位置、截图/静态预览、IPC、层级和未解析标记；支持全文搜索、层级筛选、状态筛选。

**P2 成果**：每一个找到的 window/route/menu/action 都有登记和处理状态，未闭合的 UI→执行链统计为明确数字。

## 6. 阶段 P3 — IPC / RPC / HTTP / 事件与执行流逐条配对

静态索引原报告显示 1,535 条 IPC 操作，但旧 `ipc-map.tsv` 只有 8 行，**这是这次重点缺口，不能原样继承**。

- 从 `contextBridge.exposeInMainWorld`、preload、ipcRenderer、ipcMain、生成式 channel builder、webContents 事件、MessagePort、utilityProcess、Node child_process、命名管道、WebSocket/SSE/HTTP 逐类枚举。
- 对动态生成的 `Foo_$_bar` 家族，不要只 grep 字符串；找到 schema/注册器、生成器、method 表、invoke wrapper 与 main handler 的关系，生成可核对的配对表。
- 逐项记录 source/caller、destination/handler、argument/response schema、错误/取消/超时、事件消费者、状态写入、权限/feature gate、对应操作。
- 找出“只有 wrapper 无 handler”“只有 handler 无 caller”“仅 feature flag”“只在旧版本保留”“cloud endpoint 不可见”等状态，输出未配对列表。
- 已知样例必须重新查：CoworkArtifactBridge 的 `callMcpTool`、`askClaude`、`runScheduledTask`、`navigateHost`、`openExternalUrl`；MCP setup；scheduler；ComputerUseLivePreview；ClaudeVM。
- 与 P2 UI 表、P4 Agent 表、P5 native/service 表建立双向可点击关系，不允许各写各的孤岛报告。

**P3 成果**：`IPC-REGISTRY.tsv`、`RPC-SCHEMAS.tsv`、`EVENT-PRODUCER-CONSUMER.tsv`、`NETWORK-ENDPOINTS.tsv`、`UNPAIRED-CALLS.tsv`；每个已知注册项必须有已闭合或待解状态。

## 7. 阶段 P4 — Chat / Cowork / Agent 主运行机制

重点不在营销名称，在实际“任务从输入到结束”：

- 模型/能力选择、上下文准备、prompt/schema/template、会话/Thread/Turn/Task、工具发现/参数构造/回执、长任务继续、进度/取消/转交、错误与重试、Token/用量。
- 是否有本机 Agent loop、云 Agent loop、Code launcher、legacy VM、任务调度器：分别标明执行所有权；**不能因为客户端有 cowork-svc.exe 就说当前所有 Cowork 都本地执行**。
- 子代理/并行/委派/子会话/任务卡：若存在，拆创建、生命周期、通信、展示、可点击干预、停止、恢复。若只有 UI 词汇/教程字符串则标待验证，绝不乱补。
- 数据持久化：本机配置/文件/SQLite/LevelDB/IndexedDB/日志/缓存、账号云会话、订阅 cursor、resume、cold start、崩溃恢复；注意“UI 重订阅事件”不等于“Agent 真正恢复执行”。
- Skills、Plugins、MCP、连接器、浏览器、文件系统、Shell/PTY、Computer Use、Artifacts、Scheduler、文件索引、实时预览等都要从业务执行链逆向。
- 对云端内部无法取得的 server-only 行为，只分析**可合法观察的客户端调用及返回协议、持久化表现、官方说明**，标 CLOUD-UNKNOWN；不得伪称知道服务器内部实现。

输出 `AGENT-LOOP.md`、`SESSION-STATE.md`、`TOOLS-REGISTRY.tsv`、`SCHEDULER.md`、`PERSISTENCE-MAP.tsv`、`RECOVERY-SEMANTICS.md` 和关键时序图。

## 8. 阶段 P5 — Windows 原生宿主与 cowork-svc 深入解剖

此前只解出部分 Go pclntab 和 Hyper-V 处理链，继续：

- `Claude.exe`、Electron/Node、预加载 native modules、`cowork-svc.exe`、Go PE、Windows SCM、服务安装/启动/停止、签名、版本、权限及对进程树的影响。
- 根据 Ghidra、Go pclntab、交叉引用和实际代码体逐函数处理 RPC handler/VM manager/网络/文件/持久化/调度相关实现；不把 12,769 个过程名的存在当作 12,769 个已解析函数。
- 既有重点链：`\\.\pipe\cowork-vm-service`；4-byte big-endian JSON 帧；10 MiB 限制；`configure/startVM/stopVM/isRunning/isGuestConnected/spawn/kill/writeStdin`；事件 `stdout/stderr/exit/error/networkStatus/apiReachability/startupStep`。
- 查明**真实安装服务者、真实父进程、app→service→VM→guest 的完整调用时序**。核实 packaged 的 system-owned pipe 身份要求与 native addon 的实际入口，不只引述旧文档。
- 对 VM 创建、bundle 载入、磁盘、内存/CPU 配额、网络与 guest 文件桥、失败回滚、服务重启逐项列出代码和运行证据。
- cloud task 与 legacy local VM 的分界、feature flags 和账号 rollout 必须明确；无法取得服务端代码继续标 U。

输出 `NATIVE-PROCESS-MAP.tsv`、`GO-FUNCTIONS.tsv`、`SERVICE-RPC.md`、`VM-LIFECYCLE.md`、`SERVICE-FAILURES.md`。

## 9. 阶段 P6 — 不漏掉旁支、资源、扩展与未知能力

专门从容易漏的真实路径反查：

- `resources/bundled-skills/`：docx、pptx、xlsx、pdf、pdf-reading、frontend-design 六个具体 .skill 文件；分别追清注册/提供方式、触发条件、执行器与环境。
- `resources/github-mcp/`、`resources/office365-mcp/`：打包程序、注册、账号/权限、工具调用、配置与生命周期；**打包存在不等于启用可用**。
- `mcp-runtime/nodeHost.js`、`directMcpHost.js`、扩展 marketplace / DXT/MCPB 安装/更新/验证、第三方 host。
- `pty-host`、scrollback/read/redact、`file-index-worker`、heavy-work-worker、ComputerUseTeach/WatchRecord、Artifact libraries、scheduler 迁移字段等。
- 全面扫描：feature flags、experiment/rollout、未引用的注册器、升级迁移代码、compat/legacy、异常分支、埋点事件、隐藏菜单和首次使用引导。
- 与**对应版本**官方 changelog、帮助文档、公开接口、更新差异交叉核对；只用官方声明新增线索，不能直接当本 MSIX 实现。

输出 `EXTENSIONS-AND-SKILLS.md`、`DEPENDENCY-ROLES.tsv`、`FEATURE-FLAGS.tsv`、`UNKNOWN-DISCOVERIES.tsv`、`VERSION-DELTA.md`。

## 10. 阶段 P7 — 静态运行机制还原（不启动 Claude）

- 从发行包的代码/二进制反编译结果还原 Electron 主进程、renderer、preload、workers、native 和 cowork-svc 的调用依赖与生命周期。
- 对所有登录后功能，继续静态追踪 UI 代码入口→动作→状态→IPC/RPC/网络客户端→服务边界。缺服务器内部实现标 CLOUD-UNAVAILABLE。
- 双向求差：UI 注册点是否有处理链；handler 是否有前端调用者；Go service 的 handlers 是否有已建立的边。
- 生成 STATIC-LIFECYCLE.md、STATIC-STATE-AND-EVENTS.md、UNRESOLVED-CALL-EDGES.tsv；没有登录/API 不阻塞。
- 不启动应用、不截图、不做动态验收。静态代码可推导的运行行为标 S，无法推导的标 U，不能标 R。

## 11. 阶段 P8 — 可理解的“人体解剖目录”与本地可浏览成果

最终不能让用户翻几十个无组织文件才能知道有什么。制作：

- `00-START-HERE.md`：版本、总结、完成覆盖率、未解项、目录入口。
- `01-LAYER-ATLAS.md`：按层级展开从包/OS/Electron/renderer/preload/host/service/VM/tool/agent/cloud boundary/存储的架构地图。
- `02-COMPLETE-CAPABILITY-CATALOG.md`：每个能力的中文用途、父子模块、界面、输入输出、调用链、状态、证据、可运行性。
- `03-FILE-AND-MODULE-INVENTORY.tsv`：逐个文件/模块，路径/哈希/功能层/类别/解释状态和关联能力 ID。
- `04-SYMBOL-AND-FUNCTION-INDEX.tsv`：重要第一方函数/类/注册点完整机读索引及交叉引用。
- `05-UI-CATALOG.md` + 图片：每个窗口/功能/动作/快捷键、可见状态。
- `06-IPC-RPC-EVENT-MAP.md` + 机器可读表：全链。
- `07-AGENT-RUNTIME.md`、`08-SERVICE-AND-VM.md`、`09-EXTENSIONS-TOOLS-SKILLS.md`、`10-DATA-PERSISTENCE-RECOVERY.md`。
- `11-EVIDENCE-INDEX.tsv`：每项报告结论到包路径/源码 offset/哈希/实操 run ID/文档的精确证据。
- `12-UNKNOWN-AND-BLOCKERS.tsv`：不能解释/不能观测/服务端不可见对象，一个不隐藏。
- `13-COVERAGE-AND-ACCEPTANCE.md`：可再计算的覆盖率/差集/抽查结论。
- `viewer/index.html`：离线可浏览导航，表格按名称/层级/用途搜索，点击能力看到实现链和证据，能打开真实可分享的截图/HTML 静态预览；显示 unknown，不得伪造交互能力。

文件允许按实际规模切分为多个 TSV/JSON/SQLite；必须保持稳定 ID 和统一索引。建议对报告使用易懂中文，源码符号保留原名。每个模块写清楚**“它的作用是……”**，不要堆抽象名词。

## 12. 覆盖率与真实性的机械验收规则

**严禁 ZCode/DeepSeek 自己一句“全部完成”就结案。** 由另一独立检查过程**重新从原包生成**路径/哈希/符号/注册点索引，与报告总账求差：

- `source_files - accounted_files = ∅`：所有已取得原包内文件都有账。
- `accounted_files - (explained OR explicitly_unresolved OR nonfunctional_resource) = ∅`：每一条状态明确。
- `discovered_windows_routes_actions - ui_registered_items = ∅`。
- `discovered_ipc_rpc_event_registrations - tracked_registrations = ∅`。
- `observed_runtime_features - capability_ledger_items = ∅`。
- `all_report_claims - grounded_evidence_claims = ∅`，推断单列，不允许混入证实。

把具体分子分母、未解释数、未配对数、静态确认数、动态确认数、官方声明数写清楚。

证据等级：
- **S** = 真实源码/二进制/符号/调用链，有定位。
- **R** = 相同版本真实运行，有步骤/时间线/日志/截图。
- **D** = 官方文档声明，只能证明官方说过。
- **I** = 推断，要说明依据。
- **U** = 未解释或无法验证，说明原因和补采办法。

验收门槛：
1. **文件登记率 100%（已取得的全部发行物）**，包含新版本和嵌套容器的实际项；目录与文件不可混计。
2. **每个注册点/界面入口均有状态与证据指向**；能配对则追到末端，不能配对列入明确 U 列表，绝不以零填未知。
3. **重要业务机制给出端到端实证链**，最低包括 Chat send、Cowork/任务、Artifact/工具、Scheduler、MCP、Service/VM、状态/恢复；若硬阻塞，保留 PARTIAL 状态。
4. **独立复查新发现**：额外运行按文件树/导出/配置/事件/日志反向搜索的查漏程序，列出这次新挖出的未知组件和功能，而不是只复核旧功能名。
5. 不得把“所有已发现项已登记”升级成“所有云端/服务器内部都已逆向”。
6. **如果本地可分析材料和动态测试环境仍有明确可做的项目，不能宣布结束；除非发生硬阻塞并准确说明是什么。**

独立复核可以是同一 ZCode 里的隔离检查任务，但必须**从原始目录重新生成清单**，不许直接抄前一研究者的结论。效率优先，优先自动化差集，不写一堆无意义测试程序。

## 13. 并行施工方式与保存纪律

ZCode 负责统筹，能开多少有效子任务就按实际可用并发尽量开；建议按独立目录分工：

- W1 包/版本/哈希/全部文件总账；
- W2 Electron main/preload/worker/所有 IPC；
- W3 Renderer/UI/窗口/动态组件/视觉浏览器；
- W4 Chat/Cowork/Agent/Scheduler/数据状态；
- W5 Windows Go service/Hyper-V/Native；
- W6 MCP/Skills/插件/浏览器/PTY/Computer Use；
- W7 完整**静态**覆盖审计，独立从原包重建索引。

同一源码可以交叉分析，输出文件按分工隔离，最后 ZCode 整合去重；避免多个 worker 同时覆盖同一个报告。无需为了“流程”浪费模型 token。

**每阶段提交并 push 一次真实结果**，checkpoint 不代表 COMPLETE。中断可以从上次 SHA 和 `PROGRESS.md` 恢复。更新 `PROGRESS.md` 列出本轮新增实物、实际完成、下次待办、剩余阻塞。发现新能力随时插入目录，不受本任务书例子的限制。

对于体积大的解包源和离线工具，请存本地研究目录并在 GitHub 写出准确索引、哈希和如何打开，不要为了省空间删除证据，也不要将私人授权令牌上传 Git。

## 14. 禁止出现的虚假“完成”表述

- “搜到若干关键词，功能已经全部覆盖。”
- “ASAR 解包成功，所以 Claude 已经逆向完成。”
- “437 个 JS 全部 parse 成功，所以理解了整个桌面端。”
- “生成了 1,000 条调用图，所以 IPC 全部闭合。”
- “文件名包含 subagent/browser/computer use，因此已确认可运行。”
- “服务里出现 Go 字符串，所以云端 Agent loop 在本机。”
- “仅凭官方更新文档就能说明当前固定版本有全部新 UI。”
- “做了报告，但看不到原始文件、行号、偏移或运行记录。”
- “已提交本地但未 push，却宣称仓库可验收。”

## 15. 完成回复格式（必须是真实已推送的结果）

```text
CLAUDE DESKTOP ANATOMY
STATUS: COMPLETE / PARTIAL / BLOCKED
Executor: ZCode + configured DeepSeek
Target: Claude Desktop Windows [consumer/enterprise/channel/version]
Package SHA256: ...
Branch: research/zcode-claude-desktop-anatomy-20261020
HEAD commit: ...
Report: docs/research/agent-reverse/2026-10-20/claude-desktop-zcode/00-START-HERE.md
Local offline viewer: <real full path>
MSIX files registered: N / N
ASAR files registered: N / N
First-party modules indexed: N
Symbols indexed: N
UI entrypoints: confirmed N / unresolved N
IPC/RPC registrations: paired N / unpaired N
Agent/runtime mechanisms: S N / R N/A / D N / I N / U N
Runtime test runs: NOT APPLICABLE (static only)
New/previously unknown discoveries: N
Remaining blockers: <specific list>
Independent audit: PASS / PARTIAL / BLOCKED; discrepancy count N
```

**立即开始执行。不要只回计划；第一步先验证原包与当前版本，产出实际文件账，并 push 第一个可检查的 checkpoint。除真正不可替代的材料或权限缺口以外，不需要中途征询用户。**
