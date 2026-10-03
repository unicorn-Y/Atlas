# R8 研究报告：Skill Workshop / curator 继续升级方案

日期：2026-10-03 ｜ lane：R8 ｜ 状态：研究完成，未改任何代码

来源（冻结版本）：
- OpenClaw `D:\Atlas-persistent-sources\openclaw`，HEAD `3e5560873a4`
- Hermes fork `D:\hermes-agent`，branch `atlas`，HEAD `ef4571dec5`
- Atlas 本体 `D:\Atlas`，HEAD `a034bff`

---

## 1. OpenClaw Skill Workshop

### 1.1 定位与总体架构

Skill Workshop 是 OpenClaw"受治理的技能自我改写路径"：agent/操作者创建 **proposal**（pending 草稿，带内容、目标绑定、扫描状态、哈希、rollback 元数据），只有 apply 之后才变成 live skill。三条写入路径：

1. **显式 proposal**（`propose` 模式 / `/learn` / CLI / Control UI）——全部走 proposal 存储、哈希绑定、安全扫描、rollback 捕获。
2. **自治后台学习（experience review / self-learning）**——`auto` 模式下用普通文件工具直接维护 Workshop 目录（不建 proposal、不自动 rollback）；`propose` 模式下只产出 pending proposal。
3. **每周 collection review**——每 agent 一个系统 cron 任务，审阅者用根植于 Workshop 目录的文件工具整理技能集（保留有用流程、精简臃肿、合并重叠、删过时文件），无 collection 级事务/自动 rollback。

### 1.2 数据模型（proposal record，protocol schema）

定义在 `packages/gateway-protocol/src/schema/agents-models-skills.ts`（`SkillProposalRecordSchema`，schema id `openclaw.skill-workshop.proposal.v1`）：

| 字段 | 说明 |
| --- | --- |
| `id` | proposal id |
| `kind` | `create` / `update` |
| `status` | `pending` / `applied` / `rejected` / `quarantined` / `stale` |
| `title` / `description` | 元数据（description ≤160 字节） |
| `createdAt` / `updatedAt` | 时间戳 |
| `createdBy` | `skill-workshop` / `cli` / `gateway`（创建渠道） |
| `origin`（可选） | `{agentId, sessionKey, runId, messageId}` —— 回溯到产生它的 agent turn |
| `proposedVersion` / `draftFile`（`PROPOSAL.md`）/ `draftHash` | 草稿绑定 |
| `supportFiles[]` | `{path, sizeBytes, hash, targetExisted?, targetContentHash?}`（≤64 个，每个 ≤256KB） |
| `target` | `{skillName, skillKey, skillDir, skillFile, source?, currentContentHash?}` —— 目标技能绑定 |
| `scan` | `{state: pending/clean/failed/quarantined, scannedAt, critical, warn, info, findings[]}`，finding=`{ruleId, severity, file, line, message, evidence}` |
| `goal` / `evidence` | 自由文本上下文（学习动机） |
| `appliedAt` / `rejectedAt` / `quarantinedAt` / `staleAt` / `statusReason` | 状态迁移时间与原因 |
| `evaluation` | 插件评估器结果：`{id, proposedVersion, revisionHash, trigger: manual/apply, startedAt, completedAt, correlationId?, targetTreeSha256?, outcomes[]}`，outcome 带 `{pluginId, pluginVersion, evaluatorId, status: completed/skipped/error, result{summary, findings, metrics, decision: pass/revise/block, decisionReason}}` |

扩展字段（`src/skills/workshop/types.ts` 的 `SkillProposalRecord`）：`autonomousCapture`（自治捕获标记）、`originRunIds[]`（≤4096，中断恢复归因）、`originRunMutationCounts`、`draftFile` 支持 `generations/<id>/PROPOSAL.md`。

Rollback 记录（`SkillProposalRollback`，schema `openclaw.skill-workshop.rollback.v1`）：`{proposalId, writtenAt, targetSkillFile, action: create/update, previousContentHash?, previousContent?, supportFiles?[{path, existed, previousContentHash?, previousContent?}]}`。

