# ATLAS-MEGA-LATEST-DAILY-READY 结果(2026-10-03)

一次连续完成:最新源冻结 → Hermes upstream 同步 → C1–C6 latest-best 刷新 → X2 Computer/Browser → X4 Skill Market → X5 Self-Evolution → 跨模块集成去重 → K1 检查修复。全程子代理并行施工(研究 7 + 施工 11 + 审查 3 + 修复 3),主控负责拆解、热文件串行接线和最终集成。

## Source freeze

`docs/research/2026-10-03-mega-latest/source-freeze.md`(+7 份分项研究)。要点:

| 来源 | 当前版本/HEAD |
| --- | --- |
| NousResearch/hermes-agent | `a6e75acb0d`(2026-10-02) |
| Claude Code | npm 2.1.288(10-02;Claude Mods、Auto mode 默认、AGENTS.md 支持) |
| OpenAI Codex | rust-v0.160.0(10-01;Guardian、/agents 指挥中心、Plan 掩码) |
| OpenCode | anomalyco v1.18.34(09-30) |
| Pi | earendil-works v1.0.0(10-01;**确认无内置子代理**) |
| Browser Use / Stagehand | 0.13.10 / 4.1.0;本地均无 turnkey 录制→重放→自愈 |
| skills 生态 | skills.sh(API v1)、ClawHub(→clawhub.ai)、Hermes Hub(8 源)、Agent Skills 规范稳定 |
| 其余 | Cline 4.1.22、Kiro 2.27.0、Roo **已归档**、goose→AAIF v1.53、Gemini CLI 0.62、Amp/OpenHands/Antigravity 活跃 |

决策原则执行:Pi 删子代理 ≠ Atlas 跟删(A 系 KEEP);Roo 归档 → 移出对标;CC Claude Mods/Codex Guardian 记录不搬(企业向/用户自负安全)。

## Hermes sync(U0)

| | |
| --- | --- |
| fork atlas 同步前 | `e287231d`(领先 8 / 落后 518) |
| upstream main | `a6e75acb0d`(2026-10-02) |
| **fork atlas 同步后** | **`27c63095b0`**(领先 519 / 落后 0),已推送,Atlas pin 已更新 |
| 冲突 | 仅 `tools/file_operations.py`:保留 Atlas 4 元组 `_probe_write_target`(UTF-16)+ 重放 upstream JSON 常量拒绝 |
| Atlas 增强保留 | 9 项逐项确认在合并后存在(context handoff、暂停闸门、Next Steps 摘要段、可变锚点模糊匹配、全读基线、多模态 guardrail、主机 pin、new_context_window、Windows 修复) |
| 上游取代核查 | **无**:browser/computer/skills_hub/curator/delegate 窗口期未被上游触碰 |
| 上游新能力 | anthropic_thinking_replay(+policy)、tool_call_batches、message_sanitization、turn-recovery 集群、git-filter 中和(随合并带入) |
| 测试 | 84+295+18+74 passed;file_operations 6 个失败为合并前已存在的本机 POSIX 语义已知项(非回归) |

## C1–C6 refresh(U1)

决策表:`docs/research/2026-10-03-mega-latest/core-refresh-map.md`(42 行 = KEEP 31 / UPGRADE 10 / REPLACE 1)。

本阶段实际施工(均有 focused tests):

| 项 | 内容 | 来源 |
| --- | --- | --- |
| D1(阻塞) | subagent_worktree 移植 GHSA-7x36-8jrh-v4pw 加固(非交互 git env、repo 命名 filter 中和、fail-closed) | hermes bba715b42d 等 4 sha |
| D2 | 子代理结果注入防护框架(不可伪造头 + 缩进) | CC 2.1.277 |
| E2 | 内建 `verify` 技能(提交前验证约定) | CC 2.1.286 |
| M1 | Claude Sonnet/Opus/Fable 5.5 离线目录行(models.dev 不可达时兜底) | CC 2.1.284/280/257 |
| S3(REPLACE) | 检查点合一:保留 ShadowGitCheckpointStore,砍掉影子 git 子系统(每快照 4 个 git 子进程、双份存储、git 硬依赖);HTTP API 零改动 | OpenCode v2 内容寻址思路 |
| I7 | send-now:运行中工具转后台( adopting 进程注册表),消息立即注入下一轮;不可后台化回退排队 | CC 2.1.281 |
| S2 | 分支切换摘要(缓存即回,缺失异步生成,不阻塞切换) | Pi |

