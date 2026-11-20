# Atlas / DSH 全功能、全组件、原子行为对齐与超越执行计划

日期：2026-11-17。本文续接 `tasks/dsh-parity/BEYOND-DSH-CODEX-MANDATE.md`，不撤销其中任何保护边界。旧 2026-11-13 foundations 计划的“明确不做”不是本目标的范围限制。

**Goal:** 对固定 DSH 版本中所有可识别功能、组件、接口、配置、生命周期和协作行为建立可追溯原子账本，逐条实现 Atlas 对等能力并以真实、重复、同条件实验验证具体优势，不用大模块、包数或旧 135 项替代完整验收。

**Architecture:** 保持 Electron/React、FastAPI、Atlas async kernel 和现有持久化/服务组合根；先从 DSH 构建、注册、配置、协议与桌面入口构建来源全集，再追实现与消费者拆出原子行为及组件协作边。差距进入带依赖的滚动实施队列，沿 Atlas 现有生产接缝修复，模型历史、审计、SDK 和 UI 使用一致的身份/状态契约；账本和报告是证据索引，不替代产品实现。

**Tech Stack:** Python 3.11+、SQLite/SessionDB、FastAPI、asyncio/AsyncSSH、TypeScript/React/Electron、pytest、Vitest、Playwright CDP。外部 DSH 源只读，不运行其安装/构建脚本来获取信任。

**Work Scope:** 固定 DSH `D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness` commit `d743267388641bc76f17c45ce8b4c231aed1d32c`；Atlas `D:/Atlas`，当前 wave3/HEAD `060071ab2ecf86d41cab90e98160183ce126bc69` 加既有工作树快照。覆盖源码构建内与可配置启用的能力、组件、插件、协议方法、schema、工具、模型适配、配置默认/更新、权限、执行环境、持久化、事件、UI、平台与组合；测试专用/开发专用/不可达代码也必须归类，不能静默丢弃。私有服务区分功能等价、线协议兼容和服务授权；无协议/权限时保留未满足项，不仿冒成功、不上传真实会话。

生产代码由**原 Codex Desktop GPT-6 Luna 高会话经 CDP**实施；主控负责计划、只读检查、独立验证与证据。只读研究员不得接管生产。用户已要求“那就做，不要停下来，当个plan”，因此普通可逆开发/阶段推进不再等“继续”；仅真实权限、破坏性或对外动作需要新的授权。无 POSIX target、真实模型认证失败或私有服务权限时记录 BLOCKED 并立即转可执行原子项，不停止整个工程，也不将阻塞改成 CLOSED。

## 不变边界

- 不 reset/clean/stash、恢复别人的文件或整理旧 dirty tree；记录本批前后 hash/diff，只归属自身增量。禁止 commit/push。
- 不改 `data/memory/**`、不放松 `origin_guard`，不读取/复制凭据，不打印 raw 配置/headers/key 片段或 hash；配置返回须过 secrets_store.scrub。
- 不占用/重启 8765 用户后端，不改模型/账号/网关/全局配置；live 用独立端口、临时 data root、严格预算与 PID+creation-time 所有权。
- 同时最多两个实施 worker；本计划默认只用原 Luna 一个。主控与 Luna 不抢写同一生产文件；分支/worktree 不共享 stash。
- 新服务/路由接 AppServices/lifespan/include_router；桌面事件同批更新三真源；run_drive 长函数增删后 AST 验父链/层级。
- 不削弱测试，不删除失败证据，不用 runtime mock/空壳/忽略异常替代所需能力，不减少现有流式/权限/恢复语义换取绿测。

## 四阶段与滚动执行

1. **P1 全集与首个真实修复：** Task 1–2。交付可审计来源清单/账本机制，同时修 OLDNEW 成功尝试隔离，不能只盘点。
2. **P2 引擎、状态与协议：** Task 3–4。SDK durable 入队/恢复、可恢复 retry 决定、图像 occurrence；已修动态指令/web/上下文补遗漏契约而非重写。
3. **P3 执行、生态、桌面和剩余原子队列：** Task 5–7。远端环境、sandbox、插件、权限、UI及新发现能力全部进入依赖批次。
4. **P4 全链与超越验收：** Task 8–9。全量回归/真机真模型/受控配对/遗漏复核；失败发现回流对应阶段。

