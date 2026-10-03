# R4 研究报告：Hermes Bot Mode / 群聊 / Cron / Bot Screen 产品面

> 来源冻结：Hermes fork `D:\hermes-agent`（branch `atlas`，HEAD `ef4571dec5` = upstream `c8301ea6c9` + Atlas patches），只读。
> Atlas 基线：`D:\Atlas` @ `a034bff`（Python FastAPI `core/atlas/**` + Electron/React `frontend/**`）。
> 本文路径除标注外均相对 Hermes 仓库根。

---

## 0. 总览：一个"bot"到底是什么

Hermes 的 Bot Mode 中，**bot = Hermes profile = 一个独立的 `HERMES_HOME` 目录**。它不是数据库里的一行，而是磁盘上一个完整 agent home：独立的 config.yaml / SOUL.md / skills/ / state.db（会话库）/ cron/jobs.json / assets/。Bot Mode UI（`apps/desktop/src/plugins/hermes-bots/`，插件 id `hermes-bots`）只是这套目录的"花名册 + 编排器"；所有写操作都落到 gateway 的 JSON-RPC（`tui_gateway/methods_*.py`），后者再落到 `hermes_cli/profiles.py`、`cron/jobs.py` 等文件原语。

关键结论（影响 Atlas 设计）：
1. **bot 不是独立 agent core**：所有 profile 共享同一套 Hermes runtime 代码与同一个 gateway/multiplexer 进程；profile 只是"配置 + 状态目录 + 身份（名字/头像/SOUL）"的包装。每个 bot 的会话历史在**自己的 `state.db`**（`hermes_state*.py`，SQLite）。
2. **canonical chat（forever-chat）是一个命名约定**：每个 bot 恰好一个 titled exactly `"Bot Chat"` 的会话（core 的 `UNIQUE(title)` 索引使 (profile, "Bot Chat") 成为精确注册表）。身份=名字，**从不存 session id 指针**（旧 `ui_meta.chat` 指针方案已删除——所有"丢聊天"事故都源于悬空指针）。
3. **群聊是客户端编排**：插件（Desktop 渲染层）维护 room 记录，给每个成员在各自 profile 上开 hidden plumbing session，用 `prompt.submit` 轮询驱动轮次；服务端另有新的 hosted-rooms 协议（`gateway/hosted_rooms.py` + `tui_gateway/methods_groups.py`），但桌面群聊主路径不走它。
4. **cron 是 per-profile 的** `<HERMES_HOME>/cron/jobs.json` + 60s ticker 调度器；UI 走 REST `/api/cron/*`（桌面主 Cron 面板）和 ws `cron.manage`（bot 面板 Routines），模型侧走 `cronjob_manage` 工具。

---

## 1. Bot 数据模型（问题 1）

### 1.1 磁盘布局（每个 bot 一个目录）

```
<root>/profiles/<name>/            # 非 default profile；default 直接是 ~/.hermes
├── profile.yaml                   # 元数据：description / description_auto / display_name /
│                                  #   previous_names / role / ui_meta / _ui_meta_revisions
├── config.yaml                    # model(provider/default) / skills / mcp_servers / platform_toolsets / voice...
├── SOUL.md                        # 人格（create 时由 composeSoul 生成）
├── .env / auth.json               # 凭据（clone 时默认剥离 channel 凭据、共享 auth 可选）
├── skills/<skill>/SKILL.md        # 已安装技能
├── state.db                       # 会话库（sessions/messages/FTS/titles，hermes_state*.py）
├── cron/jobs.json                 # 该 bot 的 cron 任务（见 §4）
├── assets/avatar.{png|jpg|webp}   # 头像（≤2MB，magic-bytes 嗅探）
└── bot-desktop/                   # Bot Screen 运行时状态（RFB socket、lease 文件、浏览器 profile）
```

- 目录注册表：`hermes_cli/profiles.py`（`_get_profiles_root()`、`list_profiles()`、`get_profile_dir()`、`normalize_profile_name()`）。创建走 staging 目录 + 原子 rename（multiplexer 30s 重扫 profiles/，避免半拷贝被收养）。
- 别名：`create_wrapper_script()` 生成 `hermes -p <name>` 的 shell wrapper；`build_alias_map()`。
- 重命名：`rename_profile()` 在 `profile.yaml.previous_names` 追加旧名——群聊成员描述符靠它重链（#110200）。

### 1.2 `profile.yaml` 字段（服务端写入口 `hermes_cli/profiles.py::write_profile_meta` / `tui_gateway/methods_profiles.py::_configure_ui_meta`）

| 字段 | 类型 | 语义 |
|---|---|---|
| `name` | 目录名 | 规范 id（`^[a-z0-9][a-z0-9_-]{0,63}$`），比较/spawn 永远用它 |
| `display_name` | str≤64 | 纯展示名 |
| `description` / `description_auto` | str/bool | 1-2 句角色描述（kanban 分解器按角色路由）；auto=LLM 生成未确认 |
| `previous_names` | list | 重命名历史（群聊成员重链） |
| `role` | str | 后端角色（仅 setup 写入，client API 不放行） |
| `ui_meta` | dict（64KB 上限） | 插件命名空间 UI 元数据，键为插件 id；`hermes-bots` 命名空间见下 |
| `_ui_meta_revisions` | dict[str,int] | per-key CAS 版本号（`ui_meta_expected_revisions` 悲观校验，冲突整单拒绝并回 `ui_meta_conflicts`） |