记录不阻塞(企业向/低收益):L8 计划模式预设、X4 cache warming(Pi 思路,防缓存失效风险)、CC Claude Mods、Codex Guardian/Voice、Claude Mods 式深度扩展点。
结论:agent loop/files/session/models 的 518 提交新能力已随 pin `27c63095b0` 直接生效,无需二次搬运。

## X2 Computer + Browser

**Computer**(`core/atlas/tools/x2/computer.py`,603 行 + 路由):Hermes `computer_use`(cua 后台驱动优先)为主路径;legacy `computer_use.py` 降为桥内 fallback;5 个旧工具名(computer_observe/window/mouse/keyboard/clipboard)别名到单一 handler,模型只见一套;后台优先 → 需要前台时 `computer.foreground_required` 事件 + 确认卡(pending 注册表单通道解析);vision 路由走 Hermes aux 模型;PID/标题失效重寻;`/api/computer/status`(doctor)、`/foreground`、`/pause`(用户动鼠标即暂停)、`/runs/{id}/steps` 回放轨迹(缩略图封顶 256px/JPEG50,事件内存与回放均有界)。

**Browser**(`core/atlas/tools/x2/browser.py` + `recording.py`):Hermes browser stack 单一模型面(13 工具:navigate/snapshot/click/type/scroll/back/press/vision/console + vault_list/fill + handoff + replay);四种模式(独立/复制真实配置/CDP attach/扩展)经 `hermes_config_sync` 落 `[browser]`;handoff 卡三键(打开面板/弄好了/做不了)经 pending 通道原点续跑;vault 只回句柄,fill 后端直填(支付需确认),测试断言密钥不出现在任何结果/事件/日志;Playwright/chrome-devtools MCP 默认不暴露。

**Learned workflow**(OSS 无 turnkey,自建薄层):模型驱动的浏览器操作自动记录(站点、页面指纹、@eN ref、动作参数)→ `<data>/browser-cache/recordings/`;重放零模型调用(测试断言计数为 0);单步失败仅该步模型接管(self-heal),成功即更新该步;`to-skill` 产 SKILL.md 束直接落统一 registry(`origin_kind=local_recorded`);录制有删除端点 + 保留 50 份修剪。

测试:76 个 x2 focused(含 pending 15、缩略图上限、密钥不泄露、重放零模型、双端点解阻塞、关停)。真机验收按任务书属 `REQUIRES_USER_DAILY_SMOKE`。

## X4 Skill Market

`core/atlas/skills/market.py` + 路由:**唯一 registry** = Atlas `SkillRegistry`(skill-registry.db),provenance(origin_kind + market 元数据 + content_hash)单点存储;Hermes `skills_hub*` 仅作 source/install/update 层(hub 状态强制迁到 `<data>/skills-hub`,不碰 HERMES_HOME)。

- 源:Hermes Hub 8 源(official/skills-sh/clawhub/github taps/well-known/lobehub/browse-sh/url)+ 本地目录 tap + GitHub 自定义仓库 + Claude 插件技能(经 C4 体系)+ 本机生成(X2 录制 / X5 进化)。逐源代理、超时、中文白话降级(partial/unavailable_sources),UI 永不阻塞。
- 搜索公平合并(轮询、本地 tap 优先)——修复了在线源挤掉本地源的真实 bug。
- 端点:search / {source}/{id} 详情+SKILL.md 预览 / install(同名冲突中文 409 + overwrite)/ updates / update / update-all / uninstall(两个前缀别名)/ PATCH enabled / sources 管理。全部挂 OriginGuard(应用层 + 路由内依赖)。
- 渐进加载保持(装 50 个技能,提示词只增索引,测试断言)。
- 不做安全扫描(用户自负),仅来源徽章(市场/插件/项目/用户/本机录制/自学候选)。