阶段是路由，不是工作量上限。下文 `Dependencies` 仅表示**实施产物可用依赖**，不是等待上游整项验收通过；队列分别保存 `implementation_dependencies`、`verification_dependencies`、`global_completion_gates`。Task 1 的账本schema和审计器、Task 2 的attempt事件契约、Task 3 的来源/身份契约、Task 4 的媒体投影契约是下游写同接缝的实施前置；Task 5 的目标lane登记和fail-closed接口产物可用后即可开始Task 6，**不等POSIX/其他平台验证**；Task 6的来源/consumer矩阵登记后即可开始Task 7，**不等私服或插件所有lane通过**；Task 7的来源/比较单元队列产物可用后即可开始Task 8安全改造和已满足实现前置的比较，**不等全部parity**；Task 9可先做collection和已有lane复核，但裁定完成必须全部验收前置满足。具体batch只在其声明的实施产物就绪、相关共享writer前批已释放文件且受影响契约测试通过时ready；与受阻lane无依赖的批次继续。共享文件按原Luna单writer串行，不基于某项BLOCKED而跳过未完成接口。已交付产物不把上游任务状态改成done，未完成验收始终OPEN/BLOCKED并阻止全局完成。

下列任务不是“只做这九项”：Task 1/7 发现的每个新原子行为必须有独立实施批次。每个批次落盘 `batch_id`、原子 ID、确切 repo-relative Files、依赖、正常/异常/组合验收、命令和回滚边界，再实施；不能在文件路径尚未知时假称预先批准了所有修改。批次结束立即取下一个 ready 项；只有用户打断、真实授权边界或全局完成门槛满足才停。每个新批次更新自己的明确文件清单和测试，不以本主计划的已知路径列表限制来源全集。

## 原子账本契约

Task 1 创建以下可机器校验数据，后续任务只更新既有数据，不另开互不对账清单：

- `source-index.json`：DSH commit、文件 digest、component_id、package manifest/exports、构建/注册/配置/协议/UI来源，include/dependency/import边、启用条件、分类、发现父来源；动态加载/生成schema不能解析则显式 obligation。
- `atomic-capabilities.jsonl`：稳定 atomic_id；component_id；DSH文件/symbol/实现及consumer引用；输入/输出/schema/default；触发/前后状态；错误/取消/超时/重试/并发/权限/平台/持久恢复；Atlas文件/symbol/生产入口；test/live receipt；依赖；差距；验证快照；blocker及解除所需权限；每维度的对等/优势结果。
- `interaction-edges.jsonl`：provider→consumer、资源owner、事件/协议/数据、作用域/平台、排序和失效条件、正常+异常组合验收。单组件通过不等于边通过。
- `batch-queue.jsonl`：原子/协作边 ID、所属阶段、优先级、依赖、ready/active/blocked/done、确切批次计划路径及证据路径。
- `completion.json`：按实现、接线、测试、真实运行、协议、私服授权、对等、超越分别统计；禁止把任何 UNKNOWN/BLOCKED/UNVERIFIED/FAKE_ONLY 算完成。

原子行不可写成“支持插件”这种多行为大包。一个行应能由一项明确行为断言判定，例如“活动session入队在持久化成功后返回稳定receipt且重发不重复执行”。不适用字段须有源码证据与原因，不能空字符串填充；“文件已建/接口同名/单测通过”不构成行为对等。实现状态和证据等级分离，允许实现完但真实运行未验。

### 来源完整性校验

- 索引所有 package.json、exports、Cordis 配置/preset、schema、工具/服务/client catalog、SDK 请求/通知 map、桌面 IPC/host protocol/renderer modules与平台分支；逐一追实际实现与消费者。以固定源码自行发现，不把 52/331 硬编码成验收值。
- 实际入口包括 DSH `scripts/cordis-config-files.ts`、`scripts/verify-cordis-config.ts`、`scripts/gen-{official-bundle,config,cordis,client,tool}-catalog.ts`，`packages/boot/app-boot/src/{index,official-bundle-packages}.ts`，`packages/bundle/web-app/package.json`，`packages/sdk/protocol/src/types.ts`，`packages/typert/registry/src/service.ts`，`packages/client/modules/src/client/manifest.ts`，`apps/desktop/src/{main,host-process,core-package-set,host-protocol}.ts`。读取生成器实现而非盲执行；运行时计算schema不能静态解析就保留未解析项并补受控验证。
- 每个发现的组件至少有行为行或具体 non-runtime 分类；每个注册/配置/协议/UI入口有组件/原子引用；每个引用存在、hash可核实、不能悬空。所有源文件必须归类到实现、测试、生成、资源、文档、vendor/development等有理由的类型；非代码资源也核对其消费者。
- `source-index.json` 内含逐来源单元的 **semantic_coverage** 表，不能止于文件/组件分类：接口/export方法、协议请求/通知、配置/schema每个字段及default/验证/热更新、生命周期每个迁移及异常分支、平台条件分支、生产者—消费者/资源释放边分别给稳定unit_id、文件symbol/range/digest，逐一映射一个或多个atomic/interaction ID或源码支持的排除理由。解析器不理解的动态表达式/闭包/配置组合留UNRESOLVED；人工逐单元读实现和consumer签收，抽查只作为独立复核，不替代逐单元覆盖。任何未解释单元阻止来源闭合。
- 新增/删除/改名输入由digest差异使旧证据失效；fixture必须覆盖**既有组件内部增加方法/配置默认/错误或平台分支但不增加包或入口**，未补atomic映射时check失败。人工独立抽查至少覆盖每个来源类型和每个组件族，校验机器未把“发现文件”冒充“解释语义”。
- 即使所有已录入行 PASS，只要源面未分类、动态未解析、组件无行为、协议无消费者或未覆盖平台 obligation 非零，就不得宣布全集封闭。