`ui_meta["hermes-bots"]`（即 `BotMeta`，前端 `types.ts:64`）：

| 字段 | 语义 |
|---|---|
| `title` | Bot Mode 花名册显示名（跨机器，服务端同步） |
| `description`、`color`、`shape`、`imageKind('photo'/'shape')`、`custom` | 外观；`image`（Data URL）**不入 ui_meta**（64KB 上限），走 `profiles.set_asset` 存 `assets/avatar.*` |
| `sectionId`/`sectionName` | 用户自建侧栏分区（成员关系记在 bot 上，跟随 profile.yaml 迁移机器） |
| `groups`/`group` | bot 所属群聊名列表（legacy 标量并存） |
| `hidden`、`pinned` | 花名册显隐/置顶 |
| `screenAutoOpen` | bot 开始用屏幕时自动弹 Screen tab（opt-in） |
| `created` | 创建时间 ms（复制 bot 时刻意不拷） |
| `pet`、`chat` | 仅本地持久化（pet 图标；chat 是已废弃的 canonical 指针，merge 时剥离） |

元数据写入协议（`data.ts::saveBotMeta`）：本地 `ctx.storage`（v1 name-keyed → v2 route-keyed，带迁移与回滚）**+** 服务端 `profiles.configure {ui_meta:{'hermes-bots':...}, ui_meta_expected_revisions}`，读-改-写 CAS 重试 3 次；三态结果 `persisted/unsupported/failed`。头像只在真正变化时 `profiles.set_asset`（防跨机器 no-op 竞态清图）。

### 1.3 花名册行 `RosterRow`（`types.ts:96`，= ws `profiles.list` 行）

| 字段 | 语义 |
|---|---|
| `name` | profile 规范名 |
| `title`(nullable) / `display_name` / `description` | Bot Mode 标题 / 核心展示名 / 角色描述 |
| `canonical_session` | `{id, resolved_id, root_title, title, preview, last_active, message_count, live_message_count}`——服务端每次 list 时**按名字**解析（`methods_profiles.py::_canonical_session_row`：`db.get_session_by_title("Bot Chat")` + `get_compression_tip` 取压缩谱系 tip）；`id`=持久 registry 行，`resolved_id`=当前活性 tip |
| `last_session` / `worker_session` | 最新人类可见会话 / 最新 kanban/tool worker 会话（worker 心跳让花名册显示"working"） |
| `ui_meta` / `ui_meta_revisions` / `has_avatar` | 见上 |
| `previous_names` | 重命名历史 |
| `handle` | `@`-提及名（Electron union roster 预计算：本名或 `name-device`；default 的 handle 是 `hermes`） |
| `connectionId/connectionKind/connectionLabel/installId` | 多连接归属（installId 是机器稳定身份） |
| `route` | `{connectionId, mode:'local'/'remote', profile, targetProfile}` —— 一切跨连接 RPC 的路由凭据（`requestForBot`） |
| `remoteSource/sourceReachable/sourceError/sourceMissing/retained/ghost` | 源健康与降级绘制状态 |

roster 查询：`data.ts::useRoster` → `fetchRosterSnapshot()`，React Query 每 5s 轮询 + retry 上限 15s；活跃 gateway 的 `profiles.list`（富行）∪ Electron `host.agents()` union（跨连接薄行）经 `mergeMultiSourceRoster` 合并。`bot_mode_protocol:true` + `install_id` 随行返回（前者告诉前端别再往 SOUL.md 追加协议）。

### 1.4 Bot 的能力配置（Edit Profile，`profiles.describe`/`profiles.configure`）

- `soul`（SOUL.md 全文）、`description`、`model+provider`（切贵模型需 `confirm_expensive_model` 二次确认握手）、`disabled_skills`、`enabled_toolsets`（pin `platform_toolsets.cli`）、`enabled_mcp_servers`（replace 语义）。
- Create（`create-dialog.tsx::ensureAgentCreated`）：一条 `profiles.create {name, description, clone_from('default'|null|本地源), no_skills, share_auth, soul: composeSoul(...), model+provider}`，随后 best-effort `profiles.configure` 应用 Advanced 面板的能力勾选；远端目标则直接写远端 ui_meta+asset。取消时 `deleteBot()` 删除草稿 profile（懒创建 + single-flight）。
- `soul.ts::composeSoul`：身份文本 + `## Messaging other agents` 协议段（bot-to-bot DM 走 `hermes -p <name> chat --in ~ -c "Bot Chat" --create-if-missing -Q -q "Message from 🤖 @handle: ..."`，后台跑、不阻塞）；`bot_mode_protocol` 的后端把协议注入 system prompt，前端就不再追加。

---

