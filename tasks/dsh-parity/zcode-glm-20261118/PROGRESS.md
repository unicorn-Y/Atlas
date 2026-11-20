# ZCode · GLM-5.3-Flash 全量任务进度

主计划:`docs/glm-hammer/plans/2026-11-18-zcode-glm-full-dsh-atlas.md`
交付目录:`tasks/dsh-parity/zcode-glm-20261118/`(本批唯一可写目录,Atlas 仓库内)
外部工作区:`D:\ENGINE-V3-UPSTREAM-20261118\`(官方源检出@rc.4、下载包、脚本、agent-rows、diff 证据)

## 当前总量(2026-11-18,EXEC-06 后)

- **SOURCE-INVENTORY.tsv:36,536 条目 = 35,631 文件 + 905 目录**(五 carrier:git 21,071/npm 534/安装包外层 10/内包 8,785/runtime 6,136;git 来源=NUL 集合逐项相等;pending 清零)
- **BEHAVIORS 368 / INTERFACES 260 / ATLAS-MAP 368**;状态:**对齐已验 82 / 部分 205 / 缺失 81 / 待核 0 / 受阻 0**
- C 追加:F03 OVERLAY/RENDER/SETTINGS 15 行待核→定位(统一 context-menu 服务、行 toast、配额链、开发者工具开关、AppFrame 六席、拖拽矩形回放等缺口落 gap 列)
- 全表自动复验(`audit_tables.py`):**0 失败**(列宽/主键/外键/悬空/队列;明细 `evidence/table-audit-20261118.txt`)
- 测试三批 **83 全绿**(B 节 38+vitest 17+F07/F05 定向 28;真实 SDK 子进程+当前在途树)
- SUPERIORITY 11 行;ATTEMPTS.md 三场景自动化层完成

## ZC-DSH-EXEC-03(2026-11-18)

### A · 验收状态可核验化(完成)

- 116 条「对齐已验」逐条重查(`audit_atlas_map.py`):**保留 36**(本会话当前树锚点+真机/测试收据:tray:257、inbox:102/:110、session_handle:42、checkpoint 双点、projcache:506、price_surface_nodes:164、SchemaTooNew:186、compaction 0.8/0.16、OTel 双 span、hooks:781-821、rewind:82-90、多窗:576/:632、lsp_bridge:35-51、app_server:752-1137、core-package-set:40/:131/:170 等),**降级 80**(待对照标记/无验收级收据;明细 `evidence/atlas-map-audit-20261118.txt`);文件存在性检查 0 缺失。
- source_ids 规范化(`normalize_source_ids.py`):**721 条接 source_id 外键**(含行号剥离与 `{a,b}.ts` 花括号展开)+35 条目录锚点(DIR)+**0 悬空**(`evidence/source-id-linking-20261118.txt`)。
- 口径写准:**36,536 = 35,631 文件 + 905 目录**(BASELINE §1.1 已更新;内包目录按 7z 属性列 D.... 计)。
- 自动复验含 FK 区间展开(`id01..13`)与空格分隔;失败明细落 `evidence/table-audit-20261118.txt`(当前 0)。

### B · F02 54 通道逐条对照(完成)

- DESKTOP_IPC 34 主通道+platform 5+mandatory 3+update-dialog 3+welcome 9+剩余 3 = **54 行全部逐通道更新 ATLAS-MAP**(每行:DSH 调用方→handler→可观察结果 对 Atlas 真实入口)。
- 通道状态:**对齐已验 8**(file-save/boot/directory-pick/fullscreen:1104/windows-menu:1167/mandatory×3)/ **缺失 29** / **部分 16** / 待核 1(native-theme OS 镜像)。
- 真实缺口与最小实现(见各行 gap 列):剪贴板图片回读(main clipboard.readImage+preload+草稿路径)、快捷键持久化编辑(keybindings.json+revision CAS+广播+录制态)、原生拖出(webContents.startDrag+requestId)、device-info(os.release)、更新渠道 get/set/广播(settings 渠道字段+feed builder)、Windows 标题栏配色(canvas 采样)、welcome/onboarding 全流(大)。
- **实施候选登记 `F02-impl` = blocked-on-author**(接线点 electron.ts 为原作者在途文件;新模块可隔离但接线冲突,按纪律不并写)。回归设计已写入各行 gap(主进程 mock 测试+preload 接线断言)。

### C · F03/F01/F10(完成首轮)

- **F03 逐行升级 73 行**(PREVIEW 17→D16 对齐+office/excel/code/目录树缺口标注;SETTINGS 9 分节落点;RENDER/PAGE/ROUTE/OVERLAY/MARKDOWN/CONN/I18N/SHORTCUT/COMMAND 各归真实 Atlas 面;`对齐已验`需 D16/D17/D19/D22/D33/D7/D9 收据支撑)。
- **F10 契约清单**:B-F10-SYNC-01(`dsh_session_log` 公开契约:watermark/8MiB 排空/enabled 开关/重启用续传;**S26 口径更新:非"无契约"**)、B-F10-LIVESHARE-01(owner bundle+Relay+协议包;查看/受限写/fork 三控件 owner host 强制;Relay 服务端=观察边界)、B-F10-REMOTE-01(account/watch 条件面,待核);受阻清零(原 S26 受阻行改为缺失+可验收目标)。
- **F01 安装升级/迁移**:B-F01-CORE-PKG-VERIFY-01(sha512 核心包校验+lockfile 拒绝+升级=整包替换+versions.json;paths.ts 无显式迁移函数)→ Atlas 部分(D1 版本握手,无包校验面)。
- 受控测试:83 项 pytest/vitest 均为不依赖 omni_bench 私有配置的独立受控证据;同条件优势比较仍按 P4 冻结协议等安全 batch(QUEUE R2-bench-safety blocked-on-author)。

## ZC-DSH-WATCH-04(2026-11-18)

### 1 · 外键接线收口(完成)

- 根因:INTERFACES 的 source_ids 在第 6 列,旧脚本按第 7 列处理——BEHAVIORS 接上了、INTERFACES 整列漏掉。已按表定位列重跑(`normalize_source_ids.py` 重写:行号剥离、花括号展开、目录只认真实目录 carrier/前缀、扩展名缺失文件不再吞成目录)。
- 终态(审计器固化输出):**BEHAVIORS 有效=723/目录=37/待修=0/无效=0;INTERFACES 有效=465/目录=16/待修=0/无效=0;interface→capability→Atlas 断链=0**(`evidence/table-audit-20261118.txt` + `source-id-categories-20261118.txt`);723 中含后追加行(B-F10 README、B-F01 core-package-set 等)与 IF-WEB-STORE-08 路径修正(ui-chat/src 少一层)。

### 2 · F09/F08 入口全集 + P1 对账(完成首轮)

- **F09 新增 4 行**:官方 bundle 目录全集(bundles.ts:37-80:RETIRED 2(schedule/agent-team-profile 于 rc.2 退役)/DEFAULT dsh-base/**OPTIONAL 16**(liveshare/forge/tool-worktree/cua/voice-input/chat-import 等)/**ON_DEMAND 2**(subagent-claude-code/codex)+离线生成目录 8 语言元数据);注册表双源(npmjs+npmmirror,registryPlan/attributeFailure);受管 MCP(McpServerManager extends TypertRemoteService,:193);技能七源阶梯(SkillSource:BUNDLED_SKILL_RANK=600+invocation policy)。
- **F08 新增 3 行**:AgentTeam 新址 packages/team(41 文件);CUA(computer-use+cua-bundle);office 文档族(document/office-kit+tool-office,与 runtime pythonPackages 呼应)。
- **P1 packages 262→496 行 18 族真实归类**(读子包 manifest 逐个:name 逐一确认;1 行 tsdown.worker.ts=根构建文件);inventory 处置写回。
- **F09B 定向测试:112 passed / 5 failed**(test_mcp_client.py 官方二进制 pin/config discovery 类;mcp_client.py 本身干净,疑环境依赖;失败明细已记录,基线比对待 P4 全量对账,不冒充全绿)。
- **F08 定向测试:73 passed / 4 failed**(SSH 执行世界 4 项;`core/atlas/ssh.py` 为原作者在途文件,不冒充全绿,基线比对待 P4;明细落 ATTEMPTS.md)。

### 3 · 隔离实施(ZC-EXEC-04-IMPL-1,done-in-worktree)

- **选定候选**:code 文件预览(B-F03-PREVIEW 缺口"code 预览为 Atlas 缺口";目标文件 documentPreviewRegistry.tsx 干净,WorkspaceFile.content 直达)。
- **隔离 worktree**:`D:\Atlas\.worktrees\zcode-exec04-preview`(分支 `zcode/exec04-code-preview`,基线 wave3@060071ab;node_modules 联结)。
- **改动**:3 文件 +90 行——新增 `codePreview.tsx`(30 扩展+行号渲染+MAX 2000 行+binary/空文件/截断显式守卫,不伪造内容)+registry 2 行注册+新测试 `codePreview.test.tsx`(3 用例:扩展家族/内容渲染/binary+截断)。
- **验证**:vitest **3 文件 10 测试全过**(registry 3+新 3+FilesPanel 消费者回归 4,exit 0);tsc renderer **0 错误**(exit 0)。
- **diff**:`evidence/zcode-exec04-code-preview.diff`;**不合回、不 push**,待主控验收;B-F03-PREVIEW 相关行 gap 已更新为"已实现待验收"。

### 4 · next entry(本批结束前)

1. 主控验收 IMPL-1 diff→合入主工作区后 B-F03-PREVIEW code 行升对齐已验。
2. F09B 5 失败基线比对(P4 全量对账时);F08 定向测试结果落 ATTEMPTS。
3. F05/F06/F07 "对照待批次"项(batch.ts:188 提交后重读分类、llm-retry durable 事件、bash-sandbox 底座)。
4. P4 冻结(等 omni_bench 安全 batch 解除)。

## ZC-DSH-WATCH-05(2026-11-18)

### 配对复跑(完成,结论改变定性)

- **MCP 3 项失败在干净 wave3@060071ab 同 nodeid 复现** → 基线/环境问题,非在途引入;且失败数在运行间漂移(5→3)。逐项根因:#1 在线 node manifest vs 过期 pin(网络);#2 'filesystem' 服务器本机未连(环境);#3 失败传播竞态(时序)。脱敏原文与 diff 见 `evidence/pair-mcp-failures-sanitized.txt`、`pair-failed-diff.txt`。
- **SSH/LSP world 4 项失败**:测试文件本身为在途未跟踪,干净树无对应 nodeid——配对结论即"仅在途树可观测",不归因(`evidence/pair-ssh-note.txt`)。
- **F05/F06/F07 配对批次**(7 文件,在途 20 败/45 过 vs 干净 3 败/51 过):**17 项仅在途失败**(SDK lifecycle 6 + ACP 9 + projects 2)= 原作者未提交改动引入的回归(涉及 app_server.py/kernel/projects 在途文件,受保护不动,上报主控);**3 项两树皆败**(session_sync fork/history,基线问题);仅干净败 0。清单=`evidence/pair2-inflight-failed.txt`、`pair2-clean-failed.txt`、`pair2-failed-diff.txt`。**→ EXEC-06 等价对照修正:17 项中 0 项代码回归;8 项基线存在项两树全过,9 项新增测试中 6 项为目标在途功能范围、3 项两树可移植;早前失败为环境/测试顺序污染(不可复现)。证据 `evidence/exec06-17fail-equivalence-20261118.txt`。**

### F05/F06/F07 深化(完成首轮)

- 新增 2 行:B-F06-RETRY-DURABLE-01(DSH `llm/retry`+`llm/retry-started` durable 事件 vs Atlas 仅 `attempt/failed`(session_sync.py:585)→ 部分,实施因 model_call.py 在途暂缓);B-F06-ATTACHMENT-01(DSH attachment-local 归一化/sharp/压缩管线 vs Atlas 原始 sha256 blob(S19)+D5 → 部分,session_sync.py 在途暂缓)。

### IMPL-2 · MCP 生命周期 fail-closed + 版本常量同步(done-in-worktree)

- worktree `zcode/exec05-mcp-status` 三处修复:① get_runtime_status 在 starting/connecting 期间 available=False(fail-closed);② `_startup_finished` 异常回填 state=failed+脱敏 blocking_reason(原缺陷:只记日志,状态永远 starting);③ `node_runtime.py` 常量同步部署真源 `frontend/node-runtime.json`(v24.21.0/sha256 158f7685…,原 v22.23.3 为**已提交的不同步**)+测试字面量改由常量派生(防漂移)。
- `test_mcp_client.py`:19 过/3 败 → **22 过/0 败(exit 0)**;此前"网络依赖"定性修正:第三个失败真因=已提交数据不同步,无网络访问。diff=`evidence/zcode-exec05-mcp-status.diff`(3 文件 +63/-12);运行记录 `impl2e-mcp-after.txt`;不合回不 push。
- 行级对照 2 项落行:B-F05-BATCH-01(batch.ts:109-124 逐段:三点 DSH 独有语义——exclusive 重分类跨 barrier 保留/abort 按 model order 提交/scheduler failure 降 step recovery)、B-F05-LIFECYCLE-01(turn/end reason=可序列化 cancel cause 拷贝+failure{message,code};Atlas 字段集逐字段对照待 F05)。

### WATCH-05 续(同轮追加)

- **IMPL-2 终态 22/22**:`node_runtime.py` 常量同步部署真源 `frontend/node-runtime.json`(v24.21.0/sha256 158f7685…)+测试字面量改由常量派生(防漂移);早前"网络依赖"定性**修正**为已提交数据不同步(测试无网络访问)。`test_mcp_client.py` 22 过/0 败(exit 0);diff 更新(3 文件 +63/-12)。
- **行级对照 4 项落行**:B-F05-BATCH-01(batch.ts:109-124:三点 DSH 独有——exclusive 重分类跨 barrier 保留/abort 按 model order 提交/scheduler failure 降 step recovery)、B-F05-LIFECYCLE-01(turn/end reason=可序列化 cancel cause+failure{message,code})、B-F05-REPEAT-01(stuck.py vs repeat-guard:Atlas 独有挥发字段指纹剔除+窗口化循环检测;DSH 独有可配阈值+装载期校验+通配过滤+提醒上限+source 标签)、B-F06-TOKEN-METER-01(四桶口径差异引用 BENCH-ANALYSIS 实测)。
- 记忆库已更新(WATCH-05 状态+工作流约定)。

### WATCH-05 续 2(F05-F04/F03/P1 残余复核,完成)

- **F05 「对照待批次」清零**:PIPELINE(pipeline.ts settlement 二分 post-result/final-result+executor 拒绝先于策略+correlation token+融合信号)、SANDBOX-ESC(ptc.ts:344-365 契约逐字段:description 非空/timeoutMs 门控/standingPolicy/approveEscalation subject:program/denied 指引)、JOBS(model cursor 消费语义:settle 保留未消费字节/首读裁 cap/readAt 不动 cursor)、SUBAGENT(persisted descriptor 校验:未知字段/逐 key 数组/version omit)——四行落具体差异为实施评估项。
- **SETTINGS 查表 bug 修复**(行号键误用族名查)→ 9 行落位;INPUT/BROWSER/PERM/IPC-31(matchMedia App.tsx:323)落位。
- **PYSDK 35 行逐方法映射**(对照 atlas_sdk 公开面,只读):3 对齐(start/initialize/harness-run)/15 部分/17 缺失(订阅族×5、set-working-directory×2、session-run(query)、respond 族、office×3、harness-client/finish-reason 等);SERVER 3 行按真 id(apply/schedule-restore/max-tokens)落位。
- **P1 收口证据**:`evidence/p1-packages-families-20261118.txt`(18 族 84 子包清单);**F03 残余证据**:`evidence/f03-residual-pending-20261118.txt`(待核逐前缀分解)。
- **终态:BEHAVIORS/ATLAS-MAP 368,状态 对齐已验 84 / 部分 197 / 待核 7 / 缺失 80;复验 0 失败**。剩余待核 7 行均有明确理由:4 行架构级候选(WEB-BOOT/RENDER-02/07/08:slot/boot/种子面)+user-question.cancelled(单项取消路径)+INPUT-03(已列 F02-impl)+REMOTE-01(行级契约待批次)。

## ZC-DSH-EXEC-06(2026-11-18)

### 1 · user-question.cancelled 发射/消费与 Atlas 取消路径(完成定位与验收冻结)

- **DSH 定性**:`user-question.cancelled` 不是 session event,而是 SDK JSON-RPC server→client 通知。协议 `packages/sdk/protocol/src/types.ts:51-57,194-195`;唯一发射点 `packages/sdk/server/src/user-questions.ts:34-57`(abort 监听器 `transport.notify('user-question.cancelled',{requestId,sessionId})`,写失败仅告警;`close()` 以 ASK_ABORTED 中止全部未决);消费者 `packages/sdk/client/src/client.ts:305-309`(按 requestId abort)与 `python/sdk/src/deepseek_harness/client.py:475-478,513-561`(置位问题线程取消 Event,迟到回答丢弃);语义 `packages/sdk/protocol/README.md:52,76`;测试 `packages/sdk/server/tests/user-questions.spec.ts:97-118,121-140`。
- **Atlas 实际路径**:desktop `run_drive.py:3522-3545` 发 `input.required` 后轮询 `cancel_event`,取消仅 raise CancelledError;`runtime_ws_router.py:186-190` 处理 `input.response` 且未命中静默跳过;`event_names.py:75` 无 `input.cancelled`。SDK/ACP `app_server.py:475-503` 发 `input/request`,`_wait_with_cancel:19-31` 取消后返回 None,`ask_user` 折叠成空字符串;durable `appserver.request` 置 `invalidated`(:187-228,:1576-1584);`input/response` 迟到报 -32602;但从不外发取消通知。
- **实测(当前树,私有 basetemp)**:pending 重连(input)/有 pending input 时 task cancel/进程重启失效 + desktop 问答 → **4 passed,exit 0**(命令与明细 `evidence/exec06-user-question-cancel-remoteaccess-20261118.txt` §C)。
- **差距与验收**:缺口 G1-G5(无协议级取消通知/取消语义丢失/桌面无问题级终态/无请求身份关联/durable 审计非 wire 契约)与二值验收 A-1/A-2/A-3 已冻结(evidence §B4);实施受 `app_server.py`/`run_drive.py` 在途归属限制,登记 blocked-on-author。
- **表更新**:ATLAS-MAP `B-F04-SDKPROT-user-question-cancelled-01` 待核→部分;BEHAVIORS 行补 TS/Python 消费方与测试锚点。

### 2 · remoteAccess 公开定义与 Atlas 对应面(完成定位)

- **DSH host 公开面**:`packages/api/remote-access/src/index.ts:125-377`(`registerPolicy`/`invalidate`/`decide`/`allows`/`snapshotFor`/`follow`),类型 `types.ts:89-146`(policy/binding/condition/grant/frame/denied details),快照键 `snapshot.ts:8`;执行侧强制 `gateway/src/index.ts:633,814-822`(deny→remote-access/denied;事件帧丢弃)与 `session-controller/src/index.ts:284,298,636,641`(逐项 allows 过滤);client `mount.ts:43-120`(source/whenAccess)。
- **Atlas 对应面**:`core/atlas/remote_access.py:38-89` 仅是短期 bearer 会话(sha256、TTL、revoke);`origin_guard.py:59-66` 令牌有效即放行全部 HTTP/WS(布尔闸);`api/remote_router.py:16-58` 远程页/start/status/stop/全部会话列表。无分资源 ACL、无 denied reason、无 snapshot/follow、无 whenAccess 条件面。
- **表更新**:BEHAVIORS `B-F10-REMOTE-01` 升级为完整 remoteAccess 能力(host+client,9 个 source_id);ATLAS-MAP 待核→部分;新增接口行 `IF-F10-REMOTE-ACCESS-01`(INTERFACES 259→260)。
- **验收目标**:principal+授权快照、逐 action/resource 判定与统一 reason、授权变更推送、UI 条件挂载;配对测试(owner/limited 双 token)见 evidence §D4,落 F10-cloud。

### 3 · 17 项“仅在途快照失败”等价对照(完成,定性修正)

- **划分(与交接一致)**:8 项测试函数在基线存在(lifecycle 5 + ACP 3);9 项基线不存在(lifecycle 1 + ACP 6 + projects 2),判定命令 `git show 060071ab:<file> | grep "def <name>("`。
- **隔离基线树**:`D:/Atlas/.worktrees/zcode-exec06-baseline` @ 060071ab(detached,取证后已恢复基线测试文件)。
- **矩阵**:
  - 基线代码+基线测试(8 项):**8 passed, exit 0**。
  - 当前代码+当前测试(17 项):**17 passed, exit 0**。
  - 基线代码+当前测试(同一 17 项,测试与夹具从当前树复制):**11 passed / 6 failed, exit 1**。
  - 8 项基线存在项在两套代码下均通过;9 项新增中 3 项两套产品均通过、6 项仅在基线失败(尝试隔离/ACP 取消/已提交尝试流/allow_once 副作用/项目指令注入——均为在途产品新增或修复的行为)。
- **归因**:代码回归 **0**;6 项=在途功能测试范围;3 项=可移植新增测试;早前 17 项失败不可复现,失败签名为 `SimpleNamespace` 缺 `local_execution_permission_mode`(窄 config stub 泄漏到长生命周期服务线程),属环境/测试顺序污染。旁证:本轮 3 文件整跑出现 2 项 test_projects 失败,单独运行 2 passed。
- **证据**:`evidence/exec06-17fail-equivalence-20261118.txt`(矩阵与逐项原因)+ 5 份原始输出(`exec06-17fail-*.txt`)。遗留:三文件整跑的测试间污染建议后续做 fixture 隔离,本批不改测试文件。

### 4 · F03 残余架构 4 行(完成 Atlas 对照,待核清零至 1)

- **B-F03-WEB-BOOT-01** 待核→部分:DSH 双模式 `apps/web/src/main.ts:1-40`(dshDesktopBoot.ready→injections/streamBaseUrl→`__DSH_BOOT_READY__` gate;浏览器直接 run)+`packages/client/web/src/boot.ts:23-120`;Atlas 仅 Electron(`electron.ts:603-623,1124-1132,1791-1839`;preload `index.cts:8,180`),后端 /remote 为极简移动页。缺口=浏览器完整模式+boot 握手+失败上报。
- **B-F03-RENDER-02** 待核→部分:DSH 唯一 ctx 级 `renderSlot('root')`(`ui-renderer/app.tsx:1-21`)+内置单槽(`registry.ts:24-40`)+AppFrame 子槽(`ui-layout/index.ts:193-201`);Atlas `main.tsx:13-15` 直接 createRoot,全 renderer 无 slot 注册表。
- **B-F03-RENDER-07** 待核→缺失:DSH 11 词平台 seed(`web/src/seed.ts:1-43`)+require 解析顺序与 loud miss(`modules/system.ts:101,136,330-336,384-392`);Atlas Vite 构建期打包,0 命中。
- **B-F03-RENDER-08** 待核→缺失:DSH `parseBootManifest`(`manifest.ts:229-330`)12 类校验;Atlas 无 boot manifest。
- **证据**:`evidence/exec06-f03-boot-render-20261118.txt`(逐行引用+差距+验收);复验 grep 两项均 0 命中。
- **终态**:待核仅余 `B-F02-INPUT-03`(已登记 F02-impl,electron.ts 在途)。

### 5 · PREVIEW-08/09 复核(修正错误缺口标注)

- **发现**:`B-F03-PREVIEW-08`(Office)标为“对齐已验”却在 gap 写“office/excel 渲染为 Atlas 缺口”,与当前代码矛盾。实际链路:后端 `workspace_router.py:642-675 /api/workspace/preview` → `office.py:224+ render_office` → `isolated_preview_worker.py:57-75` 隔离子进程;前端 `FilesPanel.tsx:663-667` sandbox iframe、`:392-407` 解析 xlsx 工作表、`:409-425` 解析 pptx,另有 Windows Sandbox 选项。
- **真实探针**(产品函数,私有 temp,EXIT 0):openpyxl 生成的真实 .xlsx → `render_isolated_preview` → `mode=office-html, bytes=500, has_table/alpha/42=true`;docx 构造包有效但当前运行时 `ModuleNotFoundError: docx`(pyproject:72-74 已声明 python-docx,开发环境未安装)。
- **修正**:PREVIEW-08 对齐已验→**部分**(docx/pptx 代码路由完整,当前环境缺依赖;.doc/.ppt 415);PREVIEW-09 对齐已验→**部分**(xlsx 可用且实测;xls/csv/tsv 无表格化)。
- **证据**:`evidence/exec06-preview-office-20261118.txt`(链路引用+探针输出+逐行验收)。
- 计数:对齐已验 84→82,部分 201→203;总 368 不变。

### 6 · IMPL-3 · CSV/TSV 表格预览(done-in-worktree)

- **隔离 worktree**:`D:/Atlas/.worktrees/zcode-exec06-csv-preview`(分支 `zcode/exec06-csv-preview`,基线 060071ab,node_modules 联结)。
- **改动 3 文件 +231 行**:新增 `csvPreview.tsx`(153 行:分隔符探测 comma/tab/semicolon/pipe、引号内分隔符与换行、`""` 转义、MAX 500 行/64 列/2000 字符、binary/empty/truncated 显式守卫、语义 table+thead);`csvPreview.test.tsx`(6 用例);registry 2 行注册(csv/tsv)。
- **验证**:vitest `csvPreview + documentPreviewRegistry + FilesPanel` **3 文件 13 测试全过(EXIT 0)**;renderer `tsc --noEmit` **EXIT 0**;运行记录 `evidence/exec06-csv-preview-runs.txt`、`evidence/exec06-csv-preview-tsc.txt`。
- **diff**:`evidence/zcode-exec06-csv-preview.diff`;**不合回、不 push**,待主控验收;B-F03-PREVIEW-09 gap 已更新为“csv/tsv 已实现待验收,.xls 仍缺”。
- **未测边界**:未在打包 Electron/真实文件树点选实测(仅组件+registry+消费者测试)。

### 7 · B-F02-INPUT-03 最后待核行清零 + IMPL-4 后端 CAS/原子写(done-in-worktree)

- **对照**:Atlas 已有设备级持久化——`u6_router.py:108-130` keybindings.json(mtime 轮询)、`shortcuts.ts:65-99` localStorage、`App.tsx:558-573` 3s 轮询、原生 `electron.ts:52-55,650-667,827-841,910-918`;DSH 为单写者事务+revision 乐观锁+广播。**状态 待核→部分**(非缺失)。
- **缺口**:PUT 无 expected revision(后写覆盖)、非原子 `write_text`(崩溃可截断)、无跨窗口广播、UI 保存只写 localStorage 未 PUT。验收 A-1..A-5 见 `evidence/exec06-input03-keybindings-20261118.txt` §D。
- **IMPL-4**:隔离 worktree `D:/Atlas/.worktrees/zcode-exec06-keybindings-cas`(分支 `zcode/exec06-keybindings-cas`,基线 060071ab)。`u6_router.py` +109/-15:GET 返回 content sha256 `revision`;PUT 接受 `expected_revision`(不匹配→409,支持 null=创建),temp+fsync+chmod 0600+os.replace 原子写,失败→500 且原文件不动、临时文件清理;格式错误→422。
- **验证**:`tests/test_u6_keybindings.py` **6 passed, EXIT 0**(缺失读/创建/过期 409/匹配更新/非法形状/替换失败保留原文件/损坏文件可修复);记录 `evidence/exec06-keybindings-cas-runs.txt`。
- **diff**:`evidence/zcode-exec06-keybindings-cas.diff`(2 文件 +203/-15);**不合回不 push**,待主控验收。A-4(ShortcutsPanel PUT 冲突 UI)仍待做;未做真机双窗实测。

### 8 · F08 worktree 工具复核(修正“专用 git 工具未见”)

- **DSH 事实**:存在模型工具 `create_worktree`——`packages/experimental/tool-worktree/src/index.ts:13-45`(defineTool,inject tools/worktrees;参数 name/from;输出 {path,branch,baseCommit,repositoryRoot};成功后切会话 cwd);服务 `packages/experimental/worktree/src/index.ts:159-179,251-281`(rev-parse/show-ref/worktree add --no-checkout -b/reset --hard);测试 `tool-worktree/tests/loader-composition.spec.ts:90-108`、`worktree/tests/worktree.spec.ts`。
- **Atlas 事实**:内部服务完整——`task_artifacts.py:215-260 WorktreeService.create/status/remove/merge`;对话 worktree `workspace_router.py:1598-1665`(仅 GET/merge/sync);fork 时创建 `conversations_router.py:2161-2199`;子 Agent `subagent_worktree.py:282+`+`enrichment.py:1264-1380`(GHSA 加固);**模型工具 0 命中、POST create 0 命中**。
- **差距/验收**:无模型工具、无创建后 cwd 切换、无独立 POST create、无 forgePanel;验收 A-1..A-5 见 `evidence/exec06-f08-forge-20261118.txt` §D。状态保持部分(内部能力比 DSH 更严)。
- **表更新**:BEHAVIORS B-F08-FORGE-01 升级(工具+服务+测试,4 个 source_id);ATLAS-MAP 精确入口与 gap。

### 9 · F07 标题命名复核(修正“Atlas 缺 LLM 自动命名”)

- **Atlas 已有**:`title_generator.py:178-290`(derived 立即标题+可选 LLM upgrade,JSON 提示/1000 字符/128 tokens/失败回退)、`atlas_runtime.py:1041-1095`(前 3 个用户回合、与主模型并行、reasoning off)、`run_phases.py:1401-1428`(session.title+accepted)、`session_titles.py:9-16` pin/unpin、`conversations_router.py:1389-1419` 端点。
- **真实缺口**:标题只在 `AtlasRuntime.run_turn` 路径;`AgentOrchestrator.run`(被 `app_server.py:136,592` 使用)无标题 → SDK/ACP 会话不自动命名。另缺 `session/title-llm-request` 精确请求事件、provider 插件面(first/all-prompts)、targetWords/targetCjkCharacters/maxTitleBytes 配置、title-invalid、all-prompts 多消息语义。
- **实测矩阵**:当前树 4 failed/7 passed;基线树同 4 failed/7 passed(同一测试)→ 非在途回归,是 app-server 路径从未接线。证据 `evidence/exec06-f07-title-20261118.txt`、`exec06-title-currenttree.txt`、`exec06-title-baseline-productcode.txt`。
- **表更新**:BEHAVIORS B-F07-TITLE-01 升级(6 个 source_id+测试);ATLAS-MAP 精确入口与 gap;验收 A-1..A-5。
- **实施**:受 `agent/__init__.py`/`run_phases.py` 在途限制,登记 F07-session blocked-on-author。

### 10 · F06 DeepSeek adapter / 凭据(精确差距落盘)

- **DSH**:`llm-deepseek/src/files-api.ts:9-30`(1h..30d、128MiB/上传、10k 文件/25GiB)、`:108-140` 错误分类;`file-store.ts:10-20,50-120`(32MiB/图、durable upload index、共享上传/取消/复用、配额清理重试);`image-tokens.ts` 单图≤1024 token 网格;`request-pricing.ts` 实际尺寸计价;`llm-deepseek-account`(x-dsh-auth-token、ACCOUNT_SIGN_IN_REQUIRED/TOKEN_INVALID/QUOTA_EXCEEDED)与 `credentials/deepseek-account`(浏览器授权/登出重试/通知)。
- **Atlas**:`router.py:166-180,598-624,797-804` + `agent/__init__.py:1135` 图像内联 base64/URL,无 Files API(0 命中);`secrets_store.py:51-111` keyring+加密回退、`:126-260` scrub;`models/routes.py:214-260` provider key 增列删(不回显明文);无账户授权。
- **状态**:两者均保持部分;验收 A-1..A-7 见 `evidence/exec06-f06-adapter-credentials-20261118.txt` §D。实现受 router.py 在途与账户授权边界,登记 F06-model。

### 11 · F01 核心包完整性(更新期强,启动期缺)

- **DSH**:`core-package-set.ts:10-31,55-118,131-181`(desktop-packages.json 逐包 sha512、排序/重名/版本匹配、lockfile 拒绝 registry;整包 file: overrides);`project-manager.ts:135` 启动前 verify;`runtime-tree.ts:214` 运行时树校验。
- **Atlas**:`write-release-manifest.mjs` 构建期记录 installer/backend exe/node archive/sqlite dll 的 sha256+版本一致性;`releaseUpdate.ts:70-140` 更新时安装包 sha256 三来源+重算+可选 Authenticode;但已安装树启动期不复核(grep executable_sha256/canonical_archive_sha256=0),无 npm 核心包集合(后端为 PyInstaller exe)。
- **验收 A-1..A-4**:启动前 fail-closed 校验清单与二进制哈希、缺清单拒绝、更新后三处版本一致;启动钩子受 electron.ts 在途限制。证据 `evidence/exec06-f01-core-pkg-20261118.txt`。状态保持部分。

### 12 · IMPL-5 · DSH 技能源阶梯(done-in-worktree)

- **DSH**:`skill/src/index.ts:28,40,55-75`(BUNDLED_SKILL_RANK=600、七源、InvocationPolicy)+`skill-filesystem/src/index.ts:35-39,256-268`(项目 DSH 100 > 项目 agents 200 > runtime 250 > custom 300 > 用户 DSH 400 > 用户 agents 500 > bundled 600,低者胜)。
- **Atlas 原状**:`skills/__init__.py:709` 五类(atlas/library/atlas-user/hermes/claude-user/claude-project/plugin),无 `.dsh`/`.agents`/custom/runtime/bundled。
- **IMPL-5**:worktree `zcode/exec06-skill-sources`(基线 060071ab)2 文件 +182/-3——优先级扩展为高者胜映射(plugin 60 > project-dsh 40 > project-agents 38 > claude-project 30 > runtime 25 > custom 22 > claude-user 20 > user-dsh 19 > user-agents 18 > hermes 15 > atlas-user 12 > library 11 > atlas 10 > bundled 5);`default_skill_sources` 新增 custom/runtime/bundled 参数,项目/用户 `.dsh`/`.agents` 仅目录存在时加入(缺省列表不变)。
- **验证**:新测试 5 passed EXIT 0;既有技能 7 文件 **47 passed / 1 failed**(`test_atlas_hub_state_forced_under_data_dir` 报 `No module named 'tools'`,基线 worktree 同失败 → 环境路径,非本次改动)。记录 `evidence/exec06-skill-sources-runs.txt`、`exec06-skill-sources-regression.txt`。
- **diff**:`evidence/zcode-exec06-skill-sources.diff`;**不合回不 push**,待主控验收。剩余:server 传 custom/runtime/bundled、virtual runtime provider、同名组合矩阵;验收 A-1..A-5 见 `evidence/exec06-f09-skill-sources-20261118.txt`。

### 13 · F05 行级:batch 调度 / retry durable / bash-sandbox

- **batch**(B-F05-BATCH-01):DSH `core/tools/src/batch.ts:1-240`(exclusive barrier、有界并行池、dispatch 前重分类、model-order 提交、abort 合成结果、scheduler failure 抛给 step);Atlas `tools.py:687-718,892-1035`(分类+dispatch 前复检、Semaphore+flush、ordered results、cancelled receipt、batch 锁)。核心语义等价;差异仅 scheduler failure 降为单调用 failed receipt 与 batch 锁粒度。状态保持对齐已验,验收 A-1/A-2。
- **retry-durable**(B-F06-RETRY-DURABLE-01):DSH `llm-retry/index.ts:83-230` + `types.ts`(`llm/retry` 先落盘、`llm/retry-started` 等待后、retryId/provider/mode/policyKey/maxRetries/failure,投影 llmRetry);Atlas `loop.py:2618-2685` durable `model/attempt`(started/committed/discarded+retry 字段)+`session_sync.py:675-735` 恢复(`outcome_unknown`/`retry_scheduled_not_started`)+`app_server.py:1165-1180` explicit_resume_required。**原“缺 llm/retry”表述过强**;真实差距=事件契约(无 retry-started/稳定 retryId/策略元数据),状态部分,验收 A-3/A-4。
- **bash-sandbox**(B-F05-SANDBOX-01 / B-F08-SHELL-01):DSH `bash-sandbox/src/index.ts:1-140`(per-call policy、denial signatures、runner failure→SANDBOX_UNAVAILABLE、后台 runnerFailed、mode/enforcement/denied);Atlas `sandbox.py:15-270`(Docker per-run、read-only 一次性 ro 容器、workspace-write exec、**danger-full-access 拒绝**、Job fallback、ssh bwrap)。两档隔离更严,但第三档、denial/runner 分类与后台语义缺失 → SANDBOX-01 **对齐已验→部分**;SHELL-01 保持部分。
- **实测**:`test_tool_scheduler_concurrency.py + test_retry_attempt_isolation.py + test_dsh_w7_sandbox.py` → **25 passed, EXIT 0**(`evidence/exec06-f05-targeted-runs.txt`)。
- **证据**:`evidence/exec06-f05-batch-retry-sandbox-20261118.txt`;实施受 loop.py/model_call.py/sandbox.py 在途限制,登记 blocked-on-author。

### 14 · F07 会话格式版本链复核

- **DSH**:四段冻结迁移包 `session-format-v0-to-v1`(codec/dispositions/relationships/payload-validation)、`v1-to-v2`、`v2-to-v3`、`v3-to-v4`;`session-format/src/chain.ts:83` 与 `catalog.ts:42,54-99` 对“stored newer format”返回 `status:'unsupported'+reason`,不降级;`current.ts:19,39` 拒绝非当前 header。
- **Atlas**:`atlas_state_common.py:284 SCHEMA_VERSION=32`;`atlas_state_schema.py:993-1126` 按版本前向执行 v16/18/20/22/23/25/29/30,`row>SCHEMA_VERSION` → `SchemaTooNewError` 拒绝打开(`atlas_state_errors.py:186`);另有 legacy transcript 迁移(gate+备份/暂存/校验)是不同层。
- **结论**:核心不变量一致(旧库前移、新库拒绝、失败不推进版本),形态不同(SQLite schema vs 纯事件日志;Atlas 迁移内联单函数)。状态保持对齐已验;gap=审计粒度/unsupported 投影/事件日志同构性。证据 `evidence/exec06-f07-format-chain-20261118.txt`,验收 A-1..A-4。

### 15 · PAR-07 五包并行(ZCode 原生 Agent 并发,5/5 启动)

实际启动 **5 个 Agent**,同一轮发出:PAR07-A CSV 修复、PAR07-B 快捷键端到端、PAR07-C 技能源接线、PAR07-D worktree API 独立验收、PAR07-E SDK 取消。主代理逐份复跑关键验收,结果如下。

- **A · CSV 真修复**(`zcode-exec06-csv-preview`):`parseDelimited('""')` 丢行→`rowStarted` EOF 修复;首逻辑记录跨引号换行导致分号误判→`firstLogicalRecord`。新增 2 回归,合计 **15 tests passed + renderer tsc 0**;主代理复跑一致。未启动 dev Electron(无安装/build,边界已记)。diff `evidence/zcode-par07-a-csv-fix.diff`,收据 `par07-a.md`。
- **B · 快捷键端到端 CAS**(`zcode-exec06-keybindings-cas`):新增 `keybindings.ts`(GET revision→PUT expected_revision→409 类型化→续用新 revision,首建 null,旧 payload 兼容);ShortcutsPanel 挂载读取、409 冲突横幅、重新加载/用本机改动重试,本地偏好保留。**后端 7 + 前端 11 + tsc 0**;完整前端 **376 passed**;主代理复跑一致。未做双窗真机(边界)。diff `evidence/zcode-par07-b-keybindings.diff`,收据 `par07-b.md`。
- **C · 技能源生产接线**(`zcode-exec06-skill-sources`):新增 `skill_source_config_overrides()` 复用 `extensions.*`,server lifespan + `atlas exec` 双入口,示例配置;测试 16(七级同名矩阵+双源成对+workspace 边界+配置接线);复跑 **39 passed**,2 个基线环境失败(hook 信任/missing tools)已单独确认。主树 server.py 在途,合入锚点 464–477。diff `evidence/zcode-par07-c-skill-wiring.diff`,收据 `par07-c.md`。
- **D · worktree API 独立验收 + 修复**:D 判定原 IMPL-6 **NOT MERGEABLE**——POST 把 `conversation.workspace` 覆盖为 worktree path,破坏既有 merge/delete 以 workspace 为 base 的不变量(真实 HTTP 复现:merge 400、delete 残留)。修复分支 `zcode-par07-worktree-api-fix`:只写 worktree_*,workspace 保持 base;新增 create→status→merge→delete 生命周期测试;**9 passed**,route snapshot 通过。**同时修正**:模型工具 `workspace_worktree_manage` 基线已存在(`workspace_workflows.py:1089`、`loop.py:3779`),run-request `worktree` 已自动创建/切换(`run_drive.py:2233-2262`);IMPL-6 只补 REST create,无 client 调用方。证据 `par07-d.md`、`par07-d-fix.md`、`zcode-par07-worktree-api-fix.diff`。
- **E · SDK 问题取消**(`zcode-par07-sdk-cancel`):被取消未决问题恰好一次 `user-question.cancelled {requestId,sessionId}`;`ask_user` 抛 CancelledError 而非空串;pending→resolved|invalidated 单一权威;迟到/重复回答 -32602;SDK `request_id`/`respond_input`/`cancel_session`;durable invalidated/重连/重启保留。新 6 + 既有 35 通过;主代理复跑 **24 passed**。桌面 A-2(`input.cancelled`/卡片终态)单列。diff `evidence/zcode-par07-e-sdk-cancel.diff`,收据 `par07-e.md`。

**未合回、未 push**;五包各自 worktree 独立。D 的阻断已由修复分支关闭,原 IMPL-6 分支保留为被拒证据。

### 16 · F09 插件注册表复核(修正“无包管理器语义”)

- **DSH**:`plugin-manager/src/registry.ts:14,17,54,92`——官方 npm/npmmirror 常量、`registryPlan`(配置首+fallback;请求注册表在集合内先问、集合外单独问;私有/pnpm 自身未知 registry 不回落)、`attributeFailure`(registry/spec-host/other)、`versions.ts` newerVersions/versionFacts(peerDependencies/deprecated/dsh)。
- **Atlas**:`plugins/runtime.py:371-410` 单 `registry` 安装操作;`:505-530` pnpm `--registry`;`:657-680` npm pack `--registry`;requestId 幂等/审批/取消齐全;但无 fallback 计划、无公共性判定、无失败归因/换源重试、无版本事实。旧“无包管理器语义”**错误**,已改为“单源安装底座”。
- **状态**:缺失→部分(81/206/81);验收 A-1..A-5;实施因 `plugins/runtime.py` 在途 blocked-on-author,可先做纯函数模块。
- **证据**:`evidence/exec06-f09-registry-20261119.txt`。

### 17 · F09 受管 MCP 管理面复核(修正“无对应”)

- **DSH**:`mcp-manager/src/index.ts:43,71,83,193` McpServerManager(Typert Remote),注册/启停/状态视图。
- **Atlas**:`tools_router.py:380-539` GET/POST/DELETE `/api/mcp/servers`、`:633-652` restart、`:663-689` reconnect-failed;`mcp_client.py:251-1432` handle/config/status/restart_server/Scoped;`integrations_router.py:435` 复用 restart。核心注册/启停/重启/状态已存在,旧“无对应”错误。
- **状态**:部分→对齐已验(82/205/81);差异=HTTP REST vs Typert Remote、无 per-server disable 粒度。证据 `evidence/exec06-f09-mcpmanager-20261119.txt`。

### 18 · 证据链接修复

- WATCH-05/IMPL-2 的 18 个 pair/impl 证据原只写在外部队列目录,PROGRESS/ATTEMPTS 的相对链接无法解析;已复制同名文件到本交付 `evidence/`(pair-*.txt、pair2-*.txt、impl2*-mcp-after.txt),计数与内容未改。

### 全表复验

- `audit_tables.py`:**FAILURES 0**;BEHAVIORS 368 / INTERFACES 260 / ATLAS-MAP 368;对齐 82 / 部分 205 / 缺失 81 / 待核 0;锚点 有效=770/32 与 472/16,断链 0;QUEUE 48 行。

## 精确接续位置(下一批)

1. **主控验收隔离分支**:IMPL-1 code preview、IMPL-3+A csv/tsv(`zcode-exec06-csv-preview`)、IMPL-4+B keybindings(`zcode-exec06-keybindings-cas`)、IMPL-5+C 技能源(`zcode-exec06-skill-sources`)、worktree API 修复(`zcode-par07-worktree-api-fix`,取代被拒的 `zcode-exec06-worktree-api`)、PAR-07-E SDK 取消(`zcode-par07-sdk-cancel`);均未合回未 push。
2. **F09 剩余**:server.py 在途解除后按锚点 464-477 合入 C 接线;virtual runtime provider;source/provider 分离。
3. **F02-impl 剩余**(blocked-on-author):electron.ts 解除后做剪贴板图片/file-drag/device-info/渠道切换;快捷键 CAS+冲突 UI 已由 B 完成。
4. **F03 架构实施候选**:web 双模式+boot 握手、slot 注册表、平台 seed、boot manifest;office 依赖安装验证(docx/pptx 探针)、.xls/legacy 格式。
5. **剩余行级对照**:F04 PYSDK 缺失方法、F09 registry 语义;F05 batch/retry/sandbox、F07 标题/格式链、F08 worktree 已完成。
6. **P1 收尾**:other 493 行已归类;packages 二次复核。
7. **P4**:omni_bench 安全 batch(R2 blocked-on-author)解除→required_superiority_set 冻结→同条件基准。
8. 云端确认项:`dsh_session_log` 官方接受、Relay 服务端=观察边界。

## 纪律与边界(持续有效)

- 本批只写交付目录+自有临时目录;主工作区在途改动(loop/model_call/tools/session_sync/sandbox/app_server/electron.ts/sdk-python/omni_bench)归原作者,相关行均已标注。
- macOS 仅静态证据;云端私有实现(Relay 服务端、官方 API 接受)=观察边界;无 commit/push。
- 钩子边界(2026-11-18):旧 glm-hammer forge/recon 运行 `1f40231e-d0ae-4629-bed1-56a0c442a8ea` 的 Phase-0 在本机因 CRLF/Linux 认证夹具被判 stale,与本任务无关。已用真实结构提问 proof(`USER_QUESTION_OBSERVED` seq10)按插件自身流程结束为 `RUN_ENDED_UNVERIFIED`(seq11,非 PASS),随后 state 置 idle;stop-gate 干跑无 block。该事件不计入 DSH 验收。

## ZC-DSH-PAR-08(2026-11-19,主会话复验)

- **A · CSV/TSV 预览空态**(`zcode-exec06-csv-preview`):`csvPreview.tsx` 空态改为仅 `totalRows===0`;`""`(引号空字段)与空行记录按记录渲染表格,`FilesPanel.test.tsx` 无需改。主会话复跑 `csvPreview/documentPreviewRegistry/FilesPanel` **3 文件 17 tests passed(exit 0)**、renderer `tsc --noEmit` **exit 0**;隔离 Electron(44.7.0,独立 user-data-dir,v44 实际鼠标点文件树)**19 PASS/0 FAIL,exit 0**,空文件显示空态、`""` 显示 1 行 1 列表格;主会话另跑全量前端 **82 文件 378 tests passed(exit 0)**。证据 `evidence/par08-a.md`、`par08-a-electron-*`。未覆盖完整 BackendAdapter/后端。
- **B · 快捷键并发重放**(`zcode-exec06-keybindings-cas`):409 重试改为 per-action 意图(set/delete/reset/reset-all)基于最新文件重放,未触达的远端修改保留,同 action 逐项裁决。上轮证据:后端 **7 passed**,前端定向 **25 tests**,全量 **390 tests**,renderer tsc 0;双窗真实后端 **200→409→200**,`palette`/`newTask` 同时落盘。**B2 已收口(2026-11-19)**:`effectiveKeybindings` 以「文件存在值优先(含显式 `[]`)、缺键取有效默认」作为冲突基线;文件缺失时基线=用户可见默认值,首个客户端落盘的默认项不再误判为并发编辑,显式解绑与默认严格区分。主会话复跑后端 **7 passed**、定向 **33 tests**、renderer tsc 0;真实双 Electron+临时 uvicorn 三场景 **PASS**(missing/existing/same-action,均 200→409→200 或明确裁决,`problems: []`),全量前端 83 文件 398 tests。证据 `evidence/par09-b2.md`、`par09-b2-electron-summary.json`。**本包缺口关闭。**
- **C · 桌面工作区技能源**(`zcode-exec06-skill-sources`):server lifespan 不再用默认 workspace 注册项目源;`run_drive` 在 `run.workspace` 确定后以 `SkillManager.with_sources(project_skill_sources(ws), drop_sources=PROJECT_...)` 构建 per-run scoped 视图,`.dsh`(40)/`.agents`(38)/`.claude`(30) 按会话解析;无 workspace 与 `ssh://` 不加项目源。主会话复跑 `test_skill_sources_dsh.py` **22 passed(exit 0)**、`test_par08_workspace_skill_e2e.py` **1 passed(exit 0,真实 uvicorn+/ws/chat+假 LLM,默认 workspace 泄漏场景)**;15 文件回归 166 passed/2 基线失败(hook 信任、`No module named 'tools'`,与 PAR-07 同)。残留单列:`use_skill` 工具与 `skills_router` 列表仍走共享管理器(未实现 per-run 注入),项目技能仅 run 解析面生效。证据 `evidence/par08-c.md`。
- **D · worktree API 回滚**(`zcode-par07-worktree-api-fix`):回滚拆为 `rolled_back`(清理已验证)与 `rollback_failed`(不声称已删除,持久化 recovery:conversation/path/branch/base/reason/时间戳,新增 `worktree_recoveries` 表与 GET/POST recovery 路由);记录失败+remove 失败时 Git 仍 2 棵树、会话 worktree_path 为空,恢复后重试可清残留。测试 **13 passed/1 既有基线失败**(`test_fastapi_lazy...original_route`),route snapshot 目标用例 PASS,快照 delta 仅新增 2 条 recovery 路由。**D2 已收口(2026-11-19)**:新增 `_validate_worktree_target`,按 `realpath` 证明目标严格等于 `<workspace parent>/.atlas-worktrees/<repo>/<short id>`,校验 branch `atlas/<short id>[-suffix]`、base 存在、checkout 实际分支、workspace 匹配,并拒绝根/基库/托管根/异库/未托管目录/跨边界 junction;删除前、orphan rmtree 前、branch -D 前重复校验。主会话复跑 `test_conversation_worktree_create.py` **19 passed(exit 0)**、`test_routes_match_frozen_snapshot` **1 passed**;最终三文件 23 passed/1 既有基线失败。**本包缺口关闭。** 证据 `evidence/par08-d.md`、`par09-d2.md`。
- **E · SDK 取消移植(暂停,不重启)**:`zcode-par08-sdk-port` 已保留,包含作者在途基线(app_server 1610 行/SDK 697 行/minimal support 逐文件 sha256)与本包增量(app_server +284/−56、SDK +31/−3、docs +14/−5)。已有证据:Python 3.11.15 **42 passed exit 0**;`D:/Atlas/core/.venv` Python 3.14.7 **42 passed exit 0**;旧树 3.14 在首次关闭断言处 **exit 1** 已复现(`test_app_server_user_question_cancel.py:523`,`process.wait(timeout=0)==0` 得 1)。**缺 `evidence/par08-e.md` 收据**;未获明确恢复前不自动重启 E。续接点:补收据(基线哈希/增量拆分/双环境命令)+主控复核。

