# ATLAS-C6-CODING-POLISH 结果

- 分支:`main`(直接施工,契约冻结 + 8 个子代理并行/串行)
- 执行:ZCode(GLM-5.3-Flash),2026-10-03
- 契约:`_tmp/c6-contract.md`(施工前冻结,含集成期决策 D1/D1(v2)/D2 记录)
- 说明:子代理统一用 general-purpose 类型(环境插件 agent-model-router 硬性拦截 Explore 且 router 定义需新会话才能生成;自主运行模式无法走人工选模型弹窗)

## 一、T8:LSP 核心接真实写/编辑链和 UI — ✔ 完成

**不重做 LSP core**(`core/atlas/lsp/**` C6A 产物零改动)。接线点:

| 接线点 | 文件 | 说明 |
| --- | --- | --- |
| native 写路径 seam | `core/atlas/engine/tool_registry.py`(write_file/patch 分支) | 调 Hermes 原生 handler 前读 pre_content + `snapshot_baseline`;成功后读 post、`report_after_edit` 把「本次编辑引入的诊断」中文块拼进工具结果 |
| 桥接模块 | `core/atlas/engine/lsp_bridge.py`(新) | `lsp_applicable / snapshot_before_write / report_after_edit`;所有异常吞掉,绝不拖垮写操作;发 `lsp.diagnostics` 队列事件(count==0 不发,≤20 条) |
| 双激活钝化 | `lsp_bridge.py` | **核实发现 Hermes 自带 `agent.lsp` 在本 venv 默认开启且会自动装 server**(editable 安装、DEFAULT_CONFIG lsp.enabled=true)——把 `agent.lsp.get_service` 替换为 None 返回函数,fork 零改动,只留 `atlas.lsp` 一个服务;E2E 断言工具结果含中文块、不含 Hermes 英文块 |
| WS 透传 | `core/atlas/server.py` | `lsp.diagnostics` 队列事件同名上 wire |
| 改动面板 | `shell/panels/ChangesPanel.tsx` + `GET /api/runs/{id}/diagnostics` | 每文件「N 个问题」徽标(>0 才显示)+ 可展开诊断列表(复用 `components/diagnostics.tsx`) |
| 时间线 | `timeline.ts` + `ConversationActivity.tsx` | 轻量通知「发现 N 个新问题 · 文件名」,可展开 severity/行号/消息 |
| worktree 释放 | `DELETE /api/conversations/{id}/worktree` | remove 后 best-effort `atlas.lsp.release_workspace` |
| 设置页 | `LspStatusSection.tsx` + `GET /api/lsp/status` | 逐 server 探测:绿点已就绪 / 灰点未安装 + 中文安装提示 |
| SSH/远程 | 沿用 `ssh://` 门控 | 不启动本机 LSP |
| 配置 | `config/atlas.example.toml` | 带中文注释的 `[lsp]` 示例表 |

语义验收(fake LSP E2E,`test_c6_lsp_wiring.py` 10 条 + `test_c6_lsp_e2e.py` WS 全链路):干净 → 编辑引入错误 → 工具结果出现新增诊断 + 事件 count==1 → 修复 → 报告空、无事件;原错误仅移动行号不算新增;LSP 不可用时写文件照常成功;patch 与 write_file 同链。

## 二、P1:/init — ✔ 完成

- 后端 `core/atlas/commands/init.py`(新):确定性扫描(语言/包管理器/构建·测试·lint·typecheck 命令/入口,全部带来源,有界 ≤5000 文件)+ 生成精炼 AGENTS.md 提案。移植 Hermes `hermes_cli/init_command.py` 质量标准(<100 行、只写核实过的命令)与合并纪律:已有文件保留人工内容、只补/刷新 `<!-- atlas:init managed begin/end -->` 托管区段(参考 `external_import._merge_markdown` 思路,标记区段比段落 dedupe 更强地保证幂等);CRLF 保持。`POST /api/init/preview` 出 diff;`POST /api/init/apply` 带 `expected_existing` 竞态防护,不匹配拒绝(422 中文)。
- 前端:`/init` 进 `/` 菜单(store `runInit`)→ `InitDialog.tsx`:扫描摘要 chips + **复用 ChangesPanel 的 DiffView**(不造第二套)+ 空 diff 显示「已是最新,无需写入」;确认后才写。
- 幂等:二次运行提案==磁盘内容、diff 为空(`test_c6_init.py` 15 条覆盖:人工段保留/diff/apply/幂等/竞态拒绝/路由)。

## 三、P2:/review — ✔ 完成(与「让审查员检查」合并,不留两套)