## 2. Bot 与 runtime 的关系、canonical chat（问题 2）

- **复用同一 runtime**：bot 全部字段都是"配置包装"。激活一个 bot = 对其 (connectionId, profile) 路由发起 RPC（`routing.ts::requestForBot → host.requestProfile`）；本地冷启动由 gateway 的 backend pool 按 profile 拉 起 agent 进程（`spawnPriority:'foreground'` 让用户手势插队）。没有任何"每个 bot 一个 agent 类/进程常驻"的概念；进程数由 gateway 池（3 slots 之类）控制。
- 会话创建显式契约 `follow_profile_config: true`（PR #97008）：resume 不恢复旧行存的 model/provider pin，永远跟随 profile 当前 config——bot 换模型后所有旧会话跟着走。
- **canonical chat**：`canonical-chat.ts`。
  - `CANONICAL_CHAT_TITLE='Bot Chat'`；(profile, title) 即身份，`session.list {title:'Bot Chat', include_hidden:true}` 精确查询（canonical 会话永远 hidden，不进侧栏）。
  - `findExistingCanonicalChat` **fail-closed**：RPC 失败或 roster 上曾有 canonical_session 而现在查空 → 抛错（"not starting a new chat"），绝不 mint 新会话——这是防"丢上下文"的核心不变量。
  - `createCanonicalChat`：single-flight（`canonicalCreations` map 防双击双 mint）；`session.create {title, hidden:true, follow_profile_config:true}`（lazy，行落库要等首条消息）→ 立即 `session.title` 物化行并堵住自动标题竞态；title 撞车（"already in use"）→ **adopt-before-mint**，重新查注册表收养赢家、弃掉本地的空 session。
  - 打开走 `openStoredBotChat`：`host.openSession(storedId, {intent:'in-place', expectHistory, forceResume, workspaceMode:'bots', tabTitle:'Bot Chat'})`；压缩谱系用 `resolved_id`（tip）打开。
  - New Bot 创建时唯一的 kickoff：`prompt.submit "Hey, tell me about yourself!"`（本地化文案），仅此一次。
  - 传播机制（bot↔bot DM）：SOUL 协议让 bot 用 CLI `hermes -p <peer> chat -c "Bot Chat"` 互发；`message_agent` + relay（§6）是跨连接版本。

---

## 3. 群聊机制（问题 3）

### 3.1 存储与身份

- room 记录 `GroupChat`（`types.ts:198`）持久化在**插件 storage** 键 `group-chats`（`group-chat.ts::updateGroupChat` 唯一写入口）：

| 字段 | 语义 |
|---|---|
| `roomId` | 建群时 mint 的不可变 id（`mintGroupRoomId`）；成员 session 标题、mirror key 都用它，改名不分叉 |
| `members: GroupMember[]` | 源限定成员描述符（RosterRow 的 Pick：name/handle/title/connectionId/installId/previous_names/route...） |
| `log: GroupMessage[]` | 共享房间时间线 `{at, from:{kind:'member'/'user', name, source, gateway}, text, images?, thread?, id?}`；`trimGroupChatLog` 限长并同步收敛 watermarks |
| `watermarks: Record<'<thread>::<memberKey>', number>` | 每成员在 log 里读到的位置（delta 投递基线），**必填**，所有写者都要 seed |
| `sessions: Record<'thread:<thread>::<memberKey>', sid\|true>` + `sessionOwners` | 成员的 hidden plumbing session 指针 + 捕获的 owner 描述符（sweep 重验 route） |
| `epoch` / `running` / `stoppedEpoch` / `turn` | 运行时态：Stop 使 epoch+1，旧 epoch 的在途 turn 作废（`shouldCommitMemberTurn`） |
| `holds` / `heldMessages` / `holdDetection` | #93129 粘性 hold：用户文本指向某成员时把它按住，消息攒到它下次可见 turn 再投（可按房间关闭） |
| `stranded` | turn 超时（180s poll / 事件信号）后的"迟到回复"基线，窗口重启后仍可收割 |
| `externalCursors` | #93813 成员在群 session 外部直接写 transcript 的对账游标（`group-external-writes.ts` 镜像进 log） |
| `syncRevision` / `tombstone` / `pinned` / `rosterOrder` / `sectionId` / `image` | mirror 版本 / 解散墓碑（运行时） / 置顶 / 本地排序 / 侧栏分区 / 群头像 |

- 成员身份键 `groupMemberKey`（`group-membership.ts:56`）：本地成员=裸名（兼容），remote= `connectionId::name`；session 键 `groupSessionKey = 'thread:<thread>::<memberKey>'`——**每线程每成员一个独立 session**（线程 B 复用 A 的 session 是 #90420 的串味 bug）。pre-thread 裸键只在房间未迁移时可收养。
- `followGroupChat(group, onRename)`：异步操作期间跟随 room 记录的重命名/解散（按 roomId 重找），`isLive()` 是所有轮次的继续条件。

### 3.2 建群与加 bot