### PAR-09 后台并行收件(2026-11-19)

- **B2 · 快捷键首次创建**(`zcode-exec06-keybindings-cas`):`effectiveKeybindings` 以「文件存在值优先(含显式 `[]`)、缺键取有效默认」为基线;文件缺失时默认项不再误判并发编辑,显式解绑与默认严格区分。主会话复跑 pytest **7 passed**、定向 vitest **33 tests**、renderer tsc 0;真实双 Electron+临时 uvicorn 三场景 **PASS**(missing/existing/same-action),`problems: []`;全量前端 83 文件 398 tests。证据 `evidence/par09-b2.md`。**缺口关闭,队列 PAR08-B 同步 done-in-worktree。**
- **F01 · 启动完整性**(`zcode-par09-release-integrity`):新增 `frontend/src/main/releaseIntegrity.ts`(702 行,纯函数+可注入 fs)与 `releaseIntegrity.test.ts`(449 行);覆盖清单三候选、schema、Atlas.exe/atlas_backend.exe/sqlite3.dll 存在与 SHA-256、缺清单/非法 JSON/哈希不匹配、绝对路径与 `..` 逃逸、symlink/junction、app/Electron/后端/node/平台版本一致性。主会话复跑 electron `tsc --noEmit` **exit 0**、vitest **1 file/26 tests passed(exit 0)**;当前仅 2 个新文件,`git diff` 为空。接线点冻结在 `electron.ts:1777` 的 `app.whenReady` 打包态,但现有打包链不收录 `release-manifest.json`,**保持待接线**,不声称启动期已生效。证据 `evidence/par09-f01.md`。
- **F09 · 插件注册表策略**(`zcode-par09-plugin-registry`):新增纯函数 `core/atlas/plugins/registry_plan.py`(497 行)与 44 项测试(378 行):配置主源优先+fallback、请求源在/不在配置集、pnpm 自身私有/未知源不回落公共、URL 归一(host 小写/默认端口/路径折叠/去重/剥 userinfo)、`attribute_failure` 三分法与可重试白名单、`retry_allowed` 禁止 spec-host/other 回落。主会话复跑 **44 passed(exit 0)**、ruff **All checks passed**;接线补丁 `par09-f09-wiring.patch`(runtime.py + plugins_router.py)对主树在途文件 `git apply --check` **exit 0**,状态**待集成**(未接入重试循环/失败归因落状态/前端展示)。仅两个新文件,未碰真实账号/注册表。证据 `evidence/par09-f09.md`。
- **D2 · 恢复清理归属**(`zcode-par07-worktree-api-fix`):新增 `_validate_worktree_target`(realpath/junction 解析、受管路径精确匹配、workspace/branch/base/checkout 校验)与 `_cleanup_worktree_residue` 的删除前重复校验;拒绝目录根/基库/workspace/托管根/异库/未托管目录/跨边界链接,拒绝时保留文件与恢复记录并返回 409 `recovery_refused`;已注销 Git 的 orphan 同样过校验才 rmtree;未新增通用删除接口、未改路由/快照。主会话复跑 `test_conversation_worktree_create.py` **19 passed(exit 0)**、`test_routes_match_frozen_snapshot` **1 passed**;边界矩阵 11 passed;最终三文件 23 passed/1 既有基线失败。证据 `evidence/par09-d2.md`。
- **MCP · 启动与 Node 复核**(`zcode-exec05-mcp`):既有 `test_mcp_client.py`+`test_mcp_client_scope.py`+`test_mcp_batch_reconnect.py` 主会话复跑 **29 passed(exit 0)**;真实 mcp 2.0.0 stdio server 走正常 `MCPClient.start()`→`initialize/tools/list`→echo→stop→restart,protocol `2025-11-25`,**25 checks passed**;打包 Node 端到端用旧包 v22.23.3 实际执行,选择命令确为打包 `node.exe`,echo 成功,**11 checks passed**;异常矩阵(命令不存在/立即退出/init 错误)0.5-0.7s 进入 `failed`+`available=false`+脱敏 reason,正常停止/禁用/未配置状态正确;3 个 pair 失败项已全部关闭。工作树仍为 IMPL-2 三文件 +63/-12。**未修基线缺口**:杀掉已连接子进程 8s 内不自动重连且 status 仍 connected;启动过程中 stop 后 status 停留 starting。`test_bundled_node_resolves_from_installed_application_directory` 是模拟路径(假 `node.exe`),非真实打包;本机只有旧 v22 包,当前源码 v24.21.0 真实安装包验收待重新打包。证据 `evidence/par09-mcp.md`。