## Verification Strategy

Level: **e2e + integration + test-suite**，每项单独标证据级别。先本地确定性测试，再真实进程/桌面，最后获准真实模型/目标机；不把三个级别互相替代。

命令模板（唯一 basetemp 与日志由监督器生成，不复用历史临时目录）：

- `python core/scripts/dsh_capability_audit.py --source D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness --ledger tasks/dsh-parity/atomic --check`。
- core目录：`python -m pytest -q -p no:cacheprovider -o addopts= tests/test_dsh_capability_audit.py tests/test_retry_attempt_isolation.py tests/test_kernel_recovery.py tests/test_atlas_runtime_e2e.py tests/test_event_contract.py --timeout=60 --tb=short --basetemp <unique>`。
- SDK目录：`python -m pytest -q -p no:cacheprovider -c ../../core/pyproject.toml tests/test_app_server.py --basetemp <unique>`。
- `npm --prefix frontend test`，`npm --prefix frontend run test:adapter`，`npm --prefix frontend run test:preload`，`npm exec -- tsc --noEmit -p frontend/tsconfig.renderer.json`，`git diff --check`。
- Task 9 全量执行：先 `pytest --collect-only -q -o addopts=` 保存当前全部 nodeid；自动将 unit/integration 按稳定 nodeid、每片最多30节点分片，每测试60秒、每片300秒外部监督，失败/超时递归缩到节点诊断。带显式live/外部服务的节点不自动执行，归入需授权lane，不能静默删掉。frontend全 suite 可按 `--shard=1/4` 至 `4/4` 等价并集执行；SDK/adapter/preload另列。收集数与执行/跳过/阻塞/失败数逐项对账，不同源码版本的绿数不能累计成全绿。

Task 1 实现有界runner：外层deadline、stdout/stderr文件、PID+creation-time仅清自己、pytest输出完继续核实process退出；失败日志不经tail截断。新pytest标unit。任何 required node未执行/失败/泄漏时 completion保持未完成。旧失败必须保留基线与当前结果，不能以“没增加失败”替代最终可用性；无关旧故障可单列但不得写全套通过。

真实对测仅用用户既有获准route。**运行前**在comparison-protocol为每个拟宣称优势的atomic/interaction比较单元冻结：双方版本、初态/权限/模型/预算、任务产物质量硬断言、主指标/方向/最小实用改善量、统计方法/置信度、样本量/分层和停止规则。默认每个可量化单元10个AB/BA配对（每顺序5个）、冷热分层不混合；使用预注册seed的配对差异bootstrap 10000次、95%区间，latency或总可比token主指标的相对改善下界须超过5%，且双方质量硬断言均通过、Atlas失败数不高于DSH，方可标SUPERIOR。可靠性成功率用配对精确检验与95%区间，改善下界大于0；离散能力有无用预注册正负断言逐例比较，不强行套时延阈值；多个主指标须预注册并采用Holm校正，不得事后挑选。默认固定样本到齐才判定；只因安全/权限/预算/timeout提前停时写INCONCLUSIVE，不以中途有利结果早停。需替换默认阈值/统计方法的单元必须先冻结理由，运行后不可改判据，改了须新实验ID重跑。

失败计入分母；质量按产物断言，token区分cached/reasoning并保留原始usage，费用按确认费率，无费率写未测。样本数**逐比较单元**核对，不能把全局5组分给所有功能。覆盖所有已发现的可执行组件族和跨组件场景；每个atomic行挂行为及比较维度，不用总体平均掩盖某行退步。超越不宣称“所有模型所有任务永远胜出”；无指标、样本/置信度不足或不可比较只记未证优势，不能计入要求的超越门槛。

