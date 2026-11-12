# Atlas 全项目与真实运行时审查

> 后续进展：[Gemini 真实工作过程补充审查](ATLAS-GEMINI-RUNTIME-AUDIT-2026-10-15.md)。该报告新增工作过程、控制交互、效率对照及补测结果；本报告保留第一轮观测时间与原始统计。

审查日期：2026-10-15。运行采样截至香港时间 16:24 左右。对象为正在使用的 `D:\Atlas`，分支 `ui-redesign`，提交 `fd5efb1afbdad253ed27e0f96ae35e991c179e4a`。

## 结论

当前 Atlas 可以启动、打开主要页面、执行一次真实的只读文件工具调用，并完成一次最小模型对话；但还不能据此判定整体稳定。本次整理出 **16 项问题、风险或配置缺口，其中 5 项 P1、10 项 P2、1 项 P3**。最应先处理的是：模型流缺少等待上限与重试可见性、阻塞流的取消竞争、异步 PR 接口阻塞后端事件循环、仍在使用受 WAL-reset 缺陷影响的 SQLite，以及依赖声明和锁文件不一致。

本次没有修改产品源码、配置或依赖，没有重启前台程序，没有推送、发布或创建远程 PR。产生了一个明确命名的测试会话、两个真实测试 run，以及本报告和审查临时证据。测试超时遗留的 8 个服务进程，经工作目录和 `ATLAS_DATA_DIR` 核实均属于本次隔离测试后，已经清理；前台后端进程没有变更。

以下把证据分为“实际运行复现”“隔离复现”“源码确认的风险”“配置现状”。没有把测试失败条数当作产品 Bug 数量，也没有把缺少防护直接写成已经发生的攻击。

## 优先级清单

| ID | 优先级 | 问题 | 证据性质 |
|---|---|---|---|
| A01 | P1 | 模型流可长期无输出等待，连接重试缺少上限且前台不显示重试 | 真实运行 + 源码 |
| A02 | P1 | 取消阻塞的同步流时发生 `generator already executing`，工作线程未被可靠回收 | 隔离复现 + 源码 |
| A03 | P2 | 同一工具调用生成两个完成事件和两张工具卡片 | 真实事件回放 + UI + 源码 |
| A04 | P2 | 原始用量有缓存 token，完成汇总与统计丢失 | 真实运行 + 源码 |
| A05 | P1 | `async` PR 接口内同步执行 Git/gh，阻塞事件循环 | 隔离复现 + 源码 |
| A06 | P1 | SQLite 3.50.4 仍打开 WAL 渠道库，存在已知数据完整性风险 | 运行解释器 + 数据库 + 当前启动日志 |
| A07 | P2 | 原始配置接口把真实凭据明文返回渲染端 | 实际接口检查，仅保留布尔证据 |
| A08 | P1 | package.json、锁文件与实际安装版本不一致 | 文件与运行版本对照 |
| A09 | P2 | 自动化验证门禁不可靠，存在旧夹具、收集错误、超时与进程遗留 | 实际执行测试 |
| A10 | P2 | 开发态实际 Node/MCP 可用，依赖检查仍报告全局阻断 | 实际接口 + 源码 |
| A11 | P2 | 集成能力页串行刷新慢，加载期间显示 0，缺少请求期限 | UI + 接口等待 + 源码 |
| A12 | P2 | 已结束 run 与完整事件长期保留，缺少内存淘汰策略 | 源码确认，未做长期压测 |
| A13 | P3 | Electron 测试文件进入编译目录并落入打包包含规则 | 当前编译产物 + 配置 |
| A14 | P2 | 主渲染页面没有 CSP | 当前页面 + 源码，防护缺口 |
| A15 | P2 | React 根部缺少可恢复的错误边界 | 源码，故障恢复缺口 |
| A16 | P2 | 部分已登记技能与 PowerShell LSP 缺少实际依赖 | 实际诊断 + 当前启动日志 |