### PAR-09 小结

五包全部收件为 `done-in-worktree`,均未合并/未 push;主会话逐包复跑关键命令并写回 QUEUE/PROGRESS。合入前剩余:wiring F01(打包链收录 manifest)、F09(生产重试/归因/前端)、E 暂停包补收据、MCP 两项基线缺口与 v24 真实包、A/C 合入前复核、B/D 最终合入验收。

## ZC-DSH-PAR-10(2026-11-19,逐包验收与接续)

### 首批派发(5/5 后台)

- **Codex 独立复验 PAR-09 MCP**:29 项套件、真实 stdio 25 checks、旧版打包 Node v22.23.3 11 checks 均通过;异常退出后仍未自动重连,T5 继续该基线。该结论与主会话收件一致,不重复启动 MCP 包。
- 五个候选树预建并同轮后台启动,均基于 `060071ab`,写者相互隔离:
  - **T1** `zcode-par10-registry-runtime`:把 PAR-09 registry_plan 接入真实插件安装/回退/失败归因,用本地模拟 registry/包管理器验证,不访问真实 registry。
  - **T2** `zcode-par10-release-startup`:把 releaseIntegrity 接入 manifest 生成与 packaged Electron 启动,临时打包目录验证正常/缺清单/损坏/开发态/旧安装兼容。
  - **T3** `zcode-par10-skill-runtime`:保留 PAR-08-C per-run 作用域,补 `use_skill` 与 skills router/Desktop 列表同一 workspace 视图,两工作区同名/独有技能验证;事件变更同步三真源。
  - **T4** `zcode-par10-desktop-recovery-candidate`:组合 A(csv/tsv)、B(B2 快捷键)、D(D2 工作树恢复)最小 diff,逐项复跑并保留冲突证据。
  - **T5** `zcode-par10-mcp-recovery`:以 PAR-09 MCP 生命周期为基线,补子进程异常退出后的可观察状态、有界重连与 stop/disable/并发语义,真实 stdio 验证。