事件账本（append-only）：`created / revised / evaluation_completed / applied / rejected / quarantined / stale`，每条带 `sequence`、`eventId`、`proposedVersion`、`revisionHash`、`actor`、`correlationId`、`payload`。

### 1.3 持久化（SQLite + 文件树双轨）

`src/skills/workshop/store-sqlite-schema.ts` 四张表：
- `skill_workshop_proposals`（proposal_id PK，record_json，owner_agent_id，kind/status/created/updated/draft_hash，origin_* 四列，applied/rejected/quarantined/stale_at，status_reason）
- `skill_workshop_proposal_rollbacks`（proposal_id FK，previous content/hash，support_files_json）
- `skill_workshop_proposal_events`（AUTOINCREMENT sequence，event_type CHECK，actor_json，correlation_id）
- `skill_workshop_collection_reviews`（历史 review 记录：backup_id、kept/written/dropped 名单）

per-agent 集合是**目录**而非复制实体：`<state-dir>/agents/<agentId>/agent/workshop-skills`（`src/skills/workshop/skills-root.ts` 的 `resolveWorkshopSkillsDir`）；`resolveWorkshopWatchRoots` 把该目录注册为 runtime 刷新 watch root（`src/skills/runtime/refresh-source-roots.ts`）。旧实现遗留 `<agentDir>/skill-workshop/collection-backups/<backup-id>/` 备份树（`manifest.json` 含 `skillDirs`/`resultSkillDirs`）。

### 1.4 关键文件与流程

- 工具层：`src/agents/tools/skill-workshop-tool.ts`（568 行）及同前缀的 `-schema/-helpers/-collection/-library/-patch/-presentation/-factory/-description`。agent 工具 `skill_workshop` 一个 action 枚举：`create | read | prepare_patch | patch | update | revise | list | inspect | evaluate | apply | reject | quarantine | history | restore_collection`；个人库另有 `list|read|create|update|share|unshare|transfer|activate|remove|rollback`。参数含 `expected_revision_hash`（乐观锁，拒绝过期编排步骤）、`correlation_id`（外部编排关联）、`goal/evidence`、`support_files`、`old_string/new_string`（单 span 补丁授权：`prepare_patch` 一次只能有一个活跃授权，被 `patch` 消费或失效）。
- 服务层：`src/skills/workshop/service.ts` / `service-propose.ts` / `service-evaluation.ts` / `service-query.ts`；存储层 `store.ts`、`store-proposal.kernel.ts`、`store-sqlite-*.ts`、`store-rollback.ts`、`store-transition.ts`；apply/reconcile 迁移 `apply-transition.ts` / `reconcile-transition.ts`；哈希 `proposal-hash.ts` / `revision-hash.ts`；扫描 `proposal-scan.ts`；插件钩子 `plugin-hooks.ts`（`skill_proposal_evaluate`、`skill_proposal_changed`、`skill_changed`）。
- 自治学习：`experience-review.ts` / `-scheduler.ts` / `-prompt.ts` / `-default.ts`（触发条件：turn 完成/被中断且非 provider 错误、≥10 次模型迭代、合法前台会话、runtime 上报 model 与 `skill_workshop` 可用性、30 秒静默、无活动 run；每审查一次机会、失败记录不重试、私有 detached session、共享后台工作预算）。运行时使用回执（usage receipt）防止前台修复未被本 run 使用的技能。
- 周维护：`src/cron/skill-collection-review-monitor.ts`（workshop 配置 → 系统 cron 的规范投影，7 天周期，不支持 runtime 时标记 `no-rooted-runtime` 禁用）、`src/gateway/server-cron-skill-review-jobs.ts`、`collection-review.kernel.ts` / `collection-review-state.ts` / `collection-backup.ts` / `collection-restore.ts` / `collection-rollback.ts`。
- Gateway 方法：`src/gateway/server-methods/skills-curator.ts`（`skills.curator.status`；pin/unpin/restore 已退役报错）、`skills-proposal-history.ts`、`skills-workspace-handler.ts`、`skills-install.ts`、`skills-upload.ts`、`skills-status.ts`。
- 学习提示词：`learn-prompt.ts`（`/learn` 先修订同名 pending proposal 或同名 live skill，无归属才新建，永不自动 apply）、`maintenance-prompt.ts`（周维护守则：先审计、一个过程一个家、保留独立任务、验证结果）。
- 自检：`src/commands/doctor-skill-workshop-*.ts`（automations/collection-backups/relocation/sidecars/sources/sqlite/workspaces）。