**全局超越二元门槛：**comparison-protocol在任何比较样本运行前冻结 `required_superiority_set`，必须非空，且为source-index中的**每个运行时组件至少选一个真实使用优势单元**，同时至少覆盖引擎/状态恢复、执行安全、扩展协议、桌面交互四类跨组件场景。选择依据是该组件主要用户用途/可靠性痛点，而非先跑出优势再选；不可比较的私服/平台组件保持优势未证，不因此删除或用其他强项抵消。开发/测试专用组件按其构建、诊断或测试用途设置对应单元或源码支持的不适用理由，不静默排除。总体“完成并超越”要求所有必要atomic/interaction对等门槛通过、来源obligation=0，且required集合**每个单元**满足预注册SUPERIOR；集合中任一个未证、失败或受阻则整体仍部分完成。新增组件/新发现缺口只允许扩展集合并新登记相应实验，不能事后缩减集合、改指标或删除失败样本来闭合；策略修订保留旧集合和失败并对受影响单元重新冻结/比较。

### Task 1: 建立来源全集、原子账本和有界验收工具
**Goal:** 建立可再生成并能检测遗漏、悬空证据与虚假完成的全来源原子账本，使每个新发现能力自动进入实施队列。
**Dependencies:** None
**Files:**
- Create: `core/scripts/dsh_capability_audit.py`
- Create: `core/scripts/dsh_validation_runner.py`
- Create: `core/tests/test_dsh_capability_audit.py`
- Create: `tasks/dsh-parity/atomic/source-index.json`
- Create: `tasks/dsh-parity/atomic/atomic-capabilities.jsonl`
- Create: `tasks/dsh-parity/atomic/interaction-edges.jsonl`
- Create: `tasks/dsh-parity/atomic/batch-queue.jsonl`
- Create: `tasks/dsh-parity/atomic/completion.json`
- Modify: `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`
**Acceptance Criteria:**
- [ ] 只读固定DSH源，索引可重复生成；变更manifest/注册/协议或新增未知组件的fixture使check失败并生成未解决obligation。
- [ ] semantic_coverage逐方法/配置字段及default/状态迁移与异常分支/平台分支/协作边关联atomic或源码排除理由；既有组件内新增行为但不新增入口/包时未映射check仍失败。
- [ ] 调度fixture中POSIX或私服lane为BLOCKED而其实施产物已可用时，无关SDK/UI批次仍ready，上游不变done且全局完成门禁保持失败；共享writer冲突依然不能并发。
- [ ] 每个原子/协作边具有稳定ID、DSH实现和消费者、Atlas生产入口或明确缺失、证据级别与下一批次；缺字段、孤立入口、假CLOSED或hash失效使check非零。
- [ ] 原135项和MAP01–06可追溯导入但不自动继承CLOSED；真实未知继续显示UNKNOWN。
- [ ] 有界runner测试证明超时、输出后挂活、PID复用不误杀、残留均被准确记录，未运行的测试不算PASS。
**Step 1:** 从上述DSH入口及全源文件分类建立source-index，记录来源闭包；对首批引擎/SDK/执行/插件/UI原子读到实现与consumer，其余未审条目标UNKNOWN而非推断通过。
**Step 2:** 实现schema、引用、digest、来源闭包和completion门禁；人工取每种来源与每个族至少一例反向核对，发现遗漏立即增加obligation。
**Step 3:** 用unit临时fixture运行审计器和runner回归，保存真实输出、退出码、快照与发现数量，随后立即实施Task 2。

### Task 2: 成功 attempt 隔离并贯通流式 UI、审计和重放
**Goal:** 失败模型尝试不得混入成功答案或执行工具，失败流可审计但UI和规范历史只提交成功尝试且保持正常续写能力。
**Dependencies:** Task 1
**Files:**
- Modify: `core/atlas/engine/kernel/model_call.py`
- Modify: `core/atlas/engine/kernel/loop.py`
- Modify: `core/atlas/api/run_drive.py`
- Modify: `core/atlas/api/event_names.py`
- Modify: `frontend/src/renderer/services/runtimeEvents.ts`
- Modify: `frontend/src/types/runtime.ts`
- Modify: `frontend/src/renderer/components/timeline.ts`
- Modify: `frontend/src/renderer/components/timelineProjection.ts`
- Modify: `frontend/src/renderer/components/SideChat.tsx`
- Modify: `core/atlas/tools/app_server.py`
- Modify: `sdk/python/atlas_sdk/app_server.py`
- Test: `sdk/python/tests/test_app_server.py`
- Create: `core/tests/test_retry_attempt_isolation.py`
- Test: `core/tests/test_kernel_recovery.py`
- Test: `core/tests/test_atlas_runtime_e2e.py`
- Test: `core/tests/test_event_contract.py`
- Test: `frontend/src/renderer/services/runtimeEvents.test.ts`
- Modify: `tasks/dsh-parity/atomic/atomic-capabilities.jsonl`
- Modify: `tasks/dsh-parity/atomic/batch-queue.jsonl`
**Acceptance Criteria:**
- [ ] OLD后断流→NEW成功，成功返回/DB重开/重放/UI最终文本均仅NEW；失败OLD有attempt审计且不再显示为成功内容。
- [ ] 相同前缀、fallback、完整/截断工具参数、等待取消全部有断言；失败工具未执行，总retry/fallback预算和正常max-output续写不退化。
- [ ] 新事件在三真源及normalizer/projection消费一致；app-server的session/event和最终text_parts、Python SDK的事件/最终返回/恢复重放同步映射attempt撤回与成功提交，OLD→NEW在所有出口均仅提交NEW。真实kernel fixture、SDK真实CLI和桌面演示均保存证据；未跑真实模型时不升级其证据等级。
**Step 1:** 先复现VERIFICATION07的实际失败流；为attempt分配身份/独立缓冲，定义成功提交及失败撤回/替换事件，保留失败审计。
**Step 2:** 沿model_call→kernel→run_drive→normalizer→timeline/projection/SideChat同步接线，AST检查长函数新增语句父链。
**Step 3:** 执行Verification Strategy定向组与UI事件重放，独立复核修前红/修后绿后更新原子行，不等其他族盘点结束。