- 回执规则:每包 `evidence/par10-tX.md` 末行 `PAR10_RECEIPT T{1..5} READY|PARTIAL|BLOCKED`;主会话逐包查 diff、复跑、发 `PAR10_REVIEW` 并更新本台账。T6 仅在前述可执行包派完且工位空出时,按最新 QUEUE/PROGRESS 写单包任务书后派发,额外最多两个;SDK E 保持暂停。

### T4 收件(PAR10_REVIEW T4 READY)

- **T4 · 桌面集成候选**(`zcode-par10-desktop-recovery-candidate`):从 A/B/D 三源树只读复制 14 个文件(A3+B7+D4),源 sha256 前后一致、三组件路径交集 0;候选 diff 7 tracked + 7 new,4812 insertions/250 deletions。主会话复跑:
  - A:`csvPreview/documentPreviewRegistry/FilesPanel` **3 files/17 tests** + renderer tsc **0**;
  - B:`test_u6_keybindings.py` **7 passed**、定向 vitest **3 files/33 tests**;
  - D:`test_conversation_worktree_create.py` **19 passed**、route snapshot **1 passed**;
  - 组合前端定向 **6 files/50 tests** + tsc **0**(子代理另跑全量 83 files/408 tests、event contract 13 passed)。
  - 真实 Electron:A 空文件/`""`/TSV 29 PASS;B 双窗三场景 PASS(缺失首次创建、已有文件 replay、同 action 裁决)。