### 1.5 可借鉴要点

- proposal 状态机（pending→applied/rejected/quarantined/stale）+ 每步 revisionHash 乐观锁 + append-only 事件账本 + 独立 rollback 记录。
- `origin{agentId,sessionKey,runId,messageId}` 溯源与 `autonomousCapture` 标记。
- apply 时重新校验目标树哈希（drift 需重新评估）；critical 扫描 → quarantine 而非 apply。
- per-agent 集合 = 每个 agent 自己的 workshop 目录（一个 agent 一份 learned collection），共享技能（bundled/plugin/market）不复制。
- 三模式策略（off/propose/auto）+ 上限（maxPending=50、maxSkillBytes=40000）。

---

## 2. Hermes curator（fork `atlas` 分支）

### 2.1 组成

| 模块 | 行数 | 职责 |
| --- | --- | --- |
| `agent/curator.py` | 1212 | 背景技能维护编排器（非 cron：空闲触发） |
| `agent/background_review.py` | 1364 | 每轮 turn 后 fork 审查 agent，决定保存/更新技能与记忆 |
| `tools/skill_usage.py` | ~800+ | 每技能使用遥测与生命周期状态（active/stale/archived） |
| `tools/skill_ledger.py` | ~500 | append-only JSONL 变更账本 + before/after 快照 + rollback |
| `tools/skill_provenance.py` | 56 | 写入来源 ContextVar（foreground vs background_review） |
| `agent/learning_graph.py` / `learning_mutations.py` | 255/207 | 技能图（节点/related 边/密度统计）与图上编辑/删除 |

### 2.2 curator 机制（`agent/curator.py`）

- **确定性状态迁移**（`apply_automatic_transitions`，纯函数无 LLM，每次 idle tick 都跑）：按 `last_activity_at` 把 curator 管辖技能在 active/stale/archived 间迁移。阈值 `stale_after_days=14`、`archive_after_days=30`（config 可调，<1 回退默认）。置顶（pinned）跳过；cron 引用的技能视为受保护；use_count==0 且未过 stale 期限的永不归档（"缺乏证据≠过期"）；内置技能首次见到时 seed 基线记录让不活动时钟从当下起算。**只归档（移入 `~/.hermes/skills/.archive/`）从不删除**，归档可恢复。
- **LLM 整理 fork**（opt-in，`consolidate=false` 默认）：idle 且距上次运行 ≥`interval_hours`（默认 7×24h）时 fork 辅助客户端 AIAgent。提示词是"伞形归并"（umbrella-building）教程：前缀聚类 → 每簇判断"维护者会写 N 个窄技能还是 1 个带小节的类级技能" → 三种合并方式（并入现有伞 / 新建伞 SKILL.md / 降级为伞的 references/templates/scripts）。硬规则：不碰 bundled/hub/external 技能、不删只归档、跳过 pinned 与保护内置、delete 必须带 `absorbed_into=<伞名>`（驱动 cron 引用重写）、所有变更必须走 ledgered 的 `skill_manage` 工具面（shell mv 无账本 → rollback 恢复空壳，issue #96962）、写前强制 read（read-before-write enforced）。
- **运行收尾**：解析结构化 YAML（`consolidations: [{from,into,reason}]` / `prunings: [{name,reason}]`）与工具调用对账（`_reconcile_classification`）；diff before/after 名单；写 run 报告 `logs/curator/<YYYYMMDD-HHMMSS>/run.json + REPORT.md`；重写 cron job 的技能引用跟随合并。dry-run 横幅 + `hermes curator run --dry-run` 预览。
- **调度状态**：`~/.hermes/skills/.curator_state` JSON（last_run_at、last_run_duration_seconds、last_run_summary、last_report_path、paused、run_count）；首次观察 seed last_run_at 并推迟一个周期；`_claim_run()` 文件锁防并发实例。

### 2.3 使用遥测与账本（可复用部分）