### Task 3: Durable 用户入队、规范事件和可恢复 retry 决定
**Goal:** SDK入队在持久化成功后返回稳定身份并可在丢回执和重启后正确继续，同时retry决定与预算不因重启重置或提升用户角色。
**Dependencies:** Task 2
**Files:**
- Modify: `core/atlas/tools/app_server.py`
- Modify: `sdk/python/atlas_sdk/app_server.py`
- Modify: `core/atlas/engine/kernel/inbox.py`
- Modify: `core/atlas/engine/session_sync.py`
- Modify: `core/atlas/engine/kernel/loop.py`
- Modify: `core/atlas/engine/kernel/model_call.py`
- Test: `core/tests/test_app_server_sdk_lifecycle.py`
- Test: `core/tests/test_app_server_acp.py`
- Test: `sdk/python/tests/test_app_server.py`
- Create: `core/tests/test_durable_enqueue_retry.py`
- Modify: `tasks/dsh-parity/atomic/atomic-capabilities.jsonl`
- Modify: `tasks/dsh-parity/atomic/interaction-edges.jsonl`
**Acceptance Criteria:**
- [ ] 兼容现有同步prompt/cancel/approval，新增稳定enqueue receipt与幂等请求身份；持久化失败不回accepted，丢回执重发不重复执行。
- [ ] 用户prompt以user来源入队，不投影成developer；FIFO、双session、审批/input交错、事件序列和活动run边界有实际CLI子进程验证。
- [ ] receipt返回后存在独立于同步prompt的订阅生命周期，稳定session/request/run身份、游标回放/去重和pending approval/input恢复/失效；enqueue后不调用同步prompt也能审批完成，断连重开补放不重复执行、不重复授权，队列未注册不能静默丢事件。
- [ ] 重开恢复pending与retry schedule/start/预算/终止策略；失效wait/failed/settled区分，取消中等待不复活，日志写失败不伪报成功。
**Step 1:** 复用DurableInbox/SessionDB事件扩展可信来源、幂等键、规范序列和队列唤醒；先写后receipt，保持单session执行互斥但允许持久化后续输入。
**Step 2:** 将retry决策、等待启动及已消耗预算写规范事件；明确恢复是继续还是终止并断言，不能仅记录日志但不消费。
**Step 3:** 运行SDK双session协议测试和独立CLI重启/丢回执fixture，将未授权真实模型lane保留未验。

### Task 4: 图像 occurrence 卸载与上下文、指令、web 契约补齐
**Goal:** 实际图像预算超额按稳定消息与出现位置永久投影卸载，普通/摘要/重放一致，同时补齐已修上下文、动态指令及web路径的剩余行为契约。
**Dependencies:** Task 3
**Files:**
- Modify: `core/atlas/engine/session_sync.py`
- Modify: `core/atlas/engine/kernel/loop.py`
- Modify: `core/atlas/engine/kernel/model_call.py`
- Modify: `core/atlas/engine/agent/token_meter.py`
- Modify: `core/atlas/agent/project_instructions.py`
- Modify: `core/atlas/engine/atlas_runtime.py`
- Modify: `core/atlas/tools/web_extract.py`
- Modify: `core/atlas/websearch/service.py`
- Create: `core/tests/test_image_occurrence_offload.py`
- Test: `core/tests/test_atlas_session_sync.py`
- Test: `core/tests/test_route_image_pricing.py`
- Test: `core/tests/test_projects.py`
- Test: `core/tests/test_web_tools.py`
- Modify: `tasks/dsh-parity/atomic/atomic-capabilities.jsonl`
**Acceptance Criteria:**
- [ ] 重复blob只卸载指定occurrence；raw/base64/count/量化边界、普通和摘要先持久化再重试、失败/取消/无进展停止均有断言。
- [ ] 清缓存/重开/宽松route不使旧位置复活，新附同blob是新occurrence；卸载不读原blob且不删字节，无授权路径不暴露host路径；tool图像有规范持久表示和配对重放。
- [ ] 已修项目指令added/changed/removed和web同源/policy/status不重写；补不可读非删除、取消、来源/回放、供应商策略差异证据，缺口继续入队。
**Step 1:** 按MAP04复用附件存储和SessionDB，先补tool图像持久化，再记录稳定卸载决策与纯投影，接入route实际图像预算而非JSON长度估算。
**Step 2:** 普通/摘要/overflow恢复共用投影，保留原消息身份和blob；对现有动态指令/web仅按原子矩阵补缺。
**Step 3:** 用临时DB和fake provider验证边界，再在获准模型/桌面验证媒体与跨轮行为，不把附件持久化单独记为S10完成。