- 三份可转移最小 patch 在候选树 `.tmp/par10-t4/diffs/`(A/B/D,`git apply --check --reverse` exit 0);未覆盖完整桌面/`atlas.server` lifespan、真实 OS 文件锁、同 action「采用文件」路径。回执 `evidence/par10-t4.md` 末行 `PAR10_RECEIPT T4 READY`。**状态 verified,待主控复审。**
- **T6-1 补位**:按 §后续槽位 选 QUEUE `F03-web` / `B-F03-PREVIEW-08` 的已证实 Office 依赖缺口,任务书 `PAR10-T6-1-OFFICE-FALLBACK.md`;候选树 `zcode-par10-office-fallback`(HEAD 060071ab),仅改 `core/atlas/office.py` + 新测试,走真实 `GET /api/workspace/preview` 入口,做 docx/pptx 无第三方依赖降级与明确失败语义。已后台启动。

### T1 收件(PAR10_REVIEW T1 PARTIAL)

- **T1 · 注册表接入安装**(`zcode-par10-registry-runtime`):从 PAR-09 字节一致移入 `registry_plan.py`/测试;新增 `registry_install.py`(388 行)执行 plan 顺序、失败归因门控重试、私有/自定义单源、spec-host 不回落、pnpm ignored-build 审批、凭据仅下发不落状态、输出脱敏。主会话复跑策略/引擎 **60 passed(exit 0)**、既有 `test_plugins.py` **10 passed**;沙箱真实入口(补丁后 runtime + 假 npm/pnpm)35/35,`par10-t1-wiring.patch`(134+/16-,sha256 `6fb780a6…`)对主树在途版本 `git apply --check` **exit 0**。
- **结论 PARTIAL / 链路待接**:候选树 HEAD 没有 npm/pnpm 安装链(`runtime.py:1194-1204` 仅 local/git);真实链只在主树他人未提交 `runtime.py:370-410/504-532/656-681/773+`、`plugins_router.py:136-187` 及未跟踪 `compatibility.py`。按边界未硬改、未复制主树在途文件;补丁待作者解除后应用。未访问真实 npm/pnpm/私有 registry/凭据。
- **T6-2 补位**:按 §后续槽位 选 QUEUE `F09-extensions` / `B-F09-REGISTRY-01` 的 G4/A-3 版本事实缺口,任务书 `PAR10-T6-2-VERSION-FACTS.md`;候选树 `zcode-par10-version-facts`,只做 `newerVersions` + `{peerDependencies,deprecated,dsh}`,优先本地假 registry / 纯函数,不与 T1 安装计划重复。已后台启动。

### T2/T5/T6-1 收件(PAR10_REVIEW T2 READY / T5 READY / T6-1 READY)

- **T2 · 发行启动完整性**(`zcode-par10-release-startup`):移入并扩展 releaseIntegrity(installer 可选,26→34 tests);新增 `after-pack-release-manifest.cjs`/`after-pack.cjs`,在图标嵌入后、NSIS 前写 `win-unpacked/resources/atlas/release-manifest.json`;`write-release-manifest.mjs` 发布侧清单与内嵌清单逐字段对账;`electron.ts` 在 `app.whenReady` 打包态、窗口/后端之前调用 `assertReleaseIntegrity`。主会话复跑 electron `tsc --noEmit` **0**、vitest **34 passed**;候选产物含真实 `win-unpacked` manifest 与 `Atlas-0.1.1-Setup.exe`。子代理实测真实 packaged 启动成功、缺清单/篡改 exit 1 且不拉后端、开发态正常、旧 0.1.0 字节+新清单通过、旧 schema/陈旧 app_version fail-closed;**未跑完整 `npm run dist:win`/NSIS 安装卸载**,backend 用现有 0.1.0 真实副本。回执 `evidence/par10-t2.md`。**状态 verified。**
- **T5 · MCP 退出恢复**(`zcode-par10-mcp-recovery`):从 IMPL-2 三文件按 sha256 移入;新增 stdio 读流 EOF 观察、掉线清工具索引、`reconnecting` 状态与有界重连(10 次/0.5→30s/60s 稳定窗)、disabled/stop/restart 串行化、crash-loop 预算、`unreachable` fail-closed 投影。主会话复跑 5 文件 **47 passed(exit 0)**;子代理真机 17/17 recovery、4/4 stop-during、4/4 disabled、6/6 并发 restart、3/3 stop/restart、7/7 exhaustion、7/7 node;多服务器互不影响、用户 stop 不拉起。`run_drive.py` 改动 1 行需并入在途作者;打包 Node 仅旧 v22.23.3 真实路径,未冒充 v24。回执 `evidence/par10-t5.md`。**状态 verified。**
- **Codex 独立复验(2026-11-19)**:用 T2 候选产物内的真实 Node **v24.21.0** 复跑 MCP connection **11/11**、T5 掉线重连 **7/7**;关闭 PAR-09 的新包 Node 运行证据缺口。另 3 个 lifecycle 节点 `test_stdio_session_shutdown_exits_its_real_child`、`test_cancelled_mcp_discovery_stops_its_real_stdio_child`、`test_cancelled_owner_does_not_skip_other_server_cleanup` 在 T5、PAR-09 源树、`060071ab` 基线均同样失败(主会话三方复跑确认),属基线/环境,不计 T5 回归。
- **T6-1 · Office 依赖降级**(`zcode-par10-office-fallback`):`office.py` +394/−57,保留 python-docx/pptx/openpyxl 优先路径;docx 用 zipfile+`word/document.xml`(标题/段落/表格/`w:sdt`),pptx 按 `slideN.xml` 数字序输出每页;zip 成员 ≤512/单成员 16MiB/总解压 64MiB/文本 20 万/幻灯片 ≤200,拒路径穿越与链接;降级失败抛 `OfficeDependencyMissingError`,worker 路由 422,不漏 `ModuleNotFoundError`。主会话复跑新测试 **17 passed**、既有 office 套件 **24 passed/1 skipped**、ruff 0;子代理真实 HTTP+隔离 worker 证据 docx/pptx/xlsx 均渲染文本。未装真实 docx/pptx 库,前端浏览器 E2E 未做。回执 `evidence/par10-t6-1.md`。**状态 verified。**
- **当前并发**:仅剩 T3(skill-runtime)与 T6-2(version-facts);T6 配额已用满两个,无新派;T1 link-pending 等主树作者解除。