P1 表示应优先修复的可靠性、数据或交付一致性问题；不表示这些故障在每一次运行中都会触发。

## 本次实际检查了什么

| 范围 | 方法与结果 |
|---|---|
| 代码与结构 | 枚举 1,680 个受 Git 跟踪文件；对 723 个相关代码文件、约 191,310 行进行程序化扫描和定向追踪。497 个 Python 文件 AST 解析通过。语义审查重点追踪了启动、路由、模型流、取消、工具事件、用量、持久化、安全边界和打包链。不是逐行人工证明全部代码正确。 |
| 正在运行的桌面 | 通过 CDP 连接实际 Electron，确认加载 `file:///D:/Atlas/frontend/dist/index.html`，不是另起的网页演示。Electron 主进程 36732；实际 Python 后端 37204，启动链包含 venv launcher 37288。 |
| 页面 | 打开 Agents、工作台、记忆、自动化、技能与工具、设备、自动追新等 7 个主要入口；检查 28 个设置区和开始向导的打开/关闭。采样窗口 1440×920，无横向溢出，未观察到主页面崩溃。没有保存配置或执行外部账户操作。 |
| 后端 API | 首轮 30 项、补充 60 项只读 GET 探查，覆盖模型、供应商、项目、记忆、运行时、工具、技能、插件、设备、自动化、通知、安全、工作台等。补充轮 3 个缺少必填查询参数的 422，在提供有效参数后均得到 200，不计作缺陷。OpenAPI 有 391 个路径、184 个 GET 操作；并非全部调用。 |
| 真实聊天与工具 | 创建明确标记的测试会话，执行一次只读 package.json 读取、一次最小纯文字回复；检查 WebSocket 顺序、工具结果、取消、完成状态、磁盘 run 日志和历史消息。 |
| 数据 | 只读检查当前 data 下 8 个业务 SQLite 数据库，`quick_check` 全为 `ok`。历史 pytest 临时库单独排除，未把旧测试库当生产库。 |
| 构建 | Electron 与 renderer TypeScript 检查通过；隔离目录中的 renderer Vite 构建通过；Electron 主进程重新编译结果与运行目录对应文件比较无漂移。没有覆盖前台 dist，也没有重新打安装包。 |
| 测试 | 执行前端、后端 unit/integration、独立 adapter、preload 检查；详情见下文。后端全套未完整通过，也未完整跑完。 |
| 安全边界 | 验证外部 Origin 和 null Origin 被拒绝；核对 Electron sandbox、context isolation、node integration、导航和 IPC sender 校验；检查配置凭据返回和 CSP。没有执行攻击性数据写入。 |
| 依赖与日志 | `pip check` 通过。对照清单/锁文件/已装版本；区分当前启动和历史日志。npm audit 因 registry TLS 连接失败未得到有效结果。 |

## 问题详情与修复验证条件

### A01 · P1：模型流没有完整的等待边界，前台看不到连接重试

实际运行中，首次测试约 15 秒后已成功读取文件，但之后持续显示调用模型，没有最终回答；在约 120.27 秒时手动停止了这次测试。第二次只要求回复 `ATLAS_AUDIT_OK`、不调用工具，最终成功，但约耗时 61 秒。磁盘记录了 3 次连接失败重试，退避分别为 5、10、20 秒；成功响应本身约 2.98 秒，前台事件没有传达这些重试原因和倒计时。

`core/atlas/models/router.py:653` 默认设置 `read=None`；`core/atlas/kernel/model_call.py:653` 等待同步流下一块时没有空闲期限。该函数在 `:564` 默认启用 `unbounded_connection_retries`，`:803` 后的连接重试逻辑可越过普通 max_retries。`core/atlas/kernel/loop.py:717` 主要把重试写入日志，没有同步为 UI 状态事件。