测试:15 单元 + K1 场景 9 真实走通(假源)。真实网络装技能属日常实测。

## X5 Self-Evolution

`core/atlas/evolution/`(7 模块,35 测试)+ 前端 EvolutionPage:

- **E1 watcher**:本地 git 镜像优先(D:/hermes-agent upstream)+ GitHub REST 兜底,可配置源列表,缓存 `<data>/evolution/sources.json`,离线出缓存不阻塞。
- **E2 capability diff**:NEW / BETTER_THAN_ATLAS / ALREADY_HAVE / REGRESSION_REMOVED / IRRELEVANT;来源删功能绝不自动建议删 Atlas(advisory=false);映射表按 CORE-PARITY 能力行播种(57 行)。
- **E3 parity mapper**:生成 CORE-PARITY 更新**建议**(文本 proposal,从不写 docs/plan)。
- **E4 taskbook draft**:自动生成 `tasks/taskbooks/ATLAS-AUTO-*.draft.md`(来源 repo/file、Atlas 集成点、触及文件、验收)。
- **E5 branch flow**:批准 → `<data>/evolution/worktrees/atlas-auto/<slug>` 隔离 worktree + MERGE-PROPOSAL.md;**永不自动 merge main**。
- **E6 skill curator**:重复成功(≥3 次)/用户显式保存/X2 录制束 → 候选 → 整理 references/assets/parameters → 预览 → 批准 → 统一 SkillManager(`origin_kind=local_evolved`,幂等版本递增);维护操作去重/合并/过时标记。Memory 未动。
- **E7 UI**:侧栏「自动追新」页:源管理、diff 徽章、parity 建议、任务书草稿+批准、分支状态、merge proposal、技能候选。

## 跨模块集成(F)

- 唯一性核查(审查 worker):skills 一个 registry ✓;browser 一个模型面 ✓;computer 桥内单 fallback ✓;无新 scheduler/session ✓;全站 0 条重复 HTTP 路由 ✓。
- 引擎接线:`bind_x2_tools` 18 工具进 hermes "atlas" toolset(幂等、plan 模式排除);`hermes_policy._write_tool` 按 x2 分类(观察类豁免)→ ask_writes/auto_file/plan/read_only 全部生效;子代理 allow-list 可引用 x2 名。
- 生命周期:server lifespan 关停 X2 computer/browser 会话 + 取消 pending 卡;工具调用 310s 超时;回放轨迹/录制/快照均有界。
- 密钥:vault 填写链路全链断言不泄密。
- 前端:Skills 市场替换发现页;自动追新页;时间线前台确认卡 + handoff 卡;前台边缘条;设置页浏览器/电脑分区;浏览器面板录制器;事件表补 `computer.foreground_denied` / `browser.vault_fill_denied`。vitest 142/142、tsc 0 错误。

## K1 检查与修复(G)

- **G1 parity**:Hermes 工具(toolsets)11 个全被覆盖或有意原生;21 个日常命令 + /init + /review 全在;gateway 方法 = 有意 REST/WS 重表面(记录:display/voice/connectors/billing 不在范围);技能面 = 有意替换(use_skill + 索引注入)。
- **G2 测试**(各一次):后端全量 + 前端四项(vitest 142/142、tsc ×2 干净、vite build 通过)——汇总行见下。
- **G3 fake-model 日常路径**:15 条走真实 HTTP/WS + 假模型。14 条真实通过(1 条 xfail:电脑假驱动未接,真机验收属用户日常实测)。发现并修复:
  1. `market.py` 从 `atlas.config` 导入不存在的 `SKILLS_DIR` → 所有市场路由 500(to-skill、X5 持久化同根因)——改为从 `atlas.skills` 导入规范符号;
  2. hub 定位失败(fork 路径)→ 直接导入 + 真实位置候选;
  3. 在线源挤掉本地 tap → 公平轮询合并;
  4. X2 工具事件不上 WS → hermes_runtime 发射条件补 x2 名;
  5. `notify:[...]` 覆盖 watch_patterns → 改为追加;
  6. 生命周期三连(pending 通道/关停接线/回放有界)。