- `create-dialog.tsx` 群创建流：选成员（上限 `GROUP_CHAT_MAX_MEMBERS`）、起名（`uniqueGroupChatName`）、`mintGroupRoomId()`、`updateGroupChat` 落库；把群名写进每个成员 `ui_meta['hermes-bots'].groups`（`groupMembershipPatch` / `group-chat-view-members.ts::setGroupMembership`，这样成员侧知道自己在哪些群）。成员描述符从 roster 派生（`durableGroupChatMembers`），孤化描述符（连接被删）由 `hygiene.ts` 标记不炸 UI。
- 加/减 bot = 改 `room.members` + 成员的 `groups` ui_meta；解散 = `tombstone:true` + `rememberGroupChatTombstone`（跨 mirror 墓碑，只按 roomId，防同名重建被误删）+ 解散成员 session（`session-sweep.ts`）。

### 3.3 一条用户消息的生命周期（Round 引擎）

`group-rounds.ts`（头部注释就是行为规范）：

1. `sendToGroupChat`：用户文本 → `appendGroupChatEntry`（去重：`isDuplicateGroupAppend`）→ hold 指令识别（`classifyGroupHoldDirective`/`applyGroupHoldDirective`："(stop dixie)"类）→ `queueGroupChatDrive` 串行排队驱动。
2. `parseGroupChatMentions`：确定性 @ 解析（本名/handle/title/slug/collapsed/友好名/`@everyone`/`@"two words"`；跳过正在说话的成员）。
3. `runGroupChatRounds(group, members, thread)`：
   - 回合数硬上限 `GROUP_CHAT_MAX_ROUNDS`、总消息上限 `GROUP_CHAT_MAX_MESSAGES`、continuation 上限；**串行 round-robin，无 LLM 路由**。
   - 每轮开始先 `harvestStrandedGroupReply` 收割所有成员的迟到回复。
   - `resolveGroupResponders`（自用户消息以来被 @ 的成员，否则全员）→ `rotateGroupSpeakers`（按 round 轮转起点）→ 过滤仍 stranded 的成员 → 逐个 `runGroupRoundMember`。
   - 成员回 `"pass"`（`isGroupPassText`：空或 `(pass)` 变体）= 沉默；整轮无人发言 → `unaddressedGroupMentions` 查未回应的 @handoff → 有则跑**有界 continuation 轮**（`runGroupContinuationMembers`，这就是 "handoff" 的机制：@提及即任务交接，引擎保证被点名的成员一定得到一轮），仍无人发言 → settled。
   - 退出区分 `settled`（共识安静）vs `capped`（上限截断），写 `recordGroupActivity`（`group-activity.ts`，11 种事件：working/queued/replied/held/passed/settled/capped/failed/timed-out/stopped/cancelled）→ 活动流 UI。
   - finally：`running=false`，后台 `harvestStrandedUntilSettled` 兜底收割。
4. `runGroupChatMemberTurn`（`group-turns.ts::runGroupChatMemberTurnLeased`）：
   - `ensureGroupChatSession`：fail-closed 的 resume 链（本线程 sid → 线程标题 → legacy 指针 → 房间标题；JSON-RPC 4007 才算"真不存在"→ `session.create {title:'Group: <roomId> · <thread>', hidden:true, room_plumbing:true, follow_profile_config:true}`）。
   - `buildGroupChatTurnPrompt`（`group-round-prompt.ts`）：`[Group chat: "<name>"] You are @handle, one participant ...` + **自上次 turn 以来的房间 delta**（`formatGroupDeltaLines`：条数/字符双预算， newest-first 挑行、标注省略数、`Name (user):`/`(you)`/`[device]` 前缀、把成员复读的控制帧 opener 改写为 `[member-quoted ...]` 防注入）+ 固定房间规则（一次一条、`(pass)`、@ 队友拉人、不泄露 1:1 内容）。**规则随 turn payload 走而非 SOUL**——旧 bot 无迁移即可入群。
   - 附件 `stageGroupTurnAttachments` 换成真 payload；`prompt.submit` 后 `waitForTurnSignal`（`message.complete`/`error` 事件，5s poll 兜底，180s 超时转 stranded）→ `pickGroupTurnReply`（newest-first 挑 assistant 行，识别 `failed_turn` 边界行）→ `(pass)`/回复/失败通知写回 log 并推进 watermark。
   - 阻塞式 prompt（clarify/approval）镜像到 `$groupClarify`（`syncGroupClarify`，键 `group::memberKey`），房间内渲染答题卡（`group-chat-view.tsx`）。
   - 与群 session 复用：**否**。1:1 canonical chat 与群 plumbing session 是不同 session；群成员的"记忆"只通过房间 delta 传播。
5. 跨桌面同步：`groupChatSyncSnapshot`（v3 envelope，≤48KB / 16 条消息 / 每条 1200 字符截断）写**default profile 的 `ui_meta['hermes-bots-groups']`**，`scheduleGroupChatServerSync` 按 connection fan-out、`mergeGroupChatSyncSnapshots` 按 roomId+revision+稳定消息 id 做幂等合并（墓碑随行）。这让手机/另一台 Desktop 看到同样的房间（只读为主）。

### 3.4 服务端对照：hosted rooms（另一条产品线）