影响：提供方断连或流停滞时，用户难以区分“还在推理”“正在重试”和“已经卡住”。真实测试证明出现过长等待；源码证明存在缺少期限的路径，不等于本次观测到了数学意义上的无限等待。

建议：为连接重试设置总时长/次数预算，为流增加空闲超时，将重试类别、次数、下一次尝试时间和可停止状态传到前台。验证应覆盖连接连续失败、响应头后不再出块、重试后恢复、用户取消四种情况。

### A02 · P1：取消阻塞流存在生成器关闭竞争

`core/atlas/kernel/model_call.py:643`、`:653` 把同步生成器迭代放入线程；`:661` 检测取消后，又从另一个线程调用同一生成器的 `close()`。当生成器正在执行时会抛 `ValueError: generator already executing`；取消 asyncio task 也不能停止已经在执行的线程。

隔离探针使用假生成器和本地线程，不调用真实模型或网络，稳定得到 `ModelCallError: generator already executing`，取消返回时工作线程仍处于生成器内部。探针再次执行仍复现。当前桌面那次取消成功，只说明该时刻没有触发这一竞争，不能排除阻塞出块时的路径。

建议：使用可取消的异步传输，或由流所属线程关闭底层传输并可靠退出；不要跨线程直接关闭正在执行的生成器。验证取消应得到 cancelled 终态而不是 model error，并确认后台工作线程/连接最终退出。

### A03 · P2：一次工具执行发出了两次完成事件

真实 run `c3cef1d3-27b8-4c93-bf41-dd0c90b7cf15` 的序号 7、8 都是同一 call id 的 `tool.completed`。第一个包含文件结果，第二个是上层 receipt。前台出现“读取 D:/Atlas/package.json”和“处理文件”两张卡片。

来源是 `core/atlas/agent/tool_node.py:1408` 构造工具结果并在 `:1419` 入队，上层 `core/atlas/kernel/loop.py:1459` 又发出相同调用的 `tool_result`，随后映射为两个完成事件。证据支持“事件和展示重复”，没有证据表明实际读文件执行了两次。

建议：明确唯一工具生命周期事件的生产者，或将 receipt 合并到已有 call id 的结果中。验证真实调用和重连回放都只显示一张终态卡片，且输出和 receipt 都保留。

### A04 · P2：缓存用量在事件到汇总之间丢失

第二次真实 run 的 `run.usage` 包含 `input_tokens=19508`、`output_tokens=6`、`cached_tokens=256` 和 `prompt_cache_hit_tokens=256`。同一 run 的 `run.completed.usage.cached_input_tokens` 却为 null，`cache_hit_rate` 为 null，当日 usage 的缓存累计为 0。

`core/atlas/kernel/loop.py:694` 生成 `cached_tokens`，而 `core/atlas/usage.py` 的汇总/持久化读取 `cached_input_tokens` 等规范字段，未完整归一化这些提供方别名。

影响：缓存命中率、成本判断和用量分析失真。建议在模型响应边界统一字段，保留“未知”和“真实为零”的区别；用本次提供方用量样例验证原始事件、完成汇总、数据库与 usage API 一致。

### A05 · P1：PR 路由会阻塞整个后端事件循环

`core/atlas/api/workspace_router.py:942` 是 async 接口，但在 `:951`、`:957`、`:966` 直接 `subprocess.run`，超时分别可达 15、120、60 秒，后续还调用同步 gh 查询。同文件的其他 Git/PR 路径也需要一并检查。

隔离探针把这些外部操作替换成假调用，没有执行真实 Git、网络、推送或创建 PR。3 个约 120ms 假调用让事件循环最大调度间隙达到约 362–376ms，证实存在阻塞。

影响：操作期间健康检查、WebSocket 消息、取消等共享同一事件循环的请求可能一起迟滞。建议使用异步子进程或有边界的线程卸载，并统一处理超时。验收需在慢 Git/gh 操作期间持续发送健康请求与取消请求，验证仍能及时处理。