### Task 5: 执行世界与 sandbox 的真实目标闭环
**Goal:** 文件、进程、PTY、LSP、终端、child和sandbox在同authority、canonical workspace、权限及owner边界下运行，并完成各受支持平台的真实隔离验证。
**Dependencies:** Task 4
**Files:**
- Modify: `core/atlas/ssh.py`
- Modify: `core/atlas/engine/tools/environments/ssh.py`
- Modify: `core/atlas/sandbox.py`
- Modify: `core/atlas/api/run_drive.py`
- Modify: `core/atlas/api/tools_router.py`
- Modify: `core/atlas/agent/tool_node.py`
- Test: `core/tests/test_ssh_execution_world.py`
- Test: `core/tests/test_dsh_w7_sandbox.py`
- Test: `core/tests/test_lsp_ssh_transport.py`
- Test: `core/tests/test_lsp_ssh_world.py`
- Modify: `tasks/dsh-parity/atomic/atomic-capabilities.jsonl`
- Modify: `tasks/dsh-parity/atomic/interaction-edges.jsonl`
**Acceptance Criteria:**
- [ ] 现有SSH/LSP/terminal/child独立通过记录只在hash/契约未变时复用；链接越界、stale写入、authority漂移、启动丢回执、断连unknown、owner取消与release/reaper每条可追证据。
- [ ] Linux目标直接进程绝对路径写入验证read-only/workspace-write内外canary，网络/挂载/namespace符合声明；runner缺失/初始化失败无用户副作用且不回退裸argv。
- [ ] 所有DSH支持平台逐一实现或保留未满足；不能用Windows unsupported证据把Linux/macOS/Windows目标全标通过。未接shell/exec/git/资源限制行不关闭。
**Step 1:** 保留已有ssh-bwrap接线与20秒preflight deadline；对共享FS版本/原子提交/符号链接与进程sandbox分别补实现，不混称安全边界。
**Step 2:** 在明确授权POSIX目标执行真实side-effect；当前无目标则BLOCKED并继续Task 6/7可执行队列，不自行启动/安装系统服务、探测其他主机或换凭据。
**Step 3:** 逐consumer接shell/exec/git及平台/资源策略；要求的backend不可用就拒绝执行，完整lifespan/桌面用专用进程补证。

### Task 6: 插件、权限与桌面协作边闭环
**Goal:** 所有插件来源、依赖、安装更新卸载、权限审批及桌面事件操作都沿生产入口完成且与后台状态一致。
**Dependencies:** Task 5
**Files:**
- Modify: `core/atlas/plugins/runtime.py`
- Modify: `core/atlas/plugins/compatibility.py`
- Modify: `core/atlas/api/plugins_router.py`
- Modify: `core/atlas/api/service_registry.py`
- Modify: `core/atlas/server.py`
- Modify: `frontend/src/renderer/pages/ConsolePage.tsx`
- Test: `core/tests/test_plugin_install_operations.py`
- Test: `core/tests/test_plugin_compatibility.py`
- Test: `core/tests/test_service_registry.py`
- Test: `frontend/src/renderer/pages/ConsolePage.compatibility.test.tsx`
- Modify: `tasks/dsh-parity/atomic/atomic-capabilities.jsonl`
- Modify: `tasks/dsh-parity/atomic/interaction-edges.jsonl`
**Acceptance Criteria:**
- [ ] npm/Git/marketplace/local/ref/subdir来源、依赖版本/lockfile、逐包脚本审批、取消/并发/失败回滚/卸载每个行为独立有生产及UI证据，历史间歇失败不因一次重跑绿而删除。
- [ ] 权限收紧继承、信任变更、审批never/ask/always、工具暴露/withdrawal、服务依赖卸载异常都逐条核对；不支持的私服明确未满足。
- [ ] 专用后端+Electron检查安装创建未决、等待审批、取消、重连、重启回显与后台一致，相关自省无新unbound/hidden/shadowed，既有例外有源码和证据。
**Step 1:** 从MAP01与历史review/verification导入原子矩阵，先复核当前代码避免重复修已关闭bug，再定位未闭的Git间歇失败与真实MCP/UI生命周期。
**Step 2:** 保持来源事务链和信任门，沿既有服务/路由/UI生产消费者修缺口，重放每个状态迁移和异常。
**Step 3:** 专用服务只读自省、真实协议fixture与桌面操作合验，私有registry/服务授权缺失留BLOCKED并转下一ready项。