`tui_gateway/methods_groups.py`（`groups.capabilities/list/create/state/send/rename/log/disband/replicate/promote/demote/stop/retry/approve/peer.*`）+ `gateway/hosted_rooms.py`（SQLite append-only 事件日志，房间/成员/事件上限齐备）+ `gateway/hosted_room_discussion.py`（服务端 Discussion 驱动、成员校验、执行策略）。桌面插件群聊**不**调它（桌面源码 0 引用），它是给无桌面宿主（服务器/云）用的同概念服务端实现。Atlas 若把编排放服务端，这个文件族是比桌面插件更合适的蓝本。

---

## 4. Cron 产品面（问题 4）

### 4.1 三个入口、一个存储

| 入口 | 文件 | API |
|---|---|---|
| 桌面主面板 Cron View（跨 profile 统一视图） | `apps/desktop/src/app/cron/index.tsx`（CronView，1486 行）+ `cron-actions.ts`/`job-state.ts`/`cron-job-model.ts`/`blueprints.tsx`/`open-cron-run.ts` | REST `/api/cron/*`（`src/api/cron.ts`）→ FastAPI `hermes_cli/web_routers/cron.py` |
| Bot 面板 Routines（当前 bot 的 jobs） | `plugins/hermes-bots/cron.tsx`（1345 行：列表/SchedulePicker/CreateDialog/DetailDialog/pane） | ws `cron.manage`（`tui_gateway/methods_tools.py:1393`，profile-scoped）→ `tools/cronjob_tools.py::cronjob()` |
| 模型自助（自然语言） | 聊天内 `/cron` 或直接说话 | `cronjob_manage` 工具（tools/cronjob_tools.py，action 式单一工具）；cron 会话内**禁用**（防自排程失控） |

存储一律 `<HERMES_HOME>/cron/jobs.json`（`cron/jobs.py::JOBS_FILE`，flock 30s + per-job fire fence）；60s ticker（`cron/scheduler.py`，`TICKER_INTERVAL_SECONDS=60`）+ misfire catch-up + 全局 `hermes pause` 应急闸。

### 4.2 job 字段（`cron/jobs.py::create_job` / `cron/job_definition.py::JOB_DEFINITION_FIELDS`）

**authored（创建者拥有）**：`name`、`prompt`、`skills[]`（+legacy `skill`）、`model`、`provider`、`base_url`、`script`、`no_agent`、`monitor_script`/`monitor_url`（互斥；tick 先跑廉价 monitor，输出未变则跳过 LLM）、`context_from`（引用其他 job 的最近输出）、`schedule`、`schedule_display`、`deliver`、`origin`（创建来源 `{platform, chat_id, thread}`）、`enabled_toolsets`、`workdir`、`attach_to_session`、`reasoning_effort`（none…ultra，per-job 思考档）、`failure_deliver`、`interpreter`、`repeat.times`。
**scheduler 拥有**：`id`(uuid12)、`enabled`、`state`(scheduled/paused/...)、`paused_at/paused_reason`、`created_at`、`next_run_at`、`last_run_at`、`last_status`（含 `delivery_failed` 特判：跑成功但投递失败必须当失败显示）、`last_error`、`last_delivery_error`、`last_delivery_unverified`、`last_failure`、`failure_streak`、`repeat.completed`、`monitor_state`、`pending_slot`/quota_hold。

调度解析 `parse_schedule`：`"30m"`/`"every 30m"`=interval、`"in 30m"`=一次性、`"every monday 9am"`/`"weekdays at 9am"`=自然语言→cron（`_natural_every_to_cron`）、5-6 段=cron expr（croniter）、ISO=once（naive 时间按配置时区补全）。

模型解析（fire 时）：per-job pin → config `cron.model`（车队默认）→ 主模型当前值。`--pin` 锁当前主模型；**agent 的工具不能改 model pin**（推理配置用户专属）；`reasoning_effort` 同理不在工具 schema 里。

投递 `deliver`：`local` / `origin`（创建会话的 platform:chat_id[:thread]；cron 会话里创建会被 `_resolve_cron_context_deliver` 落成具体目标） / `bot-chat[:<profile>]`（投进某 bot 的 canonical chat，`cron/bot_chat_delivery.py`，机器本地的 profile 校验）/ 平台目标 `telegram|discord|slack|whatsapp|signal[:chat_id[:thread]]`（逗号分隔多目标；`cron_delivery_targets` 只列已配置网关）。

### 4.3 UI 能力清单