- `skill_usage` 每技能记录（file-lock JSON）：`created_by, use_count, view_count, last_used_at, last_viewed_at, patch_count, patch_generation, last_reused_patch_generation, last_patched_at, created_at, state(active/stale/archived), pinned, archived_at, first_seen_at`；provenance 分类 `bundled / hub-installed / external / agent-created(curator-managed)`；`is_curation_eligible` 只让本地 curator 管辖技能进入整理。
- `skill_ledger.append_entry(action, skill, before, after, actor, evidence)`：JSONL，`before/after` 为 `[{path, sha256, blob}]` 快照（blob 存 blobs 目录），actor 可标记 `curator`（自治迁移）或派生自前台；支持 compact/trim、`pre-rollback` 条目、从备份回填快照（`fill_snapshot_from_curator_backup`）。
- `skill_provenance`：`set_current_write_origin("background_review")` ContextVar——curator 只整理自改进 fork 创建的技能，用户要求写的技能归用户（attended/unattended 正交门控）。
- `background_review.py`：turn 后守护线程 fork，继承父 runtime（provider/model/凭据/prompt 缓存），dispatch 侧工具白名单；取消握手（`_BackgroundReviewRun`）、输入 token 预算、写操作汇总与分类、usage 归账父会话。
- `learning_graph.py`：SKILL.md frontmatter 的 `related` 字段建边 + 记忆卡与技能的 token 交叠边 + 密度统计（孤立节点/簇）。
- 注意：`tools/skills_tool_dedup.py` 是**会话内 skill_view 重复读取去重**（mtime+size 指纹返回 stub），不是库级 dedupe——库级 dedupe 在 curator 的伞形归并里。

---

## 3. Atlas X4/X5 现状

### 3.1 SkillRegistry（`core/atlas/skills/registry.py`，666 行）——唯一注册表

SQLite 表（路径由调用方传入，server 装配）：

- **`skill_registry`**：`(name, version)` 主键，`metadata`（JSON）、`source`（自由字符串，如 `api`/`local`/`market:<hub>`/`<source>:<origin_kind>`）、`registered_at`、`updated_at`、`validation_status`、`status`。
- **metadata 字段**：必填 `name`（kebab-case）、`version`（semver）、`description`；可选 `capabilities, tools, requirements, examples, aliases, tags, category, keywords, use_cases`；外加两个受控对象：
  - **`provenance`**：市场安装写入 `{provider, external_id, source_url, origin_kind, installed_at, installed_path, computed_sha256, market{source, identifier, upstream_version, upstream_revision, content_hash, scope, installed_at}}`；本地写入 `{provider, external_id, origin_kind, installed_at, installed_path, computed_sha256}`。同版本 upsert 时保留既有 provenance（防外来覆盖）。
  - **`lifecycle`**：`{state: active/disabled/update-available/superseded/removed/rollback-available/quarantined, trust_state: unreviewed/trusted/revoked/blocked, pin_policy: unpinned/exact/hash, pinned_version, pinned_hash, content_hash}`。只能经审计 lifecycle 动作变更（`register()` 显式拒绝带 lifecycle 的元数据）。
- **`skill_lifecycle_history`**：append-only（BEFORE UPDATE/DELETE 触发器 RAISE ABORT），字段含 `event_id, name, timestamp, action, skill_version, previous_version/hash, resulting_version/hash, source, provider, trust_before/after, pin_before/after, approval_event_id, actor, reason, result, error_code, details`。
- **`skill_lifecycle_decisions` / `skill_lifecycle_approvals`**：两段式审批——decision 落库 → 用户批准签发一次性 token（token_hash、content_hash、current_hash、acquisition_id、target_trust_state、target_pin_policy、rollback_event_id、rollback_snapshot_hash、expires_at、consumed_at），`consume_lifecycle_approval` 校验全字段匹配 + 过期 + 单次消费。
- `commit_lifecycle_update`（同版本禁改 source 身份三字段 provider/external_id/source_url）、`commit_lifecycle_rollback`。

### 3.2 acquisition / review（X4）