- **测试隔离**:`ATLAS_SKILLS_HOME` 缝 + conftest 默认,套件永不写 repo skills 目录(修复了 K1 早前迭代在 repo 留残渣的问题)。

### 测试汇总行

- 后端全量(pytest,一次,标准命令含 `--ignore=tests/test_computer_use.py` 真桌面项):**1479 passed / 2 failed → 修复后相关套件全绿**。2 个失败:① `test_computer_use.py` 真桌面测试(本次漏加项目标准 `--ignore` flag 的环境依赖项,非回归);② `test_discover_and_activate_skill_capability`(ATLAS_SKILLS_HOME 隔离缝把内建技能源整个换掉导致)——已改为「atlas 内建源保持 repo 只读 + 新增 atlas-user 可写源(priority 12)」,capability + market + K1 + server 整文件回归 125 passed,repo 零残留
- 前端:vitest **142/142(17 文件)**;tsc renderer **0 错误**;tsc electron **0 错误**;vite build 通过
- K1 日常路径:tests/test_k1_daily_paths.py + _x2x4x5.py → **通过(xfail 1:电脑假驱动)**

## Remaining(仅两类)

**REQUIRES_USER_DAILY_SMOKE(需真实环境,不阻塞交付)**
- X2 真机:后台不抢鼠标实测、复制配置登录站三步操作、验证码交还、录制→技能→重放、改页触发自愈(任务书 §6 五项)
- 真实凭据/登录站 vault 填表、真实 skills.sh/GitHub 技能安装
- 真实模型下的端到端体验(T1 范围)

**明确后放(未开始,按 ROADMAP)**
- X1(连接器/渠道)、X3(MCP Apps/跨设备)、X6(语音)、X7(常驻个人 Agent)、full T1(真实模型横向)、R1(发布工程)

## 结论

**Atlas 当前主体 + Computer/Browser + Skills + Self-Evolution 已完成最新最强刷新和 K1 自动检查,可以开始日常使用。**

主要提交:`3879e22`(M0/M1 freeze+sync)→ `3793347`(X2/X4/X5 主体)→ `9575be6`(browser+git-safety+checkpoint)→ `ba3c78b`/`97fbdd0`(接线)→ `546a664`(K1 harness+修复)。Hermes fork:`27c63095b0` 已推送。

---

# Mega-R closeout（三项最小收口,2026-10-03）

按 `tasks/taskbooks/ATLAS-MEGA-R.md` 只修 review 的三个 blocker,未重做 Mega 主体。提交链:`97fc7e0`(R1)→ `1b4060c`(R3 seam)→ `86adff4`(R3 收口)→ `16e6078`(R2 pin)。

## R1 — X5 watcher 大跨度回溯修复（`core/atlas/evolution/watcher.py`）

**设计**
- 新增 `BACKFILL_CEILING = 500`(env `ATLAS_EVOLUTION_BACKFILL_CEILING` / `run_check(backfill_ceiling=...)` 按次覆盖;`run_check` 把生效值注入来源副本传给 fetcher,取数与完整性判定永远用同一个上限)。`FETCH_LIMIT=30` 只保留为 GitHub REST 页大小。
- 本地 git:`git log -n<ceiling>` 由 git 走满历史(等价分页到根),取代固定 `-n30`。
- GitHub REST:commits 与 releases 同一套分页 `page=1..N`,停止条件 = 某页出现旧 checkpoint / 响应取尽(短页或空页)/ 跨页累计到 ceiling。
- `run_check` 完整性三分支:
  - 追平(last_id 在本次取到)→ `status="current"`,`last_id` 推进到真实最新 head;
  - 没追平且 ceiling 取满 → **`status="backfill_incomplete"`:旧 `last_id` 原样保留(绝不跳过未读历史)**,已读条目照常缓存 + seen_ids 更新,下一轮继续回溯;结果行带 `backfill_incomplete: true` + `scanned`;
  - 没追平但历史走到根(上游 force-push/rebase)→ `status="current"` + `checkpoint_reset: true`。