- **列表/详情**：jobs 卡片（name、描述=prompt 或 script、schedule 人类可读、next/last run、last_status 字样化、pause 徽章+原因）；详情含 run 历史（agent 会话 ∪ script-only 的 output-doc 运行，`/api/cron/jobs/<id>/runs`；可点开 run 会话 transcript `open-cron-run.ts`）。
- **编辑器**：name/prompt、schedule picker（预设 hourly/daily/cron expr + 自然语言串）、**deliver 多选框**（本地文件 + 各已配置平台，`deliver-checkboxes`）、**per-job model/provider 下拉**（`requestModelOptions`）、script-only 开关（no_agent：无 LLM，stdout 即投递）、skills 附加（bot 面板走 `cron.manage add` 不带 skills；主面板/CLI 全量）。
- **动作**：pause/resume（`paused_reason`）、Run now/Trigger（同步等跑完，24h 超时）、edit（PUT updates）、delete（ConfirmDialog）、创建（手填或 **Automation Blueprints** 模板：`cron/blueprint_catalog.py` 提供参数化模板目录，`/api/cron/blueprints` 全局目录 + `instantiate?profile=` 落成真实 job；blueprints.tsx 是画廊 UI）。
- **Bot 面板 Routines**：按 `[bot:<slug>]` 名字前缀把 job 归属到 bot（`routineBot`）；legacy 无前缀的 delegated routine（prompt 里嵌 `hermes -p <bot> chat -c ...` 命令的老形态）会被自动 pause 掉（`loadRoutines`）；create 时若目标是别的 bot 且非 profile-scoped gateway，prompt 用 `SAFE_ROUTINE_MARKER` + 委托命令形态；`deliver:'bot-chat'` 让结果回到该 bot 的 canonical chat。Screen hero（见 §5）就在这个 pane 顶部。

### 4.4 后端 API 面

- ws `cron.manage` actions：`list`（`include_disabled`，回 `scoped:<profile>` 证明作用域）、`add`（name/schedule/prompt/repeat/continuity/deliver）、`remove/pause/resume`（by job_id/name）。`_scoped_rpc` 使 `profile` 参数切 HERMES_HOME → per-bot cron store。
- REST：`GET/POST /api/cron/jobs`、`GET/PUT/DELETE /api/cron/jobs/<id>`、`POST .../pause|resume|trigger`、`GET .../runs`、`GET /api/cron/delivery-targets`、`GET /api/cron/blueprints`、`POST /api/cron/blueprints/instantiate`。统一经 `cron.jobs.create_job/update_job/...`，dashboard updates 由 `_normalize_dashboard_cron_updates` 归一。
- 预检（`cron/scheduler_preflight.py` + docs）：跑前校验 API key 可解析、skills 就绪、投递目标凭据在、MCP/toolset 可解析；失败进 `scheduler_failure_copy` 的人话文案 + `incidents.py`。

---

## 5. Bot Screen —— takeover UX（问题 5）

- **是什么**：headless Linux gateway host 上，每个 bot 一个 Xfce 桌面（TigerVNC `Xvnc`，仅 0600 Unix socket）+ 该 bot 专属 headed Chromium profile（`<HERMES_HOME>/bot-desktop/browser-profile`），bot 的 `computer_use` 与 headed browser 都画在这块屏上；Desktop 内嵌 noVNC 直播。
- **用户看到什么**（`screen-pane.tsx`，569 行）：`ScreenHero`（`screen-hero.tsx`，Routines pane 顶部的缩略图，谁在控制 + Start/Install 状态）、主窗口 workspace tab（`screen-open.tsx::openBotScreen`，`host.openWorkspace` 一 bot 一 tab，重复打开 `revealPane`）、侧栏 profile 组下的 Screen 盒。头部 chip：`Bot is in control` / `You are in control`。
- **handoff 流程**：control lease 是 `<HERMES_HOME>/bot-desktop/` 下的文件（无文件=bot 控；不可读=fail-closed 锁死；250ms 桥缓存窗口）。用户点 **Take over** → `display.lease.acquire`（lease 带 epoch 单调）→ 边框变红、人类键鼠生效，bot 的 `computer_use`/browser 工具被拒（`human_has_control`，工具级栅栏）；bot 需要人工的步骤（登录/2FA/验证码/支付）在回复里说明并结束 turn，**不阻塞等待**。点 **Hand back** → bot 重获控制并重截屏继续；关 pane 也交还；断线（合盖/断网）**不**交还；reload 后出现 **Hand back (force)**。两个 viewer：后 Take over 者赢，前者降级为观看（桥用 close code 4000 `control-taken` 逐出，pane 自动以 watch 模式重附）。
- **RPC 面**（`screen-connection.ts`，契约在 `tui_gateway/contracts/display.py`）：`display.status`（状态+lease，拉取+推送 `display.lease` 事件）、`display.observe`（30s 单次 ticket → 兄弟 WebSocket `/api/display/ws` 拼接 RFB 流）、`display.lease.acquire/release(?force)`、`display.thumbnail`、start/stop。前端状态只是后端的缓存（`screen-state.ts`：per-bot `$screenState` + status 请求代际 fencing + lease epoch 乱序丢弃）。
- **autoraise**（`screen-autoraise.ts`）：opt-in（`BotMeta.screenAutoOpen`）；bot 发出**活的** `tool.start`（`computer_use`/`browser_*` 前缀）→ 30s 冷却内最多一次把 Screen tab 提到前台（不动键盘焦点）；手动关闭抑制到下一次 run；replayed 历史帧绝不触发。
- **安装**（`screen-install.tsx`）：host 缺包时 pane 显示 **Install on host**，点击经 gateway 在目标机上跑包管理器（sudo 密码掩码卡，只发往那台机），日志流式回显；内存门槛 `bot_desktop.min_free_memory_mb`（默认 1536）、空闲回收 `idle_stop_minutes`（30）、`placement: auto|terminal|gateway`（跟 terminal.backend 决定屏幕在宿主还是沙箱内）。
- 沙箱化：Docker/SSH/Singularity 后端时 Xvnc+Xfce+Chromium 进沙箱（`nousresearch/hermes-sandbox:desktop` 镜像），host 只留 marker；浏览器 DevTools 端口经同通道端口转发。