- `core/atlas/skills/acquisition.py`（906 行）：`SkillsShProvider`（skills.sh 目录 + GitHub 源复核）、`inspect_github_source`（公开仓库校验）、`_parse_manifest`、`_validate_files`、`_security_scan`（PASS/WARN/BLOCK，含密钥正则 `_SECRET_VALUE_RE`）、`prepare_acquisition`、`payload_sha256`。市场安装前还有目录快照 vs 当前 GitHub 源的比对诊断。
- 审批流：`/api/skill-catalog/approve`（签发 install_authorization token）→ `/api/skill-catalog/install`（消费 token 落库），lifecycle 更新/降级/回滚同样走 decision+approval 两段式（`server.py:4742-5155`：decision、approve、update、install、remove、rollback、trust、pin）。
- 前端：`frontend/src/renderer/pages/skillAcquisitionReview.ts`（reviewGateState PASS/WARN/BLOCK、`localPackageReviewState`：new_skill/exact_version_conflict/update_candidate、lifecycleUpdateAction、approveSkillInstallation 两跳调用）。

### 3.3 市场与安装（X4）

- `core/atlas/skills/market.py`（1282 行）`SkillMarket`：搜索/detail/fetch 走 Hermes hub 适配器（`HUB_SOURCE_IDS = official, hermes-index, skills-sh, well-known, url, github, clawhub, lobhub, browse-sh`），**安装态只落 Atlas Registry**（注释明确"不建第二注册表/lock 文件"）。安装目录：user scope `<atlas_home>/skills/community/<name>`（source `atlas`，priority 10）、project scope `<workspace>/.claude/skills/<name>`（`claude-project`，priority 30）。
- **`ORIGIN_KINDS = ("marketplace", "plugin", "project", "user", "local_recorded", "local_evolved")`**（`DEFAULT_ORIGIN_KIND="marketplace"`）——注意任务书要求的 `local_recorded` / `local_evolved` **已存在**，缺 `agent_learned`。
- `SKILL_SOURCE_PRIORITY = {atlas:10, atlas-user:12, hermes:15, claude-user:20, claude-project:30, plugin:60}`（发现层去重优先级，`core/atlas/skills/__init__.py`）。
- `register_local(name, files, origin_kind, ...)`（market.py:1200 附近）：任意本地技能包按 origin_kind 注册；`save_local_skill_bundle` 供 evolution 复用。
- enable/disable 是**全局** lifecycle state 切换（`PATCH /api/skills/market/{name}/enabled` → `market.enable/disable` → `_record_event(action=enable/disable)`），无 per-agent 维度。
- 回滚：`rollback_skill`（lifecycle.py:491）+ `_snapshot`（rollback 快照落盘 + `rollback_event_id/rollback_snapshot_hash` 入审批记录）。
- 路由：`core/atlas/api/skills_market_router.py`（search/sources/install/update/update-all/uninstall/enabled 等）；`core/atlas/skills/distribution.py`（上传包 inspect）、`bundles.py`（PluginBundle 发现）、`dependencies.py`（依赖准备/安装）、`discovery.py`（打分搜索）、`lifecycle.py`（trust/pin/update/remove/rollback 全审计流）。
- 前端：`SkillDiscoveryPage.tsx`、`SkillsMarketPage.tsx`、`components/skills/{OriginBadge, SkillCard, SkillDetail, InstallButton, InstalledSkillCard, SourcesManager, UpdatesTab}`。`OriginBadge` 已有 `local_recorded`/`local_evolved` 配色（originLabel 在 `services/skillsMarketApi.ts`）。

### 3.4 evolution 模块（X5/X6）