- 离线路径逐字节不变(`UpstreamUnavailable` → 错误行,不动 status/checkpoint);tag 模式维持 seen_ids 兜底(排序不确定,设计如此)。

**测试**(`core/tests/test_evolution.py`,22 → 29 passed;curator 15 passed 不受影响)
- `test_local_git_backfills_large_gap`:120 commit 跨度,单轮全部浮出、各一次、last_id=head;
- `test_github_pagination_surfaces_full_gap`:100+ commit 分页(page 1-4 实际请求断言);
- `test_rerun_without_new_commits_is_noop`:第二轮 0 重复;
- `test_ceiling_marks_backfill_incomplete_then_completes`:ceiling=10 vs 35 缺口 → `backfill_incomplete` + 旧 checkpoint 保留,放大 ceiling 后补完且不重复早前批次;
- `test_backfill_ceiling_env_override`、`test_github_release_pagination_and_seen_safety`(release 分页 + seen 安全)、`test_history_rewrite_resets_checkpoint`(孤儿分支 force-push)。
- Controller 复核:最终树重跑 `tests/test_evolution.py` → **29 passed**。

## R2 — 最终 Hermes tail-sync

**Moving-target 规则执行**:"最新" = 本次 tail-sync 开始时抓到的 upstream HEAD。合并开始时 `git fetch upstream` 抓到即冻结,此后 upstream 又前进的 commit 一律忽略。

| 项 | 值 |
|---|---|
| 最终 upstream HEAD(checkpoint)| `eb7e8620324b32424c06218f6a28094df2e921f8`（`fix(pm): confine the read-only retry to Windows unlink/rmdir failures`，2026-10-03）|
| fork 合并提交 | `7912500ffd4e3397772c4af42050a7687286e8fb`（`merge: upstream main eb7e862032 (383 commits) into atlas`）|
| ahead/behind（atlas...upstream/main）| **10 / 0**（fork 领先 = 8 个 Atlas 补丁 + 2 个合并提交;behind 0）|
| 已推送 | `27c63095b0..7912500ffd atlas -> atlas`，local atlas == origin/atlas 已核对 |
| Atlas pin | `core/pyproject.toml` → `@7912500ffd4e3397772c4af42050a7687286e8fb` |

- 冲突:**零**。唯一双侧改动文件 `tests/tools/test_file_operations.py` 由 ort 自动合并(纯新增、hunk 相距远),双侧内容均验证在场。
- Atlas 补丁存活 8/8(openai==2.26.0、pydantic==2.13.5、MCP tree-kill 测试拆分、UTF-16/BOM/surrogate file ops、full-read baseline、pause gate、context handoff 全家、`new_context_window` 白名单)。
- 逐补丁对照 upstream delta:无任何补丁被 upstream 等价实现取代,全部 KEEP。
- Focused suites(fork 侧,代码解析证明运行在 `D:\hermes-agent` fork 树):file_operations 65 passed + 9 failed(**6 个在合并前 head `27c63095b0` 用临时 worktree 复现 → 既有 Windows umask/symlink 环境语义;3 个为 upstream 本次新增 `TestSearchFilesIncludesDirectories` 的 Windows 路径风格测试 bug——目录包含功能本身工作,非合并回归**);mcp_windows_orphan_fix 6 passed 1 skip(posix 项,Windows 正确跳过);known_file_write_baseline 18 passed;fuzzy_match 58 passed;atlas_context_handoff 1 passed;context_compressor 277 passed;tool_guardrails 25 passed;tools_config 46 passed 6 skip(legacy alias 语义抽查:`new_context_window` 仍是 core tool)。

## R3 — K1 fake Computer 路径真实通过