### T6-3/T6-4/T6-5 派发(PAR10-READY-NEXT,按最新授权)

- 去重后确认三项均不在已派范围:T5 只做掉线重连/退出恢复;T6-1 只做 docx/pptx;T2 只做真实 packaged/NSIS payload 且 backend 用副本。三项互相独立,当前 3 个空位一次补齐,总数 5/5。
- **T6-3** `zcode-par10-mcp-lifecycle-gate`:从 T5 源树移入已验改动,复现并判明 T5/PAR-09/`060071ab` 同败的 3 个 `test_mcp_lifecycle_shutdown.py` 节点;区分夹具启动完成语义与真实产品关闭缺陷,修正等待条件并保留断言;同树回归 recovery/reconnect budget/stop 并发。任务书 `PAR10-T6-3-MCP-LIFECYCLE.md`。
- **T6-4** `zcode-par10-legacy-xls-preview`:复用 T6-1 的 `office.py` 隔离 worker 与 T4 预览约定,为 BIFF `.xls` 加只读预览;真实临时样本验证多工作表/文本/数字/日期,损坏/加密明确错误,xlsx/csv/tsv 不回归;无可合法打包解析器则 PARTIAL/BLOCKED。任务书 `PAR10-T6-4-LEGACY-XLS.md`。
- **T6-5** `zcode-par10-win-release-repro`:从 T2 移入 7 个发行文件,用同一源码跑完整 `npm run dist:win`(backend/app/manifest/Node/NSIS),补 T2 的 backend 副本缺口;记录实际命令/产物版本/哈希/Node/真实启动;隔离安装路径做升级验证,不可分离安装记为阻塞。任务书 `PAR10-T6-5-WIN-RELEASE.md`。
- 五项回执仍写各自 `evidence/par10-tX.md` 末行 `PAR10_RECEIPT <包号> READY|PARTIAL|BLOCKED`;主会话逐项复跑并发出 `PAR10_REVIEW`。

### T6-2 收件(PAR10_REVIEW T6-2 PARTIAL)

- **T6-2 · 版本事实**(`zcode-par10-version-facts`):新增 `version_facts.py`(257 行,SemVer 2.0 自包含 `newer_versions` + `version_facts` 的 `{peerDependencies,deprecated,dsh}` 归一)与 481 行测试。主会话复跑交付态 **46 passed/8 skipped(exit 0)**;在候选树临时应用 `par10-t6-2-wiring.patch` 后 **54 passed(exit 0)**,随后 `git apply -R` 复原,工作树仅剩两个新文件。主树 `git apply --check` **exit 1**(`plugins_router.py:11` 冲突,因主树 plugins_router/runtime/server 在途),与 Codex 独立结论一致(Codex 早前一次为 45 passed/8 skipped)。
- **结论 PARTIAL / 链路待接**:候选 HEAD 可应用、主树不可直接应用;路由快照在干净 `060071ab` 已漂移(应用路由补丁时需刷新 `routes.json`)。未做 UI/桌面事件接线。
- **T6-6 补位**:按 `PAR10-PLUGIN-INTEGRATION-NEXT.md` 建立 `zcode-par10-plugin-integration-candidate`,移入 T1+T6-2 与最小主树接口副本,重新适配两处调用点;用回环 registry 合验安装/版本入口、私有/显式源隔离、错误脱敏、生命周期回归;不在主树合并。任务书 `PAR10-T6-6-PLUGIN-INTEGRATION.md`。已后台启动,当前 5/5。

### T6-3 收件(PAR10_REVIEW T6-3 READY)

- **T6-3 · MCP 生命周期**(`zcode-par10-mcp-lifecycle-gate`):从 T5 源树逐文件移入 7 个已验文件(sha256 一致,diff 哈希 `83bbc759…`);三个 `test_mcp_lifecycle_shutdown.py` 节点在 `060071ab`/仅 T5 树上同点失败,根因是**基线夹具把 `await client.start()` 误当启动完成**——产品 `start()` 是 fire-and-forget,为每服务器建后台 handshake 后立即返回。修法仅改测试:新增条件轮询 `_wait_until` 等 `connected`,节点 2 取消真实 per-server startup task 并保留 `CancelledError` 断言;未用固定 sleep。修正夹具在基线产品代码上也 3 passed,证明与 T5 产品修复解耦。
- 主会话复跑 3 节点 **3 passed(连续 3 次)**、同树六文件 **50 passed(exit 0)**;子代理真实 stdio 17/4/7/6/3/4、旧 v22.23.3 与新 v24.21.0 打包 Node 各 7 checks 全过。仅改 `test_mcp_lifecycle_shutdown.py`(+50/−2)。
- 剩余:`test_mcp_server_atlas_sync.py` 2 节点仍因 `No module named 'tools'` 失败(与 T5 源树相同,既有环境),未跑完整 dist:win/NSIS。回执 `evidence/par10-t6-3.md`。**状态 verified。** 当前 4/5,待 T3/T6-4/T6-5/T6-6;空位评估 T6-7。

### T3 收件(PAR10_REVIEW T3 READY)

- **T3 · 技能列表与调用**(`zcode-par10-skill-runtime`):从 PAR-08-C 逐字节移入 skills/server/run_drive/cli/配置/两测试;新增 per-run `use_skill` 作用域——`AgentOrchestrator._skills` 改为基于 `ContextVar[_RUN_SKILL_MANAGER]` 的 property,`run_phases.execute_run` 按 `RunRequest.skill_manager` set/reset(不全局替换,并发 run 隔离);`run_drive` 两个入口传 `_workspace_skill_manager(workspace)`。skills API(`/api/skills`、详情、依赖、activate、search)与 `BackendAdapter.getSkills(workspace?)`/store `refreshSkills`/`App.tsx` 随会话工作区切换重查;无事件形状变化,无需三真源同步。
- 主会话复跑:unit **31 passed(exit 0)**;PAR-08+PAR-10 e2e **3 passed(exit 0)**(真实 uvicorn/`/ws/chat`/FakeLLM 调 `use_skill`);adapter **24 passed**;前端全量 **81 files/368 tests passed(exit 0)**。两工作区同名 `shared` 分别返回 A/B `project-dsh` body,`only-a` 跨区 404,无 workspace 仅 12 base skills。15 文件门 170 passed/2 基线 deselect。未跑真实模型/打包 Electron;`test_agent` 7 个既有 fixture 失败已单列。回执 `evidence/par10-t3.md`。**状态 verified。**
- **T6-7 补位**:按 T6 规则选 `F06-model` / `B-F06-DEEPSEEK-ADAPTER-01` 的 A-5 图像 token 网格缺口,任务书 `PAR10-T6-7-IMAGE-TOKENS.md`;候选树 `zcode-par10-image-tokens`,逐行移植 DSH `image-tokens.ts` v41(PATCH 14/DOWNSAMPLE 3/MAX 1024/MIN_PIXELS 544²/CELL 42),移植官方 fixture;可选 router 预算接线,主树 router 在途则 patch/链路待接。已后台启动,当前 4/5。

### Codex 独立复验(T6-3 / T3)

- Codex 独立复跑 T6-3 同树回归 **50 passed**,与主会话一致;确认 3 个 lifecycle 节点在修正夹具后通过。
- Codex 独立复跑 T3 后端 **6 passed** 与 Desktop adapter **24 passed**,与主会话的 31 unit/3 e2e/24 adapter/368 frontend 结论一致(计数口径为定向子集)。

### T6-8/T6-9 派发(PAR10-RUNTIME-READY-NEXT)

- **T6-8** `zcode-par10-batch-cancel-order`:QUEUE `F05-host` / `B-F05-CANCEL-SYNTH-01`;用临时确定性工具走正常批调度入口,覆盖请求/完成乱序、运行中取消、排队取消、call ID 单终态、结果顺序 vs 进度事件顺序;主树 `tools.py` 在途只读,仅复现缺口才补最小实现。任务书 `PAR10-T6-8-BATCH-CANCEL-ORDER.md`,已启动(当前 5/5)。
- **T6-9** `zcode-par10-worktree-windows-lock`:QUEUE `PAR09-D2-recovery-boundary` / `PAR10-T4-desktop-candidate`;从 T4 D2 最小 diff 起步,用真实 Windows 文件句柄(独立 holder 进程)、临时 Git 仓库与已管理 worktree,验证记录失败+真实占用 → `rollback_failed`/recovery 准确、释放句柄后恢复成功、不误删其他树、正常 create/status/delete+快照。任务书 `PAR10-T6-9-WORKTREE-WINDOWS-LOCK.md`;候选树已预建,状态 `queued`,等下一空位。

### T6-4 收件(PAR10_REVIEW T6-4 READY)

- **T6-4 · 旧 Excel `.xls` 预览**(`zcode-par10-legacy-xls-preview`):确认 T6-1 写者停止后按 sha256 移入其 `office.py`/fallback 测试;`.xls` 加入常规预览与 Windows Sandbox 预览 accepted set,前端 FilesPanel/registry 分流纳入 xls;解析器采用 BSD、纯 Python、可打包的 `xlrd 2.0.1` 并写入 `core/pyproject.toml`,PyInstaller 6.22.3 冻结探针无 hidden-import 也能渲染 `RUN_EXIT=0`。
- 主会话复跑 `test_office_preview_xls.py` + fallback + 既有 office/pdf **57 passed/1 skipped(exit 0)**、ruff **0**、renderer `tsc --noEmit` **0**、registry vitest **3 passed**。子代理真实 BIFF8 多工作表经 HTTP/隔离 worker 返回 200 `office-html`(文本/数字/日期/时间/布尔);加密/随机损坏/截断 **422**,>10MB **413**,`.doc/.ppt` 仍 **415**,xlsx/csv/tsv 无回归;缺 xlrd 为 422 `dependency_missing`。候选树 7 tracked + 2 新测试 + fixtures。
- 未覆盖:Windows Sandbox 实跑(本机未启用)、自定义数字格式、公式计算(仅缓存值)、Electron E2E。回执 `evidence/par10-t6-4.md`。**状态 verified。**
- **T6-9 补位**:T6-4 释放的工位由已排队 T6-9 接替,已后台启动;当前 5/5(T6-5/T6-6/T6-7/T6-8/T6-9)。

### T6-8 收件(PAR10_REVIEW T6-8 READY)

- **T6-8 · 批取消结果顺序**(`zcode-par10-batch-cancel-order`):唯一新增 `core/tests/test_par10_t6_8_batch_cancel_order.py`(201 行,3 个 unit),产品代码**零改动**;主树 `tools.py` 仅无关 read_file schema 在途,本包相关函数逐字节一致。
- 3 个用例走 `ToolScheduler.run` 正常入口 + 确定性 Event 工具:
  1. 请求 A,B,C、完成 C,A,B → 结果/上下文仍 A,B,C;进度完成顺序单列为 C,A,B;3 个 call ID 各一终态;
  2. A 完成、B 执行中、C 排队时取消 → B `cancelled` + `cancellation_phase="during execution"`,C 合成 `cancelled`(before execution,无 phase,duration 0)且从未 dispatch;整批 `batch_state=cancelled`;
  3. 整批在批次锁排队时取消 → 两调用均 before-execution 合成,dispatch 从未调用,不伪造已启动结果。
- 主会话复跑新增 **3 passed**、新增+既有 **34 passed(exit 0)**;子代理另做 10/10 重复稳定。名义差异(DSH `TOOL_ABORTED` 码位、连续前缀提前提交 vs Atlas 整组排干)不影响验收。未覆盖真实模型/桌面事件流顺序/自由文本 cancel message。回执 `evidence/par10-t6-8.md`。**状态 verified(对齐项,无产品改动)。** 当前 4/5,保留 1 空位待下一授权项。

### T6-7 收件(PAR10_REVIEW T6-7 READY)