- `core/atlas/evolution/skill_curator.py`（393 行，注释明说概念移植自 hermes curator/background_review）：`SkillCurator` 把候选技能存为 **JSON 文件** `<db 目录>/evolution/candidates/<id>.json`（`evolution_root()` = `get_config().db_path.parent / "evolution"`）。`ORIGINS = ("repeated_runs", "user_request", "recording_bundle")`，`STATUSES = ("candidate","approved","rejected","stale","merged")`。字段：`id,name,description,origin,status,references,assets,parameters,source_runs,use_count,pinned,last_used_at,provenance{source_version,created_at,updated_at,history[]},created_at,updated_at,approved_at`。`create_candidate` 同名自动合并（引用/资产并集、run 数累加、history 追加、stale 复活）；`maintain()` 去重合并（同名主记录吸收、`merged_into` 标记、从不删除）、按 `source_version` 标 `outdated`、按闲置标 stale；`approve()` → `to_skill_bundle()` 返回技能包 dict；`mark_used()` 回写。
- **与 skills 的关系**：`core/atlas/api/evolution_router.py` `approve_candidate` 端点把 bundle 经 `_persist_evolved_bundle` → `save_local_skill_bundle(origin_kind="local_evolved")` 写入用户技能目录并登记统一 Registry（幂等：重复批准版本号 patch+1）。`reject`/`maintain` 端点直通 curator。
- 其他：`watcher.py`（上游 git/GitHub release 监控 EvolutionStore，与技能 watcher 无关）、`capability_diff.py`、`parity_mapper.py`、`branch_flow.py`、`taskbook_draft.py`。
- 前端：`EvolutionPage.tsx` + `services/evolutionApi.ts`（candidates 列表/approve）。

---

## 4. 差距分析（对照任务书）

| 任务书要求 | Atlas 现状 | 缺口 |
| --- | --- | --- |
| per-agent learned-skill collection | 无任何 per-agent 技能概念；enable/disable 全局 | 缺 per-agent 启用关系表与 per-agent learned 候选归属（`agent_id` 字段） |
| proposal / pending / diff / approve / reject / rollback | lifecycle decision+approval 两段式（market 更新/安装）；X5 candidate 有 approve/reject | 无统一 **proposal 实体**（带 diff、revisionHash 乐观锁、事件账本、goal/evidence、autonomous 标记、origin 溯源）；candidate JSON 无 diff/补丁语义、无回滚记录关联 |
| provenance | `provenance{provider, external_id, source_url, origin_kind, installed_path, computed_sha256, market}` + append-only lifecycle history | 缺 run/session 级溯源（哪个 agent、哪次 run、哪些 evidence 产生）；candidate provenance 停留在 JSON 文件 |
| watcher | `evolution/watcher.py` 只监控上游仓库；技能目录无 watcher | 缺技能目录/技能集合变更 watcher（学习材料采集入口） |
| autonomous suggestion | X5 candidate 三来源（repeated_runs/user_request/recording_bundle）确定性生成 | 缺 turn 级背景审查（对标 OpenClaw experience review / Hermes background_review）：无"何时值得学"的触发判定、无使用回执、无 propose/auto 模式策略 |
| dedupe / merge / stale / background maintenance | `SkillCurator.maintain()` 有同名合并、source_version outdated、闲置 stale、pinned 跳过、从不删除 | 停留在候选 JSON 层；**不作用于已注册技能**（Registry 无 stale/merged 状态语义）；无伞形归并/absorbed_into；无使用遥测表（use_count 只在候选上）；无后台调度（maintain 只能手动 POST） |
| source 类型新增 local_recorded / local_evolved / agent_learned | `ORIGIN_KINDS` 已含 `local_recorded`、`local_evolved`（前端徽标已支持） | **缺 `agent_learned`**；无 origin_kind → 注册来源校验映射的收口 |
| 默认启用/建议技能，但实体不复制 N 份 | Registry 单实体（name,version) 唯一 | 缺"agent↔skill"关联建模（默认启用集、建议集、per-agent 启用开关）；现在只有全局 lifecycle enable |

**架构红线确认**：候选目前存在 `evolution/candidates/*.json`（第二存储形态）。任务书要求所有结果落同一个 SkillRegistry——升级方向是把 proposal/candidate 变为 Registry 库内的表，evolution JSON 变为兼容导入或废弃。

---

## 5. 落点建议

### 5.1 数据模型（全部落在 `core/atlas/skills/registry.py` 同一 SQLite，禁止第二 registry）

新增表（在 `SkillRegistry.__init__` 的 schema 脚本追加，保持 append-only 触发器风格）：