---

## 6. 跨连接 bot relay（补充）

`relay.ts`（773 行）+ `tui_gateway/methods_bot_relay.py`：Desktop 是路由器——持有全部 gateway socket；roster loop（每 60s）向每个 gateway 推"其他连接的 agent 名册"（`bot_relay.roster.sync`），drain loop（push 事件 `bot_relay.outbox.pending` 250ms 防抖 + 30s 兜底）取信封（`bot_relay.outbox.drain`）→ 在目标连接 socket 上 `bot_relay.deliver` → 回执 `bot_relay.reply` 唤醒发送方。旧后端逐调用降级。这是"bot A 在机器 1 @ 机器 2 的 bot B"的传输层；同机跨 profile 则走 SOUL 协议的 CLI 互发。

---

## 7. Atlas 落点建议

### 7.1 Persistent Agent 字段表（Hermes profile ∪ OpenClaw agent ∪ Atlas `agent/definitions.py` 现状）

建议 Atlas 新增 `PersistentAgent` 实体（持久层建议 per-agent 目录，如 `data/agents/<id>/agent.json` + `SOUL.md` + `state/`，学 Hermes 的"目录即身份"，但存 JSON 而非散 YAML）：

| 建议字段 | 来源 | 说明 |
|---|---|---|
| `id` / `name`(规范 slug) / `display_name` | Hermes | id 不变、name 可重命名；`previous_names` 一并吸收（群聊成员重链靠它） |
| `description` / `description_auto` | Hermes | 角色描述，供路由/分解器与花名册 |
| `avatar {kind, color, shape, image_ref}` | Hermes BotMeta | image 存文件（assets/），元数据走实体；Data URL 不入库 |
| `soul`（system prompt/人格文件引用） | Hermes SOUL.md | 对应 Atlas agent file 的 `prompt`/`developer_instructions`，建议独立文件 + 版本 |
| `model` / `provider` / `reasoning_effort` | Hermes + cron pin | per-agent 默认模型三件套；cron/子任务可 override |
| `tools` / `skills` / `mcp` / `permission_mode` / `max_turns` / `output_schema` / `role(leaf/orchestrator)` | Atlas definitions.py 已有 | 直接保留为 agent 的能力节 |
| `hidden` / `pinned` / `sectionId` / `created_at` | Hermes BotMeta | 花名册展示态；`sectionId` 记在 agent 上（Hermes 经验：成员关系在 bot、分区记录在创建端） |
| `groups: string[]` | Hermes BotMeta.groups | agent 所属群聊 |
| `canonical_session_id` | —— | **不要学 Hermes 的"按标题解析"**，但吸收其教训：指针必须带 CAS/谱系（Hermes 删指针是因为会悬空；Atlas 有 DB，可用 `session_id + compression_tip` 双字段 + fail-closed 校验） |
| `ui_meta`（per-client 命名空间 dict + revisions） | Hermes ui_meta | 通用"客户端 UI 元数据"逃生舱，64KB 上限 + per-key CAS，值得抄 |
| `heartbeat {every, active_hours, cooldown, prompt}` | OpenClaw r2 | 见 r2 报告；作为 agent 字段而非独立表 |
| `cron store` | Hermes per-profile jobs.json | Atlas: `AtlasScheduler` 已有全局 store；建议加 `agent_id` 列实现 per-agent 作用域（对应 `cron.manage profile` 参数） |
| `screen/computer {auto_open, placement}` | Hermes BotMeta.screenAutoOpen + bot_desktop | r3 lane 的 computer 能力挂靠点 |
| `credential_sharing {share_auth, mirror_credentials}` | Hermes | 多 agent 凭据共享/隔离策略 |

### 7.2 群聊 → Atlas child/delegation runtime 的映射