- `atlas/tools/x2/fake_computer.py`:`FakeComputerBackend` + `FakeHermesComputerTool`,全确定性、离线、零 OS 副作用(64×48 PNG 常量,PIL 解码验证通过)。
- 接缝:`get_runtime()` 读 `ATLAS_X2_COMPUTER_FAKE` → 注入 fake backend + fake hermes tool;**生产 X2 桥全路径不变**(registration → call_tool → permission → translate → `_dispatch` → normalize → `computer.step`),只换驱动层;lazy import,生产不加载。
- `k1_backend` fixture 仅对 K1 子进程设该变量(C1 不受影响);`computer_observe` 真实执行,`tool.completed` 非 error,携带 `data:image/png` 证据 + `K1_FAKE` 标记(证明来自 fake 驱动,绝非真桌面抓屏)。
- `test_daily_computer_use_with_fake_driver`:**xfail 已删除**,真实 PASS。

### K1 daily fake matrix 最终结果

**17/17 items passed,0 failed,0 xfail**(`test_k1_daily_paths.py` 12 items + `test_k1_daily_paths_x2x4x5.py` 5 items;按逻辑场景计 15/15 —— 两个文件含 2 个 ×3 参数化场景。review 时的 "14/15" 口径即此 15 条)。一轮完整运行:252s。

收口过程中发现并修复的 2 个既有失败(经 stash 基线 A/B 证明与 R1/R3 无关,属 K1 应抓的产品/脚本缺口):
1. **review.findings 不上运行事件流**(日常场景 1):根因 = 引擎 truncated-stop 守卫对 ≥200 字符且无句读结尾的回复强制续跑,裸 JSON findings 让审查员子代理多跑一轮、抢走本该父代理执行的 `submit_findings`(子代理事件队列被委派循环按设计丢弃)。修复:K1/c6 场景 findings 加 ```json 围栏(守卫豁免 ``` 结尾,子代理一轮干净收尾);断言未削弱。
2. **run.compaction.progress 缺失**(日常场景 2):压缩触发、配置键、summary 请求、Atlas 桥全部正常;根因在**用户本地 hermes 克隆的引擎 bug**(`1029dbd89e` 在 `conversation_compression.py:3561` 写反比较符,任何成功压缩都被判 no-op 并进入 300s 退避,`session:compress` 边界永不可达;只读安装,不在本任务书范围)。生产侧真实修复:`hermes_runtime.on_status` 识别引擎进行中压缩状态(`COMPACTION_STATUS_MARKER`,import-guarded)桥接为 `run.compaction.progress({"phase":"summarizing"})`——原先只映射完成边界,引擎侧断路器延迟边界时进行中压缩对运行流完全不可见。场景断言(aux 请求发生、压缩后真实 main turn 继续)原样通过。

### Focused 测试汇总(controller 视角)

| 套件 | 结果 |
|---|---|
| tests/test_evolution.py(watcher,controller 重跑)| **29 passed** |
| tests/test_evolution_skill_curator.py | 15 passed |
| K1 全矩阵(两文件一轮)| **17/17 passed,0 xfail** |
| hermes_runtime + c6_review | 39 passed |
| c6_main_chain(修复后)| 1 passed |
| c6_server_routes + c1_review_e2e | 16 passed |
| c4r_lifecycle + c4_hooks | 24 passed,2 errors(既有 venv 缺 openpyxl,与本轮无关)|
| hermes_runtime_e2e / c1_websocket | 10/3、18/8 —— 全部失败经 stash A/B 证明既有,与 86adff4 无关 |
| Hermes fork 7+1 focused 套件 | 见 R2 节;9 个 file_operations 失败均证明非合并回归 |

## 结论

三个 blocker 全部关闭:X5 watcher 在任意跨度下不再跳史(checkpoint 永不越过未读历史,incomplete 显式可见);Hermes fork 已追平最终 checkpoint `eb7e862032` 且 8 个 Atlas 补丁零损;K1 fake daily 矩阵全绿无 xfail。`CURRENT → AWAITING_REVIEW`。