1. **`skill_proposals`**（对标 OpenClaw proposal record + Atlas decision/approval 合流）：
   `proposal_id PK, agent_id, kind(create/update/merge), status(pending/applied/rejected/quarantined/stale/merged), title, description, draft_content, draft_hash, base_name, base_version, base_content_hash, support_files_json, target_name, target_skill_dir, scan_json, goal, evidence, origin_agent_id, origin_session_key, origin_run_id, autonomous INTEGER, created_by, created_at, updated_at, decided_at, status_reason, revision_hash, correlation_id, proposal_event_id(FK 最新), acquisition_id(联动现有审批)`。
2. **`skill_proposal_events`**（append-only + 触发器）：`sequence PK AUTOINCREMENT, event_id UNIQUE, proposal_id FK, event_type(created/revised/evaluation_completed/applied/rejected/quarantined/stale/merged), revision_hash, occurred_at, actor, correlation_id, payload_json`。
3. **`skill_proposal_rollbacks`**：`proposal_id PK/FK, written_at, target_name, target_version, action(create/update), previous_content_hash, previous_content, support_files_json, restore_event_id`（复用 `lifecycle.py::_snapshot` 落盘 + 事件关联）。
4. **`skill_usage`**（对标 Hermes skill_usage）：`name, version, agent_id, use_count, view_count, last_used_at, last_patched_at, patch_count, first_seen_at, state(active/stale/archived), pinned, archived_at, origin_kind`，主键 `(name, version, agent_id)`——聚合行用 `agent_id='*'`。
5. **`agent_skills`**（per-agent 启用关系——技能实体不复制）：`agent_id, skill_name, enabled INTEGER, relation(default_enabled/learned/suggested/adopted), enabled_at, disabled_at, note, UNIQUE(agent_id, skill_name)`。技能实体永远只有 `skill_registry` 一份；agent 只持有关系行。`relation='learned'` + `provenance.origin_kind='agent_learned'` 表达"该 agent 自己学到的"；`relation='default_enabled'` 表达出厂默认；`relation='suggested'` 表达推荐未启用。
6. **Registry 校验扩展**：`_validate` 的 lifecycle state 枚举追加治理值不需动；`ORIGIN_KINDS`（market.py）追加 `"agent_learned"`，并新增 `VALID_ORIGIN_SOURCES` 映射（origin_kind → 允许的 registry source 前缀）收口。

### 5.2 文件级改动