- **T6-7 · 图像 token 网格**(`zcode-par10-image-tokens`):逐行移植 DSH v41 `image-tokens.ts`——PATCH 14/DOWNSAMPLE 3/MAX 1024/MIN_PIXELS 544²/CELL 42,`grid_tokens`/`grid_cells`/`solve_resize_ratio`/`safe_resize`/`resize_once`/`deepseek_image_tokens`/`deepseek_request_image_dimensions`;新增无第三方库的 Base64 图像固有尺寸解析与 `deepseek_message_image_tokens` 消息级计价。`router.py` +14/−2:仅对 DeepSeek route 在真实预算 `estimate` 中加图像 token。
- 主会话复跑 `test_image_tokens.py` **65 passed**、`test_model_router.py` **65 passed(exit 0)**;候选 patch 对主树 `git apply --check` **exit 0**(主树 router.py 在途仍保留)。覆盖 1×1/小图/极端宽高比/1024 cap/fixpoint/非法尺寸/请求尺寸投影/预算路径。
- 边界:`token_meter.route_image_pricer` 链路与发送前图片重编码未接;未做 Files API/账户(不在 A-5);未合并/push。回执 `evidence/par10-t6-7.md`。**状态 verified。**
- **断线续接**:T6-7 代理在写出 READY 回执后无进展,已停止并由主会话收件;T6-5/T6-6/T6-9 因 API TLS 断连中止,已按原上下文续接(不重做已完成的构建/测试),当前 3/5。

### T6-6 收件(PAR10_REVIEW T6-6 READY)

- **T6-6 · 插件注册表+版本信息合验**(`zcode-par10-plugin-integration-candidate`):T1/T6-2 模块按源 sha256 移入;主树在途 `runtime.py`/`plugins_router.py`/`compatibility.py`/`test_plugin_install_operations.py` 只读复制并重新适配两处调用点(安装:审批/幂等/取消/状态快照/失败归因/脱敏;版本:同一 plan + 同源重定向限制/15s/8MiB/凭据与未知源拒绝),AST 复核无缩进落错。
- 主会话复跑 combined **158 passed(exit 0)**:纯函数/路由 114(44+16+54,T6-2 的 8 个 HTTP skip 已变真实执行)+ 集成 15 + 既有插件 28 + `test_routes_match_frozen_snapshot` 1。子代理真实回环 registry 矩阵 15/15(公共回退、私有/显式/spec host 不回落、未知源拒绝、版本/依赖/预发布、脱敏、生命周期、幂等)。
- `test_plugin_install_operations` 单独运行出现 **20/6、23/3、21/5** 漂移(失败集含 Windows PermissionError、patch-carry、缺真实 pnpm fixture);主会话单节点对照:候选 `git_manifest`/`marketplace` 单跑均通过,主树 `git_manifest` 单跑反而失败——判为套件顺序/环境抖动,非本包回归;不冒充全绿。
- `routes.json` 839→865,归因:本包 1 条、主树在途 router 10 条、候选 HEAD 既有漂移 15 条。可重放补丁 `.tmp/t6-6-artifacts/par10-t6-6-wiring.patch` 对当前主树 `apply --check` **0**,主树未应用。未覆盖真实 npm/私服/账号、SSRF 白名单、前端 UI、pnpm 自身 registry `resolved`;合并时需按目标 FastAPI 版本重冻结快照。回执 `evidence/par10-t6-6.md`。**状态 verified(候选合验,不合并)。**
- **当前并发 2/5**:T6-5、T6-9(RESUMED);其余已完成。

### T6-5 收件(PAR10_REVIEW T6-5 PARTIAL)

- **T6-5 · Windows 完整发行链**(`zcode-par10-win-release-repro`):从 T2 按字节移入 7 文件;`npm run dist:win` 的 `clean:release`/`build` 成功,**`package:backend` 被 PyInstaller 6.22.3 原生崩溃阻塞**(`find_binary_dependencies` 隔离子进程导入 `rapidocr.inference_engine.onnxruntime` 0xC0000005,1915 包顺序确定性复现)。按任务允许改用现有真实 0.1.0 backend 副本后,`package-sqlite`/`package:node`/`stage-electron`/`electron-builder`/`write-release-manifest` 全 exit 0。
- 产物:`Atlas-0.1.1-Setup.exe` 731,988,013 B,sha256 `94e71e…`;Atlas.exe `92d002…`;backend `13d8511e…`;sqlite 3.54.0 `5ca6a16…`;Electron 44.7.0;Node v24.21.0;内外清单 19 共享字段 0 漂移;installer.sha256 与 Setup 一致;NSIS payload 四受检文件与 win-unpacked 逐字节相同。真实启动成功,删清单/篡改 backend 均 exit 1(`manifest_missing`/`hash_mismatch`);迁移矩阵 A–F 与旧清单兼容按回执记录。
- **真实用户环境副作用(未修)**:0.1.0 隔离安装(在收到“不得改真实 Start Menu”约束前完成)覆盖了真实 Start Menu `Atlas.lnk`——原 `d59862…`(备份已在 `.par10-t6-5-sandbox/user-shortcut-backup/StartMenu-Atlas.lnk`,主会话核实哈希 `D59862EC…`)→ 当前 `780F52…`,target 指向沙箱 `install-0.1.0-upgrade\Atlas.exe`;Desktop 未变(`0831ce1b…`);HKCU 卸载项 `dd62424e-…` 保留。按任务书约束:**保留备份,暂停当前用户下的安装器/卸载器/注册表清理**,不再改真实 Start Menu;后续仍待维护者决定清理/恢复。0.1.1 真实安装/升级因 NSIS 编译期固定创建 Start Menu 快捷方式记为阻塞;仅做文件级升级模拟。
- 回执 `evidence/par10-t6-5.md`。**状态 PARTIAL(构建除 backend 阶段/真实安装阻塞/用户环境副作用已知)。**

### T6-9 收件(PAR10_REVIEW T6-9 READY)

- **T6-9 · Windows 文件锁下的工作树恢复**(`zcode-par10-worktree-windows-lock`):T4 D2 最小差异按 sha256 移入;新增 `test_conversation_worktree_windows_lock.py` 4 个 unit,独立 holder 进程真实持有 checkout/admin 句柄(`WinError 32`,180s 硬超时,`try/finally` 释放)。
- 真实占用:创建记录失败+文件占用 → `rollback_failed` + 准确 path/branch/base/reason + recovery row;占用期间 retry/explicit recovery 均 409;释放后 explicit recovery 与 retry create 均 200、marker 清除、可重新 create;他树/非受管路径拒绝且文件未删;正常 create/status/merge/delete 与快照通过。发现并最小修复 prunable registration 永久 409:仅 retry/recovery 路径 `_cleanup_worktree_residue(..., allow_prune=False)` 执行 `git worktree prune` 后复用 orphan 清理;rollback 路径仍保留 Git 列表;归属/规范路径/TOCTOU 不变。
- 主会话复跑 **24 passed(exit 0)**(4 真实句柄+19 D2+1 snapshot);子代理另 3 次稳定、wave2 6/memory 16/合并 23;无残留 holder 进程。平台边界:单 checkout 句柄时 git 2.55.0.windows.3 先删 admin entry,需 checkout+admin 双句柄才复现 prunable 残留。回执 `evidence/par10-t6-9.md`。**状态 verified。**

### T6-10/T6-11 派发(PAR10-T6-10-11-CONTINUE)

- 当前无活跃旧包(T6-5/T6-9 已终态),两个空位按任务书启动:**T6-10** `zcode-par10-render-slots`(B-F03-RENDER-02;独占 `App.tsx`+新 slots 模块,真实组件槽/重复裁决/卸载/独立扩展);**T6-11** `zcode-par10-shortcut-reference`(B-F03-SETTINGS-07;独占 `main.tsx`+ShortcutsPanel+新参考覆盖层,复用 T4 快捷键文件与现有录制/持久化)。两包文件归属互斥,均不碰主树。当前 2/5。

### T6-10 收件(PAR10_REVIEW T6-10 READY)

- **T6-10 · 渲染扩展槽**(`zcode-par10-render-slots`):新增 `frontend/src/renderer/slots/` —— `SlotRegistry`(single/list、declare/register/unregister/unregisterScope/renderSlot、订阅快照、幂等 disposer;首个注册占用,不同 id 重复注册抛错,同 id 原地替换)、`SlotOutlet`、`builtinSlots`。`App.tsx` 真实接入:应用根改为 `app.root` single/root 槽(`atlas.app-root`),原 `ErrorBoundary+AppContent` 成为贡献;`DiagnosticsFloatingOverlay` 改为 `shell.diagnostics` 槽,保留 `apiBaseUrl`/布局/样式/错误/启动。`main.tsx`/`ShortcutsPanel` 未改。
- 主会话复跑槽定向 **3 files/14 tests passed**、全量 renderer **84 files/382 tests passed(exit 0)**、`tsc -p tsconfig.renderer.json --noEmit` **0**。子代理 Vite dev+Playwright 真实入口:`#root` 渲染 32631 字符,派发 `atlas:toggle-debug-overlay` 后诊断浮层可见(`overlayCount=1`),`pageErrors=[]`,组件栈 `App→SlotOutlet→AppRoot→AppContent`。
- 主树 `App.tsx` 在途仅 2 处无关 hunk(导入/reply memo),与本包 3 hunk 无文本重叠;主树未触碰。未覆盖 Electron 进程探针、生产 build、嵌套子槽层级。回执 `evidence/par10-t6-10.md`。**状态 verified。** 当前 1/5,仅 T6-11 在跑。

### T6-12..T6-15 派发(PAR10-EXECUTE-12-15,四个空位一次补齐)

- T6-11 保持运行;四个空位分配给已授权四项,当前 **5/5**。所有新树从 `060071ab` 起,源写者均已停止;T6-12 明确不读/不复制 T6-11 未收件改动。
- **T6-12** `zcode-par10-product-candidate`:组合 T4 桌面候选、T6-4 BIFF8、T3 工作区技能、T6-10 渲染槽的最小已验差异;处理 App.tsx(T3 工作区重查 vs T6-10 root slot)与预览入口(T4/T6-4 registry/FilesPanel)交叠;按正常 Electron/renderer+本地后端临时数据跑 CSV/BIFF8/双窗快捷键/技能作用域/槽,继续 D 路由快照。任务书 §T6-12。
- **T6-13** `zcode-par10-backend-package-fix`:从 `build-backend.mjs` 复验 PyInstaller rapidocr/onnxruntime 0xC0000005,隔离单进程收敛根因,采用最小脚本/配置/依赖组合修复;验证本树源码 backend、临时进程 `/health`、OCR/ONNX 入口保留;禁止改系统 Python/安装器。任务书 §T6-13。
- **T6-14** `zcode-par10-plugin-version-ui`:从 T6-6 候选移入 backend 集成,在现有扩展设置组件接版本/依赖/预发布/错误状态;产品 adapter+正式 HTTP,临时回环 registry,故障保留配置,安装回归;区分页面接线/真实 registry/主树未集成。任务书 §T6-14。
- **T6-15** `zcode-par10-vision-token-accounting`:从 T6-7 移入网格与 router 预算,接正式 `route_image_pricer`/usage;文本与图像分离、base64 不重复计文本、实际 usage 优先;真实小图+本地夹具,不付费调用;未验证 provider 明确标出。任务书 §T6-15。
- 回执均写各自 `evidence/par10-t6-1X.md` 末行 `PAR10_RECEIPT <包号> READY|PARTIAL|BLOCKED`;主会话逐项复跑并报 `PAR10_REVIEW`。

### T6-16 已授权待派(PAR10-T6-16-RENDERER-BOOT)

- 五名(T6-11..T6-15)均在跑且无回执,按“同时最多五名”不超发。候选树 `zcode-par10-renderer-boot` 已从 `060071ab` 预建,QUEUE 行状态 `queued`;任务书 `PAR10-T6-16-RENDERER-BOOT.md`(B-F03-RENDER-08:独立清单解析/阶段排序、真实 renderer 装配、重复/缺失/未知批次、损坏诊断、旧无清单入口、renderer tsc+Vite 生产构建+启动证据;不碰 T6-12 App.tsx/T6-11 入口)。
- 已启动后台监听器轮询五包回执;任一终态出现即在同一调度回合启动 T6-16,不等待全员。

### T6-15 在途修正 / T6-11 独立复验 / T6-17 排队

- **T6-15**:Codex 独立复跑 `test_image_tokens.py`/`test_model_router.py`/`test_token_meter.py`/`test_token_meter_anchor.py` 为 **152 passed,1 failed**;失败 `test_surface_meter_prices_each_node_and_route_images`——`price_surface_nodes` 的 nodes 每项多出 `visual_tokens`,与既有精确结构断言不符。已把“保留逐节点结构、只在被消费的相容层暴露图像合计、修后四文件全过并验真实回环 usage 优先”的修正要求发给 T6-15 代理,等待其回执。
- **T6-11**:Codex 独立复验 14 项、tsc、真实渲染入口 `Ctrl+/`、冲突拒写、FastAPI 保存、即时命令面板、刷新恢复均通过;已要求代理把独立结果补进 `par10-t6-11.md` 并收尾,避免重复改动。
- **T6-17 排队**:任务书 `PAR10-T6-17-PAIRED-CURRENT.md` 已读;候选树 `zcode-par10-paired-current` 已从 `060071ab` 预建,QUEUE 行 `queued`。范围 `S-PENDING-01`:Atlas/DSH 同网关同 wire model/同输入/同判定,回环+临时目录,最多 8 真实回合、至多一次恢复;先核对官方 DSH 可运行版本与 Atlas SHA,不切账户/不改配置。**T6-16 优先,其次 T6-17。**
- 当前 **5/5** 仍无回执;监听器与两棵排队树就绪,首个终态补 T6-16,第二个终态补 T6-17。