- Atlas 已有 `AgentOrchestrator`（`core/atlas/agent/__init__.py`）+ 子 agent（`role: leaf/orchestrator`）。建议**不要**把群聊做成新的 runtime，而是复用 delegation：一个"群聊驱动器" = 一个 orchestrator 级组件，成员 turn = child run。
- 状态机直接移植 Hermes 的五元组（这些是不变量级的经验，全都有对应 issue 号背书）：
  1. **共享 room log + per-成员 watermark**（delta 投递，成员无状态也可恢复）→ Atlas 用 `data/groups/<roomId>/log.jsonl` + `watermarks`；
  2. **确定性 @ 解析 + 串行 round-robin + `(pass)` 沉默 + 硬上限**（MAX_ROUNDS/MAX_MESSAGES/MAX_CONTINUATIONS 分开计数，exit 区分 settled/capped）→ 放 `core/atlas/groupchat/`（新模块），驱动循环是纯 Python，直接替代 Hermes 里 2000 行 TS；
  3. **每 (thread, member) 一个 session**、fail-closed resume（只有明确"不存在"才 create）、`follow_profile_config`（session 永远跟 agent 当前配置）→ 映射到 Atlas child session 创建约定；
  4. **stranded/harvest**（turn 超时 ≠ 丢弃，基线收割迟到回复）+ **epoch/Stop**（取消旧 epoch 在途 turn）+ **hold**（用户点名某人停/等）；
  5. **handoff = @mention continuation**（保证被点名的成员至少得到一轮），不需要专门协议。
- 服务端 vs 客户端：Atlas 是 FastAPI 单体，**编排放服务端**（学 `gateway/hosted_rooms.py` 的 append-only 事件日志 + `methods_groups.py` 的 `groups.*` 契约：create/state/send/log/disband/stop/retry/approve），Electron 只做房间视图——比 Hermes 桌面插件的"客户端编排 + ui_meta 镜像同步"简单一个数量级，也不需要 48KB 截断投影那套补丁。
- bot↔bot DM（canonical chat）：Atlas 服务端直接投递到目标 agent 的 canonical session（`deliver='bot-chat'` 机制可复用于 cron 投递），无需 SOUL 里教 CLI 互发。

### 7.3 Cron → AtlasScheduler

- r2/r7 已规划 APScheduler 侧；从 Hermes 再吸收：(a) **`[bot:<id>]` 名字前缀或 `agent_id` 列**做 per-agent 归属；(b) `deliver` 目标语法（local/origin/bot-chat/platform:chat_id:thread）与 `delivery_failed` 独立状态；(c) per-job `model/provider/reasoning_effort` pin + fire 时三级解析 + "agent 不可改模型 pin"；(d) `no_agent` script job 与 monitor_script 抑制（廉价监控不变则不烧 LLM）；(e) 自然语言 schedule 解析器（`_natural_every_to_cron` + "in 30m"/"every monday 9am"）可整段移植为纯函数；(f) fire-fence + paused_reason + 全局应急 pause。

### 7.4 UI 直接参考文件清单（Electron/React → Atlas frontend）

| Atlas 功能 | 参考文件（Hermes） |
|---|---|
| Agent 花名册（侧栏/搜索/分区/健康徽章/needs-attention） | `plugins/hermes-bots/roster-pane*.tsx`、`bot-row.tsx`、`data.ts`（filterBots/botSourceStatus/noteBotAttention）、`user-sections*.ts` |
| 新建/编辑 agent 对话框 | `create-dialog.tsx`（懒创建+single-flight+取消回收）、`edit-profile-dialog.tsx`、`profile-config.tsx`（能力清单）、`model-picker.tsx`、`avatar-picker.tsx`、`soul.ts` |
| Agent 详情页（会话预览/cron/Screen hero） | `plugin.tsx`（点击编排）、`cron.tsx`（Routines pane + ScreenHero 布局）、`canonical-chat.ts`（点击开 canonical 会话的完整防御序列） |
| 群聊 UI | `group-chat-view.tsx`、`group-chat-view-members.tsx`、`group-chat-parts.tsx`、`group-hold-status.tsx`、`group-mention-text.tsx`、`group-panes.ts` |
| Cron 面板 | `app/cron/index.tsx`（列表+详情+编辑器+runs）、`blueprints.tsx`（模板画廊）、`cron-job-model.ts`/`cron-actions.ts`（纯函数，测试友好的做法值得抄）、`api/cron.ts`（REST client 形状） |
| Bot Screen（若 Atlas 做 computer-use 接管） | `screen-pane.tsx`（lease UI + 4000 重附）、`screen-connection.ts`、`screen-state.ts`（代际 fencing）、`screen-autoraise.ts`（opt-in 自动弹 tab 的栅栏规则）、`screen-install.tsx`；文档 `website/docs/user-guide/features/bot-screen.md` 是产品规格书级别的参考 |
| 活动流 | `group-activity.ts` + `group-activity.test.ts`（11 种事件枚举） |

### 7.5 反模式提醒（Hermes 用血泪换来的）

- 不要存 canonical session 裸指针（Hermes 因此删掉了整个指针机制）；要存就带谱系 + fail-closed。
- 会话自动标题与身份命名有竞态：创建后立即显式写 title。
- 客户端编排群聊导致：48KB 截断镜像、tombstone 记忆、route 捕获/失效、多源同名去重……全部是 Hermes 为"编排器在 UI 层"支付的复杂度税；Atlas 应把编排放 FastAPI。
- 多机器写同一 ui_meta 必须 CAS（`ui_meta_expected_revisions`），且"旧网关不认识字段"要三态区分（persisted/unsupported/failed）而不是一律报错或一律假成功。
- cron 会话内必须禁用 cron 管理工具（防自排程循环）；投递失败与运行失败必须分开显示。