| 文件 | 改动 |
| --- | --- |
| `core/atlas/skills/registry.py` | 新增 5 张表 + `create_proposal / revise_proposal(带 expected_revision_hash) / list_proposals / inspect_proposal / decide_proposal(apply/reject/quarantine) / record_proposal_event / proposal_history / list_proposal_events / skill_usage 增删查（mark_used/mark_viewed/set_state/curated_report）/ agent_skills 关系 CRUD（enable_for_agent/disable_for_agent/agent_enabled_skills/default_enabled/建议采纳）`；apply 路径复用 `commit_lifecycle_update`/`record_lifecycle_event` |
| `core/atlas/skills/proposals.py`（新增） | proposal 领域服务：diff 生成（draft vs base 的 unified diff，供前端 review）、扫描对接（复用 `acquisition._security_scan`）、critical→quarantine、apply 时目标树哈希复验（drift 拒绝）、rollback 记录写入 |
| `core/atlas/skills/agent_collections.py`（新增） | per-agent collection：默认启用集装载、建议生成（usage 驱动）、learned 归属查询；只读写 `agent_skills`/`skill_usage`，不复制技能目录 |
| `core/atlas/skills/market.py` | `ORIGIN_KINDS` 加 `agent_learned`；`_install_bundle/register_local` 写入 `skill_usage` 种子行；`_toggle` 增加可选 `agent_id` 参数（per-agent 启用走 `agent_skills`，全局 toggle 保持兼容） |
| `core/atlas/skills/acquisition.py` | `prepare_acquisition` 结果可直接升级为 proposal（`acquisition_id` 关联），复用现有 PASS/WARN/BLOCK |
| `core/atlas/evolution/skill_curator.py` | 保留为候选生成器，但落点改调 `SkillRegistry.create_proposal`（JSON 文件降级为导出/兼容）；`maintain()` 迁移为 Registry 版：同名 merge 产 `kind=merge` proposal（`absorbed_into` 记入 payload），stale 判定改读 `skill_usage`，`outdated` 判定复用 |
| `core/atlas/evolution/watcher.py` | `resolveWorkshopWatchRoots` 对标：新增技能目录 watcher（观察 `skills/community`、project skills 与 per-agent learned 目录变更 → 产出 suggestion 入 `agent_skills(relation='suggested')` 或 proposal），复用 `evolution_router` 的 check_now 调度骨架 |
| `core/atlas/evolution/curator_runner.py`（新增，对标 hermes curator 编排） | 空闲触发 + `interval_hours`/`min_idle_hours`/`stale_after_days`/`archive_after_days` 配置、`.curator_state` 等价状态行（可存 `evolution/curator_state.json` 或 Registry meta 表）、单实例文件锁、dry-run、run 报告（`logs/curator/<ts>/`）、确定性迁移（active/stale/archived，只归档不删）+ 可选 LLM 归并 pass（读 proposal 工具面、写 proposal，不直接改库） |
| `core/atlas/api/skills_market_router.py` | 新端点：`GET/POST /api/skills/proposals`、`POST /api/skills/proposals/{id}/{apply,reject,quarantine}`（带 `expected_revision_hash`、`reason`）、`GET /api/skills/proposals/{id}/events`、`GET /api/skills/proposals/{id}/diff`；`PATCH .../enabled` 支持 `agent_id` body |
| `core/atlas/api/agent_skills_router.py`（新增） | `GET /api/agents/{agent_id}/skills`（含默认启用/建议/learned 分组）、`PUT /api/agents/{agent_id}/skills/{name}/enabled`、`POST /api/agents/{agent_id}/skills/{name}/adopt`（建议→启用）、`POST /api/agents/{agent_id}/usage`（mark_used 回执） |
| `core/atlas/api/evolution_router.py` | `/candidates/*` 改为薄壳（内部转 proposal），`/candidates/maintain` 转调 curator_runner；保留响应形状兼容前端 |
| 前端 `frontend/src/renderer/services/skillsMarketApi.ts` | originLabel 加 `agent_learned`；proposal/agent-skills API 封装 |
| 前端 `frontend/src/renderer/components/skills/OriginBadge.tsx` | `agent_learned` 配色 |
| 前端新增 `ProposalReviewDrawer` / 复用 `SkillDetail` | proposal diff + approve/reject/quarantine UI（沿用 `skillAcquisitionReview.ts` 的 gateState 模式）；`SkillsMarketPage` 加 Proposals tab；agent 维度入口（Settings 或 SkillDiscoveryPage 过滤） |

### 5.3 per-agent 建模原则（回应"实体不复制 N 份"）

- 技能实体只有 `skill_registry(name, version)` 一行 + 磁盘上一份 payload（`provenance.installed_path`）；per-agent 一切都是 `agent_skills` 关系行 + `skill_usage(name, version, agent_id)` 遥测行。
- learned 技能的 per-agent 归属用 `provenance.origin_agent_id`（写入时定死，不可变）+ `agent_skills.relation='learned'` 双表达；其他 agent 通过 `adopt`（复制的是关系行不是实体）共享。
- enable 优先级：per-agent `agent_skills.enabled` > 全局 lifecycle state；禁用技能对建议（suggested）保持可见。
- 升级过程中候选/proposal 一律经 `registry.create_proposal` 进入审批，杜绝绕过审批直写 `skill_registry` 的新路径（X5 现有 `approve_candidate` 已是正确范例，只需换底座）。

### 5.4 分期建议

1. **P1 底座**：registry 五张新表 + proposals.py + agent_skills + ORIGIN_KINDS 加 `agent_learned`；evolution candidate approve 切到 proposal 底座。
2. **P2 curator 后台化**：curator_runner（空闲触发/状态/报告/dry-run）+ maintain 迁移 Registry 版 + skill_usage 遥测接入（mark_used 从激活端点回写）。
3. **P3 自治建议**：目录 watcher + suggestion 生成 + per-agent 启用/采纳 API 与前端；可选 turn 级 experience review fork（对标 OpenClaw experience-review 触发条件：非错误结束、≥N 迭代、静默期、usage receipt、propose/auto/off 三模式 + maxPending/maxSkillBytes 上限）。