- 后端 `core/atlas/review/engine.py`(新,771 行):移植 Hermes `agent/review_engine.py` 审查简报结构与派发形状(文件头注明来源 `@e287231`),吸收 Codex/OpenCode findings schema。`/review`、`/review branch <名>`、`/review commit <sha>`(容忍全角空格、可追加关注点)。
- **只读链(集成决策 D1/D1(v2))**:`_handle_run_start` 拦截 → `collect_diff`(git 只读子进程,working_tree/branch 三点 diff/commit show,2000 行截断)→ 换派发提示词 → 父运行强制 **read_only** + 定向 `tool_allow`。delegate_task 新增 `permission_mode` 参数(**只能更严**:rank 取 max(父, 定义, 调用));审查员子代理 `read_only` + 继承读工具 + `review_command`(只读验证命令:拒绝写模式/危险命令表、120s 超时、输出截断)。agent 只读门禁与 `hermes_policy` 写拦截对 **精确出现在 tool_allow** 的 delegate/review/submit 三工具放行(普通只读会话行为不变)→ 写操作结构性拒绝、**零审批卡**。
- findings:`submit_findings` 工具容错解析(findings JSON schema:file/line/range/severity(blocker|major|minor)/title/explanation/evidence/suggested_fix;非法条目丢弃)→ `review.findings` 事件(空数组也发)。
- tool_search 兼容(决策 D2):两个审查工具注册进 hermes `toolsets._HERMES_CORE_TOOLS`,否则被延迟桩挡住("Tool does not exist")。
- 前端:`ReviewFindingsCard.tsx`(severity chips、file:line、可展开 evidence/suggested_fix、逐条「打开文件/让 Atlas 修这一条」、整卡「全部发回对话修复/复制」,空结果显示「没有发现问题」);`/review` 进 `/` 菜单(带参数提示);原「让审查员检查」按钮改为发送 `/review`(同一入口)。
- 测试:`test_c6_review.py` 34 条(三种 scope fixture/schema 解析/review_command 拒绝写/submit 事件/只读回归/父→子→submit 流)+ `test_c6_main_chain.py`(见下)。

## 四、长会话性能 — ✔ 完成(实测数字)

实施:react-virtuoso 单实例虚拟化(历史+活动时间线合并,`MessageThread.tsx`)、`message.delta` ~12.5Hz 合批(`eventBuffer.ts`)、runtimeEvents O(n²) 累积修复 + `run.events` 800 条封顶(截断标记)、流式回复纯文本渲染完成后切 Markdown、`ConversationMessage` memo 化、消息**最新 100 条 + before_id 翻页**(修复了原来取最旧 100 条的 bug)、`conversationMessages` LRU≤10 会话、TimelineNav 改数据驱动。

**实测**(`frontend/scripts/bench/RESULTS.md`,隔离后端 + 2×2000 条会话 + 15KB 长输出,无头 Edge):

| 指标 | 目标 | 实测 |
| --- | --- | --- |
| 2000 条会话打开到可交互 | < 1s | **146–311ms** |
| 两个大对话间切换 | < 300ms | **50–347ms**(缓存后 50–210ms,冷切换偶发 250–350ms) |
| 流式(300 delta @~100Hz)帧间隔 | 无持续卡顿 | p50 **7–12ms** / p95 12–20ms / max 20–74ms |
| 上滚翻页 | 视口不跳 | firstItemIndex 锚定 ✓ |

## 五、主体 UX 最后一轮(14 项逐项)

| # | 区域 | 结论 |
| --- | --- | --- |
| 1 | 输入框 | **修 3 处**:连接状态不再被意图提示顶掉(CC 做法);新增已发送消息 ↑/↓ 历史召回(localStorage,最近 50;CC/Codex shell 做法);发送按钮不再抢焦点;附件 key 内容稳定 |
| 2 | 普通消息 | 无真实问题,未改 |
| 3 | 工具步骤/思考/子 Agent | 无真实问题,未改(失败步骤已自动展开;C6 新增子任务/审查卡片) |
| 4 | 改动 diff | 无真实问题,未改(本波已加诊断徽标) |
| 5 | 终端 | 无真实问题,未改 |
| 6 | 文件面板 | 无真实问题,未改 |
| 7 | 权限切换 | **修**:`/permissions` 与 cyclePermission 双份循环逻辑合一(单一事实来源) |
| 8 | 模型选择 | 无真实问题,未改 |
| 9 | 状态栏 | 无真实问题,未改 |
| 10 | / 菜单 | **修**:Palette 与斜杠菜单共用同一模糊打分器(`services/fuzzy.ts`;Codex palette 做法) |
| 11 | 设置页 | 无真实问题,未改(本波新增 LSP 状态卡) |
| 12 | 错误/重试/恢复 | **修(最大一项)**:`client.ts` 英文兜底全部改中文主文案 + `BackendError.detail` 保留原始英文,错误横幅加「详细信息」展开区(CC/ZCode 的「中文白话 + 原始错误进详情」) |
| 13 | 空状态 | **修**:`New conversation` 占位标题改「新对话」(store/adapter/App 多处) |
| 14 | 快捷键 | 无真实问题,未改(默认组合全带修饰键) |
| 附 | 旁问面板 | **修**:SidePane 每事件强拉到底 → 160px 跟底阈值(与主线程一致) |