### Task 7: 全组件剩余原子差距滚动清零
**Goal:** 将来源全集中不属于已知批次的全部功能与协作差距转换为确切文件和二元验收的生产实施批次，不遗漏组件也不以预设清单封顶。
**Dependencies:** Task 6
**Files:**
- Modify: `core/scripts/dsh_capability_audit.py`
- Test: `core/tests/test_dsh_capability_audit.py`
- Modify: `tasks/dsh-parity/atomic/source-index.json`
- Modify: `tasks/dsh-parity/atomic/atomic-capabilities.jsonl`
- Modify: `tasks/dsh-parity/atomic/interaction-edges.jsonl`
- Modify: `tasks/dsh-parity/atomic/batch-queue.jsonl`
- Modify: `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`
**Acceptance Criteria:**
- [ ] 每个DSH组件/入口/平台/配置有行为或明确分类，每个未实现/未接线/未验原子均挂独立batch计划及依赖；不存在“misc已完成”聚合掩盖。
- [ ] 所有ready批次由原Luna滚动执行；每批在动手前声明确切Files/测试/状态契约并审查，涉及新接口同批迁移调用者；新增发现回流而不删scope。
- [ ] 全源归类与动态obligation为零且所有必要原子/协作边对等通过才可标parity；外部授权阻塞可以暂停具体项，不能满足本验收项。
**Step 1:** 按source-index逐族读取实现/consumer，覆盖模型/协议/搜索浏览器/技能/hooks/调度/记忆/工作流/协作/诊断/配置/打包启动及此前未命名族；族名仅导航不代替实际发现。
**Step 2:** 对每条未满足项创建 `tasks/dsh-parity/atomic/batches/<batch_id>.md`，包含原子ID、明确文件、依赖、正常/异常/组合验收与命令；该新文件由运行时分配稳定batch_id，不以目录名表示已实施。
**Step 3:** 从队列取ready批次交原Luna实现→定向验证→独立验收→更新证据；BLOCKED转其他ready，所有项满足之前不能交最终完成报告。

### Task 8: 同条件逐行为比较与可重复优势
**Goal:** 对已映射原子行为和跨组件任务给出可重复同条件比较结果，明确Atlas每项对等性、具体改进及代价，不用总体平均冒充全面超越。
**Dependencies:** Task 7
**Files:**
- Modify: `core/scripts/omni_bench.py`
- Modify: `core/scripts/omni_multiturn.py`
- Test: `core/tests/test_omni_bench.py`
- Create: `tasks/dsh-parity/atomic/comparison-protocol.md`
- Create: `tasks/dsh-parity/atomic/comparison-results.jsonl`
- Modify: `tasks/dsh-parity/atomic/completion.json`
**Acceptance Criteria:**
- [ ] live调用前通过benchmark安全batch：禁止读取/复制用户凭据文件、复制解析真实全配置或覆盖代理；越界fixture触发即拒绝启动，合法显式白名单route来源能以不落盘不打印密钥的方式使用既有获准模型；机制缺失只阻塞live lane。
- [ ] 比较前逐比较单元冻结任务/断言/预算/模型route/双方版本/初态、质量门槛、指标方向/最小改善量、统计/置信标准、样本数/停止规则；默认每单元10组AB/BA配对并按上文95%区间/5%实用阈值判定；冷/热、失败、质量、usage、费用按可比口径保留。
- [ ] 每个原子有行为结果和具体比较维度或有证据的不可比较原因；每个组件有对应真实场景，跨组件取消/断线/重启/压缩/长跑/媒体/审批均覆盖。
- [ ] 比较前冻结required_superiority_set，非空且每个运行时组件至少一个主要用途优势单元，并含四类跨组件场景；不事后缩减，集合每个单元均SUPERIOR才满足整体超越，任一未证/失败/BLOCKED保持整体部分完成。
- [ ] 没有样本、没有费率、认证失败、质量退步或区间不足以判优势均不标SUPERIOR；不保证所有未来模型/任务永远优胜，不把一个强项抵消另一缺失。
**Step 1:** 先建立benchmark安全原子batch再允许任何live：修复omni_bench.py现有用户凭据文件读取/注入（当前约246–266）、真实配置复制解析（约442–448）、代理固定覆盖（约55/260–263/490–493）及omni_multiturn启动复用；准确行号实施前复核。启动参数只接受隔离测试配置和运行时显式提供的获准route描述，秘密仅走正常已有provider内存解析，不另读/复制认证文件，不回显/落盘；现有API不足则live BLOCKED而不是用旧启动器。安全fixture监测对真实HOME/auth/config/DB的open、copy和proxy env改写，触发即失败，确认fixture/live专用配置不受误拒。安全通过后才读取隔离原始计量、保留失败样本/完整关闭证据。
**Step 2:** 按冻结协议运行短样本再扩长跑/故障注入，模型预算/超时触发即停止该lane；认证或外部权限失败不换账号/网关，不循环重试。
**Step 3:** 将每个结果回挂atomic/interaction，任何退步回流对应实施任务修复后在新快照重验；旧胜率不覆盖新代码。