### A06 · P1：当前渠道库仍处于受影响 SQLite 版本的 WAL 模式

实际后端解释器链接 SQLite **3.50.4**，`data/channels.sqlite` 当前 `journal_mode=wal`。本次启动 07:42Z 的日志明确警告 WAL-reset corruption bug，并说明因已有并发打开者而没有在线切换 WAL。8 个当前业务库的 quick_check 都通过，因此不能声称已经发生损坏。

[SQLite 官方 WAL-reset 缺陷说明](https://sqlite.org/wal.html#walresetbug)列出了受影响版本和修复版本：3.51.3，或回补的 3.50.7 / 3.44.6。这是特定并发条件下的风险，不是每次写入都会损坏。

建议：升级实际打包/运行的 SQLite 库，不能只改 Python 依赖清单。安排有备份的停写验证窗口，确认新进程实际 sqlite_version 与渠道写入/检查点路径。审查中没有对前台数据库做 journal 切换或迁移。

### A07 · P2：原始配置 API 返回完整凭据，弱化了其他设置页的脱敏承诺

`core/atlas/api/config_editor_router.py:61` 的 `_state()` 把 config/settings 文件原文和 effective config 直接放入响应，`:78` 的 GET 接口返回这些字段。实际响应检查确认 settings 中存在非空真实 api_key；本报告不记录值，证据文件也不包含该接口正文。

外部 Origin 被拒绝的保护已验证，所以这不是已证明的任意远程泄露。但渲染端能够拿到原始密钥，原始编辑器与其他设置接口“密钥不回传”的边界不一致，增加渲染端受损、调试记录或导出误带凭据的影响。

建议：明确原始编辑器的敏感权限边界；普通读取使用脱敏占位，秘密采用单独的输入/更新通道。保存时不能把脱敏占位覆盖成真实配置。验证所有配置读取/导出接口与渲染端状态都遵守同一策略。

### A08 · P1：依赖版本与锁文件不一致，当前构建无法代表干净安装

| 包 | frontend 声明 | 根锁文件 | 实际安装 |
|---|---|---|---|
| vite | ^8.3.4 | 6.4.3 | 6.4.3 |
| esbuild | 0.28.2 | 0.25.12 | 0.25.12 |
| katex | ^0.16.47 | 0.18.10 | 0.18.10 |

当前 renderer 构建通过，使用的是实际安装的 Vite 6.4.3。TypeScript 7.0.2、Vitest 5.0.4、Electron 44.7.0 在本次对照中一致，不能把所有依赖都说成漂移。

影响：新机器、CI 或重新安装可能与本机行为不同。没有在用户正在使用的 node_modules 上运行 npm ci，所以不声称已经观察到 npm ci 失败。建议统一声明和锁文件后，在独立目录执行干净安装、构建、preload 和测试，再验证打包运行。

### A09 · P2：自动化验证体系存在显著断层

前端：28 个测试文件，25 个文件通过、3 个失败；188 项中 171 通过、17 失败，另有 7 个未处理错误。失败集中在 backendProcess 的旧返回结构/假计时器/启动模拟，以及 Electron navigation 的旧 mock。部分“源码 Python 选择”测试还读取了实际 `data/runtime/backend.pid`，因此测试结果受正在运行的前台影响。

后端：最终隔离执行的 JUnit 包含 1,995 条记录：**1,818 通过、161 断言失败、11 错误、5 跳过**。11 错误包括 2 个收集错误、8 个测试工作进程退出和 1 个调度器内部错误。终端口径为 `169 failed, 1818 passed, 5 skipped, 2 errors`；工作进程退出在终端和 JUnit 的分类不同，不能把两组数字相加。调度器最终 `KeyError: <WorkerController gw9>`，因此尚有测试没有执行。

可确认的主要类别：40 个旧夹具未提供 Atlas agent/runtime context；12 个 FixtureConfig 缺少 raw；旧 Hook 测试未经过当前信任审查；测试请求未适配 Origin 校验；8 个模型网络测试发生 TLS EOF；以及运行时接口/方法被移除后的旧断言。收集错误是 `atlas.hermes_pin` 和 `ATLAS_PROBE_NONCE` 无法导入。不能仅凭这些失败判定对应功能全部坏掉。

独立 adapter：主源码测试文件 18 项中 17 通过、1 失败（调用不存在的 `deleteFact`）。项目现有命令的根目录筛选还把 `data/upstream/staging/atlas` 内同名测试一起收集，原始输出是 36 项、34 通过、2 失败；主源码和 staging 结果已分开，不重复计算。

preload 检查：`frontend/scripts/test-preload-bundle.mjs:43` 读取 `ts.ScriptTarget.ES2022` 时抛 TypeError，当前安装的 TypeScript API 与脚本假设不一致。

另有重要测试设施问题：超时工作进程退出后，4 组 uvicorn launcher/child 共 8 个服务遗留。通过它们的 cwd、ATLAS_DATA_DIR 和 PYTEST_CURRENT_TEST 确认来自本次审查后已清理。测试夹具应保证超时后整个子进程树退出。

审查中一次使用反斜杠 CLI 临时路径的测试尝试被 rtk 路径转义破坏，产生大量 FileNotFoundError；该轮已排除，报告没有将其计作产品缺陷。另一个“非 Git 临时目录”断言把临时目录放在本 Git 仓库内部，Git 会向上发现仓库，也不能直接定性为 collect_diff 缺陷。

建议：先修夹具与隔离，再恢复默认测试命令完整可结束的能力；安全、取消、用量和事件协议的测试必须走当前实际调用链。未恢复门禁前，绿色构建不能代表行为回归被可靠覆盖。

### A10 · P2：运行依赖检查把开发态的可用 Node 判为全局阻断

`/api/runtime/dependency-check` 显示系统 Node v24.18.1 可用、source=system，MCP runtime 可用且已有 3 个连接；全局 blocker 同时报告 bundled Node executable missing。`core/atlas/api/tools_router.py:317` 只检查 bundled 状态，没有根据当前模式接受已解析成功的系统运行时。

建议：开发态按实际解析出的 Node/npm/npx 判断；打包态再强制 bundled 完整性。验证同一份诊断的 available、source、blocking_reason 与全局 blockers 自洽，同时保留真正缺失运行时的阻断。

### A11 · P2：集成页加载慢且中间状态误导

真实 `/api/integrations` 探查等待超过 10 秒，健康接口同期可在毫秒级返回。`frontend/src/renderer/pages/IntegrationPanel.tsx:52` 起打开页面就刷新，缺少请求期限/AbortController，载入前以 items.length 显示 0。`core/atlas/runtime/capability_bus.py:66` 起串行执行命令版本/认证检查，单项允许等待数秒，多项累积。

这里的 integration registry 与 agent tool/capability registry 是不同对象；不能把 agent 工具数与页面集成数直接对比，报告未这样计数。

建议：先显示缓存与明确的加载态，设置总刷新期限；独立外部探针并发且各自限时，返回部分结果和失败原因。验证慢或挂起 CLI 不会让整个面板长期显示 0 或一直 busy。

### A12 · P2：运行记录与事件缺少内存生命周期

`core/atlas/api/runtime.py:50` 保存完整 events；`:127` 用字典持有 runs；`:182` 启动读取全部历史 runtime_runs；`:209` 留在内存中。已完成 run 没有对应的上限或淘汰路径。前端 `useAtlasStore.ts` 的 runs、artifacts 等也缺少完整结束清理，removeRun 没有常规调用方。

前端单 run 的 runtimeEvents 已有 800 上限，消息缓存也有 LRU，所以不能概括成“所有事件和消息都无限增长”。本项针对未受限的后端完整事件与 run 集合，并未做长期堆内存压测，也没有虚构泄漏速率。

建议：终态 run 只保留有界摘要，事件回放从磁盘分页读取；活跃和近期 run 设容量/时间边界。验证多轮大工具输出后驻留集合可回落，并保留旧 run 查询与重连回放功能。

### A13 · P3：Electron 测试文件进入交付候选产物

`frontend/tsconfig.electron.json` 包含 `src/main/**/*.ts` 且没有排除测试；当前 `dist-electron/main` 中存在 backendProcess.python.test.js、backendProcess.test.js、electron.navigation.test.js、sourceUpdate.test.js。`frontend/package.json` 的打包 files 包含 `dist-electron/**`。

因此当前产物和包含规则会把测试代码纳入打包输入。没有重新制作安装包，所以不声称已经检查了一个新安装器内部。建议编译与打包均排除测试，验证候选 asar 文件清单不含测试及其辅助数据。

### A14 · P2：主渲染页缺少 Content Security Policy

运行页面无 CSP meta；`frontend/index.html` 没有主页面 CSP，主进程也未为该页面注入 CSP 响应头。工作区 preview 有自己的策略，不能替代主 renderer 的策略。

这是防护缺口，没有通过注入证明已有 XSS。已存在的 sandbox、contextIsolation、nodeIntegration=false、导航约束和可信 sender 检查应保留。建议为主页面建立与现有资源及启动脚本兼容的 CSP，并验证 Markdown、图表、字体和预览正常，同时非许可脚本被拒绝。

### A15 · P2：React 根部缺少错误边界

检查 `frontend/src/renderer/main.tsx` 和 renderer 组件，没有发现顶层 getDerivedStateFromError/componentDidCatch 等错误边界；代码块中出现的 ErrorBoundary 字样属于预览/字符串逻辑，不能算应用恢复机制。

本次没有故意向前台注入崩溃，因此没有“已复现全白屏”的证据。风险是单一组件抛错可能把用户留在不可恢复的界面。建议在根部及高风险扩展区域提供可恢复边界、诊断入口，并在隔离环境注入组件异常验证聊天数据和恢复操作保留。

### A16 · P2：登记能力与实际可用能力存在配置缺口

当前依赖诊断中，arxiv、blocked-page-recovery、competitor-news-monitor 依赖的 brave-search 未启用，缺少 BRAVE_API_KEY；pdf 缺 pdfplumber；telegram-integration 缺 telethon、pysocks、qrcode。当前启动日志还报告一项无效技能 metadata 被跳过，以及已找到 pwsh 但缺少 PowerShellEditorServices bundle。

这些是具体技能/语言服务的可用性问题，不代表所有网页搜索、PDF 或 Telegram 路径都不可用；实际 web.search/web.fetch 仍在工具目录。健康页的 skills=ready 表示管理组件启动成功，不能代替逐技能可用性。

建议：按实际使用需求补齐依赖或明确停用，页面直接显示“已登记但不可用”的原因。补齐外部密钥和登录需要真实账户条件，本次没有代填密钥、安装组件或发送外部消息。

## 真实运行的可追溯记录

测试会话：`76d90d3c-74e9-4e3a-a410-42d5b7e07d2f`，标题以 `[Atlas全面审查 2026-10-15，只读测试会话]` 开头。

1. Run `c3cef1d3-27b8-4c93-bf41-dd0c90b7cf15`：08:05:58.748981Z 开始；08:06:13.352521Z 工具成功返回 package.json；08:06:13.672499Z 再次产生同 call id 的完成事件；08:06:13.968380Z 继续调用模型；08:07:59.015848Z 取消。未获得最终回答，不记为聊天成功。
2. Run `958a40b9-5406-4ee9-abff-74c84cab2410`：仅请求固定文字、不调用工具；经历 3 次连接重试后完成并持久化 `ATLAS_AUDIT_OK`，没有文件变更。原始用量与完成汇总的缓存字段不一致。

原始工具事件：[live-run-events.json](/D:/Atlas/.tmp/audit-20261015/live-run-events.json)。实际取消状态截图：[live-cancelled.png](/D:/Atlas/.tmp/audit-20261015/live-cancelled.png)。脱敏汇总含第二次 run 的事件、重试记录、API 状态、数据库检查、依赖对照和失败分类：[evidence-summary.json](/D:/Atlas/.tmp/audit-20261015/evidence-summary.json)。

当前启动日志中没有复现历史日志里的 memory_reflector.idle_cycle_error 或 startup.component_failed；历史错误没有被冒充成当前故障。当前健康页返回 ok，11 个组件 ready；这与上述细粒度问题可以同时成立。

## 正向结果与边界

已确认：主页面没有崩溃；真实文件读取成功；最小模型对话最终成功；实际停止路径可到达 cancelled；前端适配器关于重连去重、同一 run 恢复等相应用例通过；8 个数据库 quick_check 通过；类型检查与当前依赖下构建通过；Python 依赖一致性检查通过；外部 Origin/null Origin 被拒绝，允许的开发 Origin 可用。Electron IPC 入口已有可信 sender 校验，没有沿用旧报告“7 个入口缺失校验”的结论。

未确认/未执行：干净安装后的构建、新安装器、真实升级/回滚/卸载、重启后恢复、托盘/登录启动、长期内存与 CPU 压测、所有供应商/模型、完整外部账户操作、真实 Git push/PR、通知与渠道发信、破坏性文件工具、计算机控制全面回归、备份恢复演练，以及所有页面在不同分辨率和输入方式下的交互。npm audit 因 TLS 失败没有形成漏洞结论；后端测试因超时与调度异常没有完整结束。审查没有为了验证这些操作而打断正在使用的桌面或对外写入。

本报告覆盖了全项目的主要系统面和真实运行链，但不构成每条功能路径都已通过的保证。没有发现当前数据库已损坏、任意远程代码执行或所有聊天必然卡死的证据。

## 建议修复顺序

1. 先修模型请求的期限、重试状态和取消回收（A01/A02），一起验证停止按钮在断连、停流和重试期间都有效。
2. 修事件生命周期和用量字段（A03/A04），用本次真实事件作回归样例。
3. 移除后端异步路由中的阻塞外部调用（A05），再验证并发健康请求和取消。
4. 处理 SQLite 实际运行库与依赖锁一致性（A06/A08），在隔离干净安装中完成验证。
5. 恢复测试隔离和门禁（A09），随后修诊断、加载态、凭据边界、资源生命周期、打包和恢复防护（其余项）。

## 复核入口

- 隔离探针：`D:/Atlas/core/.venv/Scripts/python.exe D:/Atlas/.tmp/audit-20261015/controlled_probes.py`。只使用假流/假子进程，不推送、不联网。
- 数据只读检查：`D:/Atlas/core/.venv/Scripts/python.exe D:/Atlas/.tmp/audit-20261015/inspect_readonly.py databases`。
- 后端原始 JUnit：[backend-isolated.xml](/D:/Atlas/.tmp/audit-20261015/backend-isolated.xml)。该文件保留未完成执行的结果，不能作为全套通过证明。
- 前端原始结果：[frontend-tests.json](/D:/Atlas/.tmp/audit-20261015/frontend-tests.json)。
- adapter 原始结果：[adapter-tests.json](/D:/Atlas/.tmp/audit-20261015/adapter-tests.json)，含 staging 重复收集，需按上文区分。
- 构建输出只在 `D:/Atlas/.tmp/audit-20261015/renderer-build` 与 `main-build`，没有部署到当前前台。

临时证据目录未纳入版本控制；如需长期保留，应连同本报告保存脱敏证据，而不要提交用户配置、密钥或全部运行日志。