三套主题零改动(只用既有 token);无新增动画;浅色方向与整体结构未动。

## 六、顺手修旧测试漂移 — ✔

`test_backend_parity_wave2.py::test_goal_replace_pause_resume` 仍按 C3R 前的 `goal=` kwarg 构造(直接 TypeError)。已按现产(only `action="goal"` + Hermes GoalManager 语义 + `server._run_scheduled_goal` 门禁)重写,单跑通过;未改生产实现。

## 七、E2E 主链(任务书 §7)

`core/tests/test_c6_main_chain.py`:fake-model + 隔离后端 + fake LSP,一条 WebSocket 主链:
代码 workspace(已提交基线)→ 编辑引入 `LSP_BUG` → `lsp.diagnostics` 事件(count==1)+ 工具结果中文块 → `/review` 拦截 → 真实 delegate 链路派只读审查员 → `review.findings`(1 条 blocker,结构合法)→ 普通消息修复 → 诊断清零且 0 条不刷事件。**passed**。

## 八、验证汇总(原文)

```
后端 focused:
  tests/test_c6_lsp_wiring.py + test_c6_lsp_e2e.py      → 11 passed
  tests/test_c6_init.py                                  → 15 passed
  tests/test_c6_review.py                                → 34 passed(+11 c1 回归)
  tests/test_c6_server_routes.py                         → 16 passed(+133 memory/c4 回归)
  tests/test_c6_main_chain.py(主链 E2E)                 → 1 passed
  集成回归(c6_* + c1_policy/child/lifecycle_subtask)     → 61–65 passed(D1v2 后终验 61)
后端全量(唯一一次,focused 全绿后):
  pytest -q --ignore=tests/test_computer_use.py          → 1290 passed, 9 skipped in 895.69s
  (9 skipped 含按规永久跳过的 test_computer_use)
前端四项:
  npx tsc -p tsconfig.renderer.json --noEmit             → 通过
  npx tsc -p tsconfig.electron.json --noEmit             → 通过
  npx vitest run                                         → 78 passed (13 files)
  npx vite build                                         → ✓ built in ~15s
backend-adapter vitest                                    → 17 passed
```

注意:全量 pytest 跑在 D1(v2)(review 只读链收紧)之前;该改动面由 focused 集成回归(c6_review/server_routes/c1_tool_policy/child_policy/lifecycle_subtask,61 passed)覆盖后复跑通过。

## 九、截图(`artifacts/screenshots/c6/`,均经目检)

| 文件 | 内容 |
| --- | --- |
| `1-chat-lsp.png` | 主聊天:写入步骤 + 「发现 1 个新问题 · demo.py」通知 + 完成 stats |
| `2-review.png` | 代码审查卡(阻断 1/主要 0/次要 0、demo.py:3 finding、全部发回/复制)+ 派子任务步骤 |
| `3-changes.png` | 改动面板:demo.py diff + 「1 个问题」徽标 + 「LSP 诊断(当前共 1 个)」3:5 T999 |
| `4-terminal.png` | 终端(工作目录 PowerShell) |
| `5-settings.png` | 设置·高级:语言服务(LSP)状态卡(fake 已就绪/其他未安装+中文提示) |
| `6-long-conversation.png` | 2000 条会话(最新一页 1996–1999 + TimelineNav 导航点) |

复现:`node scripts/shots/c6.mjs`(隔离后端 + 内容路由 fake LLM + 无头 Edge,不触用户数据/端口)。

## 十、仍存在的真实缺口

1. **V4A 整仓 patch 的 LSP seam**:无顶层 path 的 V4A patch(Hermes `mode:"patch"`)不走诊断 seam(write_file/replace-patch 全覆盖);上游文件头场景低频,留待需要时补。
2. **打开文件不定位行**:Electron `openPath` 无行号通道,审查卡「打开文件」只打开文件 + 行号内联提示;需要 FilesPanel 行锚点支持。
3. **恢复滚动存档后 Virtuoso `startReached` 偶发不触发一次自动翻页**(再滚即恢复;显式「载入更早的消息」按钮始终可用)。
4. **冷切换偶发 250–350ms** 略超 300ms 目标(首次取数);缓存后稳定达标。
5. **`test_computer_use.py` 按规永久跳过**;真实 server smoke(pyright 等)本机未装、按「不自动安装」跳过,缺失提示路径已测。
6. dev-server 流式基准依赖 5173/4173(OriginGuard 信任来源),端口占用时需腾出。

## 十一、CORE-PARITY 状态

C6 负责行全部 ✔:T8(编辑后诊断)、P1(/init)、P2(/review)已按实测写入 `docs/plan/CORE-PARITY.md`(提交号齐全);I5 备注 `/init` `/review` 落地;`docs/PARITY.md` F118/F173 同步;VENDORED 登记 init_command/review_engine/lsp-seam 三个移植。