### T6-11 收件(PAR10_REVIEW T6-11 READY)

- **T6-11 · 快捷键参考与录制入口**(`zcode-par10-shortcut-reference`):全局 `Cmd/Ctrl+/` + 设置→快捷键可见入口;新参考覆盖层复用 Atlas 样式(搜索/分组/行内录制/添加/清除/恢复/全部恢复),走既有 `KeybindingsSync`/`/api/u6/keybindings`,无新存储;录制态由 `[data-shortcut-recorder]` 抑制,`Ctrl+/` 被录制器捕获不叠层;模态互斥按 `settings/shortcuts`,其它 dialog blocked(reason=modal);顶层参考层吞 App 级快捷键并可按 `Ctrl+/`/Esc 关闭。探针发现并修复参考层与设置面板各自 `KeybindingsSync` 的同窗 409:新增 `KeybindingsProvider` 共享控制器 + 单测。
- 主会话复跑定向 **6 files/50 tests**、全量 **86 files/415 tests**、u6 pytest **7 passed**、renderer tsc **0**;子代理隔离 Electron 44.7.0 探针 **15 阶段 PASS/problems=[]**,真实 `Ctrl+/`、录制抑制、modal、PUT 落盘、刷新恢复均实测。候选仅 `main.tsx`/`ShortcutsPanel.tsx`/新 `shortcuts/` + T4 已验 7 文件;`App.tsx`/slots 未动。回执 `evidence/par10-t6-11.md`。**状态 verified。**

### T6-14 收件(PAR10_REVIEW T6-14 READY)

- **T6-14 · 插件版本界面**(`zcode-par10-plugin-version-ui`):T6-6 后端差异按 sha256 移入;`ExtensionCatalogPanel` 插件行新增 `PluginVersionPanel`(当前版本/newer_versions 升级/peerDependencies/deprecated/dsh/预发布/检查与安装错误/安装所选版本/取消/构建批准),经产品 BackendAdapter 走正式 HTTP,不直连 registry。
- 主会话复跑后端 combined **158 passed**(114+15+29+snapshot)、前端全量 **84 files/380 tests**、adapter **25 passed**、renderer tsc **0**;子代理真实 uvicorn+回环 registry 6/6(授权回退、错误恢复、2.0.0 安装/回退)。install-ops 20/6 与 T6-6 同基线抖动,不计功能通过。未启动真实 Electron、未访问真实 npm/私服/凭据;主树未集成,合并需重冻结快照。回执 `evidence/par10-t6-14.md`。**状态 verified。**

### T6-16/T6-17 已补位(当前 5/5)

- T6-11 与 T6-14 终态释放两个工位:T6-16(`zcode-par10-renderer-boot`,B-F03-RENDER-08)先启动;T6-17(`zcode-par10-paired-current`,S-PENDING-01 同网关同 wire model 配对,≤8 真实回合)第二个启动。T6-12/T6-13/T6-15 继续在跑。**当前活跃:T6-12、T6-13、T6-15、T6-16、T6-17。**

### T6-14 定向返工排队(Codex 在途验收)

- 反馈:`PluginVersionPanel.tsx` 起始安装时 `install=null`、`inFlight=false`,快速双击可重复派发;轮询期普通运行态禁用取消;取消 HTTP 直接返回终态时 `cancelInstall` 不清 `installing`,下次安装一直禁用;超时文案承诺刷新但无查询入口。
- 已定位代码:`installSelected` 先 `setInstall(null)` 再 await、无同步 ref 守卫;`follow` 在前台轮询且 `installing` 常真;取消按钮 `disabled={installing && status!=='awaiting_approval'}`;`cancelInstall` 终态分支不 finally;`follow` 无 generation/abort,旧响应可覆盖终态;超时文案“可稍后用刷新查看”无对应调用。
- 修复要求(等首个终态腾位即恢复同一 T6-14 代理):同步 ref 防重复派发;拆分 starting/following/cancelling/approving,运行/排队中取消可用;取消终态立即清忙并重置守卫;follow 用 generation/AbortController 忽略旧响应与终态后响应;超时提供 `GET /api/plugins/install/{request_id}` 查询入口(现有路由 `plugins_router.py:165`)或按实际改文案;测试覆盖双击单派发、运行中取消、取消终态清忙、旧轮询不覆盖、超时动作。当前 5/5 不超发,首个终态先修此包,再考虑新派。

### T6-15 收件(PAR10_REVIEW T6-15 READY)

- **T6-15 · 视觉 token 生产计量**(`zcode-par10-vision-token-accounting`):从 T6-7 移入 `image_tokens.py`/测试与 router 预算,接入 `token_meter.price_surface_nodes`/`route_image_pricer`、`model_call` 输入估算和 `loop` usage 投影;文本与图像分开,图像 payload base64 从文本估算剔除;`price_surface_nodes` 的 nodes 保持 `{seq,tokens,heuristic_tokens}` 精确结构,图像合计只在结果顶层 `image_tokens`;provider 实际 usage 优先于网格估算。前端 `TokenUsage`/`runInsights` 增加视觉 token 展示。
- 主会话复跑四文件 **153 passed(exit 0)**、集成 `test_vision_token_accounting.py` **15 passed(exit 0)**、前端 token 展示 **2 passed**、renderer tsc **0**。集成覆盖本地回环 provider `usage=999` 优先、base64 不计文本、文本回归、URL/内联同语义。未消耗真实付费 provider;未验证真实 provider usage。
- 代理在写出 READY 回执后仍继续更广回归;为维持最多 5 并发,主会话按回执+复验收件后停止该代理(产物未回退)。回执 `evidence/par10-t6-15.md`。**状态 verified。**
- **T6-15 修正确认(代理回报)**:`price_surface_nodes` 的 nodes 已恢复原有精确结构 `{seq,tokens,heuristic_tokens}`,不再加 `visual_tokens`;图像合计仅放结果顶层 `image_tokens`(由 loop 的 `run.usage`/`surface_image_tokens` 消费)。四文件复跑 **153 passed/0 failed**(image 65+router 65+token_meter+anchor),新增集成 15 条含本地回环 `usage=999` 优先、base64 不计文本、文本回归;代理仍在跑更广回归并收尾回执。

### T6-13 收件(PAR10_REVIEW T6-13 READY)

- **T6-13 · backend 打包修复**(`zcode-par10-backend-package-fix`):根因=`winrt-runtime 3.2.1` 包内旧 `MSVCP140.dll`(14.29.30157)被 `winrt.runtime`(第 1321 包)先加载,随后 onnxruntime 1.31 pybind 绑定旧运行库,在第 1483 包 `rapidocr.inference_engine.onnxruntime` 触发 0xC0000005(系统 runtime 14.51.36247)。修复仅在 `frontend/scripts/build-backend.mjs` 加 `--exclude-module winrt`(+8 行,含原因);Atlas backend 不 import winrt,Hermes Store 助手走独立 payload Python。
- 验证:修复前实际入口 EXIT=1/3221225477;修复后 `node build-backend.mjs` 与完整 `npm run package:backend` 均 EXIT=0(可重复);PYZ 保留 83 个 rapidocr 模块(含 `inference_engine.onnxruntime`)与 onnxruntime pybind、cv2,无 winrt;`package-sqlite` SQLite 3.54.0 0;Codex 独立启动新 backend `/api/health` **200/ok**。主会话健康探针因 C 盘 0 字节在写临时文件阶段失败(环境原因,非产品),已由 Codex 独立证据补足。候选只 1 个打包脚本文件。回执 `evidence/par10-t6-13.md`。**状态 verified。**

### T6-14 返工收件(PAR10_REVIEW T6-14 READY)

- **T6-14 rework**(`zcode-par10-plugin-version-ui`):`installGuard` 同步 ref 防双击重复 POST;拆分 starting/following/cancelling/approving,queued/running/awaiting_approval 均可取消,仅取消请求在途禁用;取消直接终态立即清忙/释放守卫;每次安装/取消/批准/查询递增 generation+AbortController,取消中止 follow,旧轮询因 generation 不匹配丢弃;adapter/UI 新增 `GET /api/plugins/install/{id}?wait_ms=0` 查询,超时文案改为可点击“查询安装状态”,查询后继续 follow 或终态。
- 主会话复跑前端全量 **84 files/383 tests**、adapter **26 passed**、renderer tsc **0**;后端 158 未变;子代理 vite build/真实 uvicorn+回环 6/6、`git diff --check` 0。新增测试覆盖双击单派发、运行中取消、取消终态解除禁用、旧轮询不覆盖、超时查询/abort。回执 `evidence/par10-t6-14.md`。**状态 verified。**

### C 盘耗尽事件与 D 盘恢复(2026-11-19)

- C: 两次归零导致 T6-12/16/17/18 代理无回执终止(`TaskOutput` 已无任务)。C: 现约 4G/201G,D: 63G。
- 按用户约束,五包全部以 D 盘临时目录重启/续跑:**T6-12** 从已有 23 文件集成产物续跑;**T6-16** 从已有 `boot/`+main.tsx/vite 实现续跑(Codex 独立 48 项/tsc/生产 Chromium 正常-损坏-旧启动已过);**T6-17** 树干净、重新配对(≤8 回合);**T6-18** 树干净、用 T6-13 新 backend 做发行候选;**T6-19** rc.5 搜索路由新树。所有子进程 TEMP/TMP/TMPDIR、Electron profile、测试 basetemp、构建/缓存/产物均指向各树 `.tmp`/D 盘,不写 C 临时目录。
- **当前活跃 5/5**:T6-12、T6-16、T6-17、T6-18、T6-19。T6-13/T6-14 已 verified。

### T6-16 收件(PAR10_REVIEW T6-16 READY)

- **T6-16 · 渲染启动清单**(`zcode-par10-renderer-boot`):`renderer/boot/` 覆盖 B-F03-RENDER-08——`rev`/release 版本校验、entry/batch/依赖重复与缺失 loud 拒绝、bootstrap→application 固定阶段+相位内 dependsOn 拓扑排序、环/反向依赖拒绝、无清单 legacy 与 `?atlasBoot=legacy` 旧入口、损坏 `{code,path,message,hint,recoverable}` 诊断与兼容恢复、只接受 `./` 本地构建 URL 且运行时从不 fetch/import 清单 URL(静态 `LOCAL_BOOT_MODULES`)。
- 主会话复跑 boot 定向 **5 files/48 tests**、全量 renderer **86 files/416 tests**、renderer tsc **0**;子代理实际 Vite 生产构建 EXIT 0(`rev=atlas-boot-eed0730c`,5 entries,写 `dist/boot-manifest.json`),真实 Chromium 正常/损坏/旧启动三路 `pageErrors=[]`,真实 Electron 44.7.0(生产 dist+真实 preload+独立 profile)**10 阶段 PASS/problems=[]**。Codex 独立 48 项/tsc/生产构建一致。未覆盖完整 Electron 主进程/file:// 与完整后端;候选未合并。回执 `evidence/par10-t6-16.md`。**状态 verified。**
- **T6-20 补位**:T6-16 终态释放工位后启动 `zcode-par10-plugin-install-windows`;任务书 `PAR10-T6-20-PLUGIN-INSTALL-WINDOWS.md`,从 T6-14 已验候选接续;先区分 Codex 22/4 中 3 个真实旧失败与缺 `ATLAS_PNPM_ENTRY` 的第 4 项,再追踪真实临时仓 staging→replace→patch carry→revert,Windows 锁/重复请求保持旧版本可读/可重试;D 盘 TEMP/TMP。当前 5/5:T6-12/T6-17/T6-18/T6-19/T6-20。

### T6-20 已授权待派(PAR10-T6-20-PLUGIN-INSTALL-WINDOWS)

- 任务书 `PAR10-T6-20-PLUGIN-INSTALL-WINDOWS.md`;候选树 `zcode-par10-plugin-install-windows` 已从 `060071ab` 预建,QUEUE 行 `queued`。任一首终态即领取,不超发第六名。
- Codex 独立复跑 `test_plugin_install_operations.py` 为 **22 passed/4 failed**,日志 `D:\Atlas\.worktrees\_codex-par10-probes\plugin-install-regression\pytest.log`;任务书要求先区分 3 个真实旧失败(Git 同仓重装 PermissionError、升级读到旧 v1 的 patch-carry、市场源批准后安装失败)与第 4 项缺 `ATLAS_PNPM_ENTRY`。从 T6-14 已验前端/后端候选接续,保留版本信息/取消/并发去重/构建批准;用真实临时仓与正式安装执行器追踪 staging→replace→patch carry→revert,Windows 锁/重复请求保持旧版本可读、终态可验、可安全重试;校验同名插件配置/补丁迁移。所有子进程 TEMP/TMP/依赖/数据根在 D 盘。
- T6-19 任务书补充:缓存按模型路由隔离;现有 Web 工具基线 **6 项已由 Codex 独立通过**。