### Task 9: Final Verification
**Goal:** 在同一受验版本完成来源遗漏检查、全部适用回归、真实桌面/模型/平台验证与逐项优势复核后才裁定整体完成。
**Dependencies:** Task 8
**Files:**
- Modify: `tasks/dsh-parity/atomic/completion.json`
- Create: `tasks/dsh-parity/atomic/final-verification.md`
- Modify: `tasks/dsh-parity/BEYOND-DSH-PROGRESS.md`
- Test: `core/tests/test_event_contract.py`
- Test: `core/tests/test_service_registry.py`
- Test: `sdk/python/tests/test_app_server.py`
**Acceptance Criteria:**
- [ ] Verification Strategy全部适用suite以collection/执行清单对账；失败/超时/未跑/残留为零，外部受阻lane不存在未满足硬验收，否则总状态不为完成。
- [ ] 所有source obligation=0，必要atomic/interaction具当前版本生产入口和正常/异常/组合真实证据；不存在UNKNOWN/BLOCKED/UNVERIFIED/FAKE_ONLY被算完成。
- [ ] 桌面真实使用、真实模型与授权目标平台各有独立receipt；预先冻结的非空required_superiority_set覆盖每个运行时组件及四类跨组件场景，集合所有单元均满足SUPERIOR，其他必要原子/协作边对等通过；任一优势未证不满足整体完成，不用135、包数或测试数字声称完成。
**Step 1:** 冻结工作树manifest，运行来源audit、全部backend/frontend/SDK/adapter/preload套件的有界分片并核实进程退出；检查AppServices/router/event三真源与AST。
**Step 2:** 独立验收实际桌面、模型、取消恢复、平台及公平比较，记录版本/命令/事件/文件产物；修订代码则使受影响证据失效并重验。
**Step 3:** 输出逐原子及全局结果：实现/接线/测试/真实运行/协议/私服授权/对等/超越分列。任一硬项未满足就报告部分完成和可继续队列，不给虚假百分比或CLOSED。

## Critic Responses

2026-11-17 第一轮普通三方意见均为ADVISORY_REVISE，全部采纳：

1. 来源完整性从组件/文件数量升级为semantic_coverage逐方法、配置字段/default、迁移/异常、平台分支、协作边的单元映射，并增加组件内部新增行为漏录fixture。
2. 实施产物依赖、验证lane和全局完成门禁分离；具体批次按真实产物与writer解锁，不因POSIX/私服BLOCKED卡无关队列，也不虚标上游done；增加调度fixture。
3. 比较按单元预注册质量/指标/方向/阈值/统计/样本/停止规则；给出默认10配对、95%区间、5%实用阈值和提前停止INCONCLUSIVE规则。
4. Task 2加入app-server/SDK attempt撤回/提交/最终结果/重放；Task 3加入不依赖同步prompt的订阅、游标、审批/input恢复与失效。
5. Task 8在live前增加明确benchmark安全batch，封住既有凭据文件/配置复制与代理覆盖；无合规route传递机制时仅阻塞live，不沿用不安全启动器。

## 规划审查与执行状态

本文件是用户要求的全目标滚动主计划与首批明确实施任务，不是功能已完成报告。当前宿主可见旧 `.glm-hammer/plan-seal.json`，未提供本轮认证runId/generation/journal；不得编造metadata或手写approved状态。采用独立可行性/接线/覆盖审阅提供普通评审意见，**不宣称 Forge certified PASS**；认证缺口不改变用户指定的原桌面生产通道与已授权工程目标。
