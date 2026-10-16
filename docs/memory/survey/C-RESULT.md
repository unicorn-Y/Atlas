# C 线调研结果：生命周期、原文回溯、委派、技能与多模态事件

日期：2026-10-16（Asia/Hong_Kong）  
分支：`memory-survey-c`，基线 `64a4f650a45a69061fcc3d0aa07a513366e8e426`。只读检查 Atlas 源码；本文是调研裁决，不是施工变更。

## 范围、方法与证据边界

按任务书第 2 节检查 M1、M2、M6、M8 和多模态预留字段；C 线补充的 GitHub 项目均给出固定 SHA、许可状态和源文件位置。部分大仓库因 D: 在本轮取证后变为 0 可用字节，未能完成 checkout；这类内容明确标为 GitHub 源码页、官方拆解源码或未核实，不冒充本地 clone 源码。许可只按已实际看到的根/子目录 LICENSE 记录；“未发现”不等于获准复用。

共同结论：Claude 评审的骨架方向基本成立，但需收窄/补强：Atlas 自己是长期记忆主体；生命周期使用显式事件接口；原文引用锚定 SessionDB 稳定 `message_uid`；委派采用最小化、有出处的上下文包；经验只先进入候选，技能必须有证据、反馈和验证门；多模态资产保留原始指针并与派生文本分开。透明文件库继续由 Atlas 掌权，外部项目的宿主框架和服务依赖不直接搬入。

## M1 生命周期钩子

### 对比表

| 项目 | commit / 许可 | 关键源码:函数:行 | 做法、强弱、移植成本 | 证据 |
|---|---|---|---|---|
| MemOS Hermes adapter | `a7367d07e55db61099f7b4e2c1108bc5831a24f3`；根 Apache-2.0，adapter 未见子 LICENSE | `adapters/hermes/memos_provider/__init__.py:on_turn_start:1038`, `sync_turn:1129`, `_turn_end:2427`, `on_session_end:1762`, `_submit_verifier_feedback:2492`; `crystallize.ts` retry `230-304` | 完成 turn 时写 user/assistant/tool_calls/thinking/timestamp/context，session end 与话题结束分离；断连后 reconnect 并重试一次，trace id 支持反馈回写。优势是生命周期和反馈闭环；通用写入幂等需继续从 core 验证。Python→Node bridge→MemOS 服务，逻辑可移植、框架成本中高。 | 本地源码实读 |
| Hermes native memory hooks | `NousResearch/hermes-agent@607a0b0d41e07d903c0b475dd72fb6ac2b37fecc`；MIT | `agent/memory_provider.py:on_delegation:180-181,on_pre_compress:176,on_session_end:165`; `memory_manager.py:on_delegation:937+` | provider 可收到 pre-compress/session-end/parent delegation complete 通知；写入/存储由 provider 决定。delegation hook 是 child 完成后的父侧观察，不是 child 记忆注入。Python低成本参考。 | 本地源码实读 |
| Claude Code hooks | 官方本机拆解；无可适用的公开产品源码许可 | `ClaudeCode-Official/07-TYPESCRIPT-SOURCE/src/src/entrypoints/sdk/coreSchemas.ts` hook event schema `362-365`; `tools/AgentTool/runAgent.ts` SubagentStart `530`; `utils/hooks.ts`; `skills/bundled/updateConfig.ts` `PreCompact`说明 `145` | 事件集合覆盖 UserPromptSubmit、PreCompact、PostCompact、Stop、SessionStart/End、SubagentStart/Stop。适合作事件词汇，不证明 Atlas 的记忆写入策略。TS 宿主耦合高。 | 官方拆解源码实读；不是上游仓库 clone |
| OpenClaw active-memory | `c98311f906972e2a33d6ef3c6ecf027c90256ec6`；根 MIT，插件无子 LICENSE | `extensions/active-memory/index.ts:register:63`, `api.on(before_prompt_build):212`, `api.on(agent_end):604` | prompt 前召回并校验权限；限时运行，失败/超时跳过，不阻塞主任务；结束时清 run state，不直接证明会话沉淀。TS 插件/API 中等成本，适合借限时、fail-open、清理边界。 | 本地源码实读 |
| LangMem | `48e3c11f5bb527282c7d5339c6a87a0b35abccfc`；根许可文件存在 | `src/langmem/short_term/summarization.py:_preprocess_messages:102,153,173`, `summarize_messages:337,467-485` | Rolling summary 记录已摘要 message IDs 和 last-ID watermark，重复输入不会重复归并；不是完整 session/subagent hook 系统。Python但需 LangGraph/LangChain/model adapter，移植成本中。 | 本地源码实读 |
| LangChain AgentMiddleware（新增） | `c088db971097f0f12c7b8c30d473e8dbde09c823`；根许可文件存在 | `libs/langchain_v1/langchain/agents/middleware/types.py:AgentMiddleware`; `factory.py` | before_agent/before_model/after_model/after_agent 组合接口和 wrap/retry 语义可供借鉴，不自带记忆；Python runtime 较重，移植事件契约成本低、框架成本高。 | 本地源码实读 |
| AgentMemory（新增） | `b5e00d027bc0f5f6cb7529bc1acfe6688ba105d1`；未发现 LICENSE/COPYING/NOTICE，许可需确认 | `src/hooks/codex-user-prompt.ts:main:5`; `codex-post-tool.ts:main:27-64`; `src/services/agent-installer.ts` | prompt hook 注入任务召回，post-tool 对卡住/失败事件二次 recall；异常 fail-open。TS+本地服务/MCP+SQLite，移植成本高。许可不能假定。 | 本地源码实读 |
| Mastra memory processor | `mastra-ai/mastra@a15924e709dd5d9439a6c102901c326ab0ec77fb`；根 `LICENSE.md`，该 subtree 无独立许可 | `packages/core/src/processors/memory/message-history.ts:processInput:187-279,processOutputResult:286-343,persistMessages:352+` | 输入按 thread/resource 从 storage 取历史，token boundary/last-N 截断后加回上下文；输出经 transcript transform/redaction 后持久化，错误向 runner 抛出，没有本处自动 retry；过滤 partial tool calls/working-memory tags。适合双向 processor 生命周期，但存储由可替换 storage 实现；TS runner依赖中高。 | 固定 SHA 的 sparse local clone 源码实读 |
| Letta agent loop | 本地 `letta` 目标树 `5bcdd177d70fa2b31a754cfcd801e77b2e1ab16a` 不含预期 `letta/services/group_manager.py`；固定 SHA URL 404，未能确认许可/实现 | 任务书目标 agent-loop/shared-block 源码不在 checkout | 无法从现有证据评价存储、写入、retry、去重/纠错、召回/反馈；不将二手摘要当实现。 | 未核实 |

### 裁决与 Atlas 映射

事件词汇第一选 Claude Code hooks；记忆生命周期行为第一选 MemOS adapter。若看 Atlas 易接的稳定水位，LangMem 是第二；若只看宿主插件接点，OpenClaw 的限时召回/失败隔离优先。不要让一个“SessionEnd”替代 turn 完成、压缩和子代理结束。

移植清单：`ClaudeCode hook event taxonomy → core/atlas/kernel/loop.py:_run_hook`（现有 SessionStart/PreCompact/PostCompact/Stop call sites）；`MemOS.sync_turn → core/atlas/agent/enrichment.py` 的 turn 生命周期/`agent_stop` writer；`LangMem message-ID watermark → core/atlas/engine/session_sync.py:compact_session_messages` 的覆盖边界；`OpenClaw bounded fail-open recall → core/atlas/agent/run_phases.py:_phase_prompt_hook`。检查补齐 SessionEnd 与 SubagentStop 的明确写入语义，保留当前 SessionDB 为原文权威，不新建第二份 transcript DB。Atlas 已有 hooks：`core/atlas/agent/enrichment.py` HookBus（含 `after_compact/before_response/after_response/agent_stop/subagent_start/subagent_end`）；`core/atlas/kernel/loop.py:_run_hook:1622`；压缩/事件调用见 `loop.py:872,960,1284`；子代理事件见 `core/atlas/agent/__init__.py:535,611`。

Claude 骨架：支持并收窄。生命周期 hook 作触发器，不代表写入成功；重复事件须用 session/turn/message 水位幂等，检索超时必须可跳过，持久写失败需留重试/状态而非假成功。MemOS 明确的重连一次是可移植细节，底层服务与 bridge 不搬。

尚未查清：MemOS provider 对所有输入的持久化幂等键、Claude hook 异常时宿主回退差异、Mastra pinned commit、Letta agent loop 的可检出源码。新增候选检索词：`site:github.com agent memory lifecycle hooks before_agent after_agent hooks`；`site:github.com/langchain-ai/langmem hooks before_agent after_agent`；`agent memory hooks UserPromptSubmit PostToolUse fail-open SQLite`。

## M2 原文指针与轨迹回溯

### 对比表

| 项目 | commit / 许可 | 关键源码:函数:行 | 做法、强弱、移植成本 | 证据 |
|---|---|---|---|---|
| Codex memories | `openai/codex@a45b8ccb016fb74f63a6bc29e701568e387cbe38`；仓库 `03-SOURCE/LICENSE` 为 Apache-2.0 | `codex-rs/memories/read/src/citations.rs:parse_memory_citation:6-70`; `protocol/src/memory_citation.rs:8-20`; `app-server/src/request_processors/feedback_processor.rs:resolve_rollout_path:315-333` | citation 记录可读文件 path/行/note 与 thread/rollout id；先运行态映射，再 DB 路径回退，缺失只 warn。rollout 是本地 JSONL，可回看完整轨迹；没有 message/span 锚点。回退非重试。Rust→Python机制低成本，路径布局不照搬。 | 本机官方拆解 + 本轮 sparse local clone |
| Claude-Mem | `b8fc2ef9bab0dd1438d6cc8699c6884445ad409b`；根 Apache-2.0 | `src/services/sqlite/SessionStore.ts:getObservationsByIds:3115-3147`; `observations/get.ts:getObservationsByFilePath:8-70`; `ProgressiveMemorySearch.ts:indexRow/fetch:15-23,90-105`; `observations/store.ts:computeObservationContentHash:16-25` | observation ID 稳定定位派生记忆，hash 按 session/title/narrative 去重，支持 observation fetch/路径关联；它不是 transcript message ID 或字符 span。TS/Bun/SQLite，中等移植成本。 | 本地源码实读 |
| LongMemEval-V2 | `2cc8c540bdb87fe6761629b585e727e1c4704520`；根 Apache-2.0，memory_modules 无子许可 | `memory_modules/trajectory_store.py:save_json/load_json:15-22`; `logical_trajectory_fingerprint_from_simplified:174-177`; `prepare_trajectory_insert:180+`; `materialize_prepared_trajectory:376-394`; `validate_pooled_trajectory_dir:397-466` | 以 trajectory ID 存 JSON 和截图，保留 state/step/url/action/thought/树/截图；规范化 SHA fingerprint 校验文件数和引用，错误抛出而无自动重试。适合可复演电脑轨迹，不是产品期 transcript memory。Python 低成本但文件/截图存储需规划。 | 本地源码实读 |
| AMA / AutoMemory | `b411e86f945c1058eddafabfdefd55da93a4d6a4`；API license unknown，未见根或 reference 子树 LICENSE | 目标 `tool.py` 未在该 commit clone 中；仅 `reference/ama-agent/details.md:27,117` 提及 `traj_find/traj_get` | 不把文档冒充源码。可能是 turn_idx/action/observation 级轨迹检索，但写入、重试、去重/纠错、指针解析与反馈均未实证。完成前不得移植。 | 源码缺失；文档级线索 |
| agent-memory（新增） | `bettyguo/agent-memory@d38704818ae7e84a4e154cd79494af0742deba18`；Apache-2.0 | `src/trace_mem/store.py:get_turn:287-302,verify_citation:305+`; `citation.py:sign_citation/verify_citation_signature/verify_citation_content:40-80` | SQLite turns 主键 trajectory+turn；citation 带 turn、字符范围、内容 SHA 和 HMAC，读取时重新展开原文并验篡改。内容修订会使旧 citation 失效，未见自动重基准。Python/依赖轻，最贴近精确可验证锚点。 | 本地源码实读 |
| NLM Memory（新增） | `pbmagnet4/nlm-memory@2689952f525b44e230e648230ab69655dadb2780`；Apache-2.0 | `src/core/transcript/current-session.ts:findCurrentSession:90+`; `src/core/hook/pointer-block.ts:formatPointerBlock:65-114`; `src/core/recall/citation-log.ts:appendCitation/readCitation/citationStats:56+` | 多宿主 adapter 找 SessionChunk，pointer block 给 ID/title，另用 get_session 展开 transcript；JSONL citation log 统计使用情况。需要确认 adapter 对消息级 ID/span 的稳定性。TS 端口中等。 | 本地源码实读 |
| OpenClaw active-memory（新增） | `c98311f906972e2a33d6ef3c6ecf027c90256ec6`；根 MIT，extension 无子 LICENSE | `extensions/active-memory/session.ts:prepareActiveMemorySession:24-60`; `transcript.ts:streamActiveMemoryTranscriptRecords:49+` | sessionKey/sessionId 定位活跃会话并流读 transcript record；没有持久 message/span proof。适合作 session id→日志入口。TS宿主耦合中高。 | 本地源码实读 |

### 裁决与 Atlas 映射

第一：Atlas SessionDB 的 `message_uid` 作 canonical FK，叠加 agent-memory 的 span/hash/HMAC 校验；这样来源可逐条展开并识别源文变更。第二：Codex rollout path 快速恢复完整线程；NLM 的短指针、全量下钻和使用统计是好 UI/交互模式。Claude-Mem observation ID 只标识派生记忆，不应冒充原文锚点。

移植清单：`agent-memory.get_turn + citation content hash → core/atlas/engine/session_sync.py:session_message_evidence`，但改用 `(conversation_id,message_uid,part/span)` 并基于 Atlas 身份校验；`Codex.resolve_rollout_path → session_sync.py:read_session_all_messages` 作为全轨迹回退；`NLM pointer_block/get_session → memory library 的引用显示与显式展开`；`LongMemEval fingerprint/截图子项 → 未来 computer event attachment integrity check`。Atlas 现有 `_message_for_atlas:53-70` 把 SessionDB `message_uid` 映射到 Atlas `id`；`read_session_messages:73-88` 支持 before_id 分页；`session_message_evidence:207-223` 查稳定 uid；`include_compacted=True` 可读归档内容。不要额造 message id。

Claude 骨架：修改后支持。文件引用只足以定位手册，不足以指向原话；每个事实必须有稳定原文 FK、可选 span 与 proof hash。纠错/删源时旧证据标失效，不静默改写。用户可改透明记忆文件，但原始 transcript 是证据，不能被重建覆盖。

尚未查清：AMA 上游真实 `tool.py` 和 license；Claude-Mem ingestion 到原始 transcript 的 message/字符映射；Codex 拆解包和 pinned commit 的逐文件一致性；NLM adapter 是否都提供稳定消息 ID。新增候选查询：`"agent trajectory" "source span" citation HMAC`；`"get_session" "transcript" memory agent hook`；`"sessionId" "transcript records" agent memory plugin`。

## M6 委派与外部 Agent 记忆

### 对比表

| 项目 | commit / 许可 | 关键源码:函数:行 | 做法、强弱、移植成本 | 证据 |
|---|---|---|---|---|
| Hermes | `607a0b0d41e07d903c0b475dd72fb6ac2b37fecc`；MIT | `agent/memory_provider.py:on_delegation:180-181`; `memory_manager.py:on_delegation:937+` | hook 是父侧观察已完成委派；child 没有 provider session。没有自动给 child 填长期记忆或注入策略。优在清晰回调边界，不能视作完整 handoff 设计。Python 端口低。 | 本地源码实读 |
| Codex 子线程 | `openai/codex@a45b8ccb016fb74f63a6bc29e701568e387cbe38`；根 Apache-2.0 | `codex-rs/core/src/agent/control/spawn.rs:spawn_agent_internal:684,prepare_forked_history:1023`; fork selection `:807-852`; `codex-rs/memories/README.md:213-220,232-281` | fork mode 控制 initial history；memory Phase1 只 root session，避免对子代理重复提炼；consolidation subagent 只拿 workspace diff，受限工具权限。可借 root-only writer + 显式 child packet 原则。README仅架构说明；Rust端口高。 | 本轮 sparse local clone |
| OpenAI Agents Python SDK | `openai/openai-agents-python@17d994bd3045dae71acda676a4ef4762ed8ecd94`；根 MIT | `src/agents/memory/session.py:Session.get_items/add_items/pop_item/clear_session:53-93`; `sqlite_session.py:18-94,132-165,209-222`; `handoffs/__init__.py:HandoffInputData:70+, Handoff.input_filter:158-160, handoff:229+` | Session 以 session_id 隔离的可插拔对话历史，SQLite 文件可持久化且处理锁；handoff input_filter 可过滤交给下一 Agent 的 transient context。没有父子 session 自动共享长期记忆。Python/SQLite接 Atlas低。 | 本地源码实读 |
| CrewAI | `6115839576d68d2e83b9f7f31e6c55d471e1fc64`；根 LICENSE；`lib/crewai` 无子许可 | `lib/crewai/src/crewai/crew.py:Crew.create_crew_memory:3340-3394,_reattach_memory_views:3155-3206`; `agent/core.py:Agent._retrieve_memory:3474-3587` | crew 共享 `/crew/<name>` hierarchical memory scope；任务前用 task description recall(limit=5)，发 retrieval events；读取失败降级无记忆。写入触发/修正/去重需看 unified Memory 后端。Python但 RAG/embedding 抽象较重，中高成本。 | 固定 SHA 的 GitHub 源码页实读；本地 checkout 因磁盘问题不完整 |
| MemOS sub-agent | `a7367d07e55db61099f7b4e2c1108bc5831a24f3`；根 Apache-2.0，插件无子许可证 | `apps/memos-local-plugin/core/retrieval/retrieve.ts:subAgentRetrieve:174-187`; `orchestrator.ts:retrieveSubAgent:1166-1172` | child 仅取 Tier2 与可选 Tier3，排除 Tier1/low-value，受 topK 限制；输出 injection packet 并发 retrieval event。使命相关性优，TS+MemOS 服务依赖高。 | 本地源码实读 |
| open-multi-agent（新增） | `d4084ef803c4cfb9b241e5545b2ff236ceb2603e`；根 LICENSE，packages/core 无独立许可 | `packages/core/src/tool/built-in/delegate.ts:87-107`; `memory/shared.ts:4-7,49-98`; `memory/store.ts:31-79` | 委派完成后将结果、delegatedTo/success 写到带 agent 命名空间 shared memory；写失败不使业务任务失败；可替换存储、upsert/CAS。key 随机而非幂等，默认内存易丢，summary 是否注入看调用点。TS端口中。 | 本地源码实读；完整 checkout 需留意磁盘告警 |
| AgentMemory（新增） | `b5e00d027bc0f5f6cb7529bc1acfe6688ba105d1`；未发现许可证文件，待确认 | `src/services/memory-orchestrator.ts:40-80` | 项目级 recall facade/hybrid retrieval，可作跨 agent 服务边界参考；不是 delegate 专用，证据不足以裁决。 | 本地源码实读 |
| AgentEnsemble（新增） | `agentensemble/agentensemble@d77d6460bda40f8eccb78d05fcc36861225d845f`；根 MIT，`agentensemble-core` 无子 LICENSE | `agentensemble-core/src/main/java/net/agentensemble/delegation/AgentDelegationTool.java:349-427`; `Ensemble.java:1571-1588` | 保存带角色、描述、耗时、depth、result、worker trace、success 的 DelegationTrace；不显式传任务记忆，v2.0 MemoryContext disabled，默认仅 run 内 ephemeral。失败转 response，无自动重试。Java移植中高。 | 固定 SHA 源码实读 |
| Letta | `5bcdd177d70fa2b31a754cfcd801e77b2e1ab16a`；本地目标树未包含 `letta/services/group_manager.py`，该 SHA URL 404；许可/目标实现未核 | 目标 shared block 函数无法验证 | 不把 DeepWiki 二手摘要当源码。Letta shared blocks 机制本轮不可比较。 | 明确缺口 |
| Claude Code subagents | 公共 `anthropics/claude-code` 仓库不含产品实现源码 | 官方拆解可见 `tools/AgentTool/runAgent.ts` SubagentStart `530`; lifecycle hooks `SubagentStart/SubagentStop` | 能核实事件启动钩子与公开行为，不能据此断言其子代理自动继承主会话记忆；公开仓库不含内部 memory策略。 | 官方拆解源码；产品策略未核 |

### 裁决与 Atlas 映射

最强的组合细节：open-multi-agent 的有归属、可审计委派结果记录；第二是 MemOS 的按子代理使命分层召回。Hermes 的 `on_delegation` 是很好的 callback 边界，但它只是父侧完成后事件，不自动提供上下文。Codex 提供不重复提炼的 root-only writer 策略。Atlas 应在派发前构造最小上下文 packet（任务范围、出处明确的相关记忆、如何按需取回），让有权限的外部 agent 通过工具继续取记忆；完成后 parent 收回结果、保留子会话轨迹指针并送入统一后续提炼。孩子默认不独立运行长期记忆写入，防重复/自我强化。

移植清单：`MemOS.subAgentRetrieve → core/atlas/agent/enrichment.py:delegate_task` 的任务条件召回；`OpenAI Handoff.input_filter → delegate_task` 的 packet 裁剪；`open-multi-agent shared namespace + delegate record → enrichment.py:delegate_task/delegate_parallel` 产出的 delegation event（用确定性 parent/task key，补幂等）；`Hermes.on_delegation → agent_hooks.py:AgentHooks` 的父侧完成回调；`Codex root-only phase1 → memory writer` 去重策略。使用 Atlas session id 与 M2 message UID 回链，不复制整段对话。

Claude 骨架：修改后支持，不可假定子 Agent 获得主 Agent 的全部 memories；授权全开也不代表无关/过量注入。需求拍板项：委派完成结果是否只存成可审计记录后按需读取，还是立即按预算生成 child summary packet。建议两者分层：持久化完成记录；只有调用方明确需要时再派生限额摘要。

尚未查清：Letta pinned 源码、AgentMemory 许可、CrewAI Memory 后端的写入/纠错/使用反馈、Hermes hook 的参数和异常边界全量。新增候选/搜索词：`open-multi-agent/open-multi-agent`、`AndrewMoryakov/AgentMemory`、`AgentEnsemble/agentensemble`；`agent memory shared context runtime MCP`；`shared memory multi-agent orchestration`。AgentEnsemble 通过 pinned Git blob 源码读取了委派实现，但不是完整 checkout。

## M8 经验转技能并合并 SkillOpt

### 对比表

| 项目 | commit / 许可 | 关键源码:函数:行 | 做法、强弱、移植成本 | 证据 |
|---|---|---|---|---|
| MemOS skill lifecycle | `a7367d07e55db61099f7b4e2c1108bc5831a24f3`；根 Apache-2.0 | `core/skill/eligibility.ts:evaluateEligibility:45,decide:64`; `skill.ts:runSkill:65,applySkillFeedback:285`; `verifier.ts:verifyDraft:46`; `lifecycle.ts:applyFeedback:37,applyTrial:59`; `crystallize.ts:230-304`; prompt `skill-crystallize.ts:19-78`; UI `viewer/src/views/SkillsView.tsx` | 证据足够、支持数/成功锚点/政策增益准入；3–10 traces、工具白名单、counter-example；candidate→trial→active/archive，试验、用户 thumbs、reward 反馈；结构校验失败带 correction context 重试一次，再原子 upsert。Prompt：“Don't invent guidance unsupported by the inputs.” 逻辑适合 Python 重写，插件服务与 TS UI 中等成本。 | 本地源码实读 |
| Hermes skill evolution | `607a0b0d41e07d903c0b475dd72fb6ac2b37fecc`；MIT | `agent/background_review.py:_review_tool_whitelist:1088,_run_review_fork:1147,spawn_background_review_thread:1310`; `tools/skill_manager_tool.py:_create_skill:453,_patch_skill:508,skill_manage:768`; `agent/curator.py:apply_automatic_transitions:209`; `hermes_cli/journey.py` edit/display/delete | 后 turn review fork 可更新 skill 或 memory+skill；先补当前技能再扩 support files、拒绝每 session 新造；用户可见可编辑，写入 gated。弱在提炼质量更多依赖 LLM prompt，无 SkillOpt 同级 heldout gate。Python移植中高。 | 本地源码实读 |
| SkillOpt-Sleep / Atlas adapter | `microsoft/SkillOpt@343db229dbd5ddaf9df6b1d5540d8bcdb2604d5c`；根 MIT，`skillopt_sleep` 无子 LICENSE | `skillopt_sleep/cycle.py:run_sleep_cycle:625,797-820,989-1039,1090-1093`; `consolidate.py` gate `135-173`; `staging.py:adopt:3028`; Atlas `core/atlas/evolution/skill_sleep.py:harvest_atlas:43,run:111-125` | harvest→mine→分 train/heldout→replay/consolidate gate→stage；默认 validation gate 拒绝未改进 proposal，candidate 先 staging，auto-adopt 是 opt-in，accepted 前不覆写 live skill；gate 可配置，不应将“必定严格提升”当无条件结论。Atlas adapter 将 `evolve_memory=False`，保留记忆与 skill 分工。Python成本低至中，实际模型/replay 成本由 backend 决定。 | 本地源码实读 |
| Codex phase2 | `openai/codex@a45b8ccb016fb74f63a6bc29e701568e387cbe38`；根 Apache-2.0（memories子树无独立许可） | `codex-rs/memories/write/src/phase2.rs:run:49`; `templates/memories/consolidation.md:29-32,137-145,687-756,813-863` | consolidation agent 增量读现有技能/手册；重复程序且明显省时/减少错误才建 skill；`SKILL.md`+scripts/templates/examples。Prompt：“Create a skill when the procedure repeats (more than once) and clearly saves time or …”。文件可读可 git diff；没有独立 heldout 成功门。Rust高成本，只移植准入和格式约束。 | 本轮 sparse local clone |
| ReasoningBank | `thakshak/ReasoningBank@0669c7e8697100b1779d284834f8562248db2d2a`；MIT | `reasoningbank/core/bank.py:ReasoningBank.add_experience:107,retrieve_memories:147`; `distillation/distill.py:judge_trajectory:12,distill_trajectory:41`; `memory/json.py:44,54` | 将成功/失败归纳成策略并向量 top-k；无标准可编辑技能包和完善生命周期。Python但 Chroma/LangChain 中等。 | 本地源码实读 |
| ExpeL | `e41ec9a24823e7b560c561ab191441b56d9bcefc`；Apache-2.0 | `agent/expel.py:success_critique:152,failure_critique:173,_build_critique_prompt:202,create_rules:287,update_dynamic_prompt_components:498,parse_rules:665,is_existing_rule:689,update_rules:696` | 成败轨迹反思成 lesson/rules，add/delete/replace 并向量召回；可借成败对照，非可维护 SKILL 包。研究依赖/模型成本中高。 | 本地源码实读 |
| Voyager | `55e45a880755d0c8c66ca7fb5fe7962ac8974f89`；MIT | `voyager/agents/skill.py:SkillManager.add_new_skill:61,generate_skill_description:102,retrieve_skills:114`; `voyager.py:reset:165,step:203,learn:295`; `prompts/skill.txt` | 成功 JS 程序+描述落 skills.json/代码/向量库，执行失败可反馈改代码；可执行性强，Minecraft/Node/LLM/Chroma 强绑定。只借“已成功 procedure”形状。 | 本地源码实读 |
| Anthropic skills format | `anthropics/skills@dbd4588f9e1033efb41dad4bef2f7947c8993d44`；根未声明 LICENSE，部分 skill 需逐包核许可 | `skills/skill-creator/SKILL.md`; `scripts/run_eval.py`, `quick_validate.py` | 文件格式是 frontmatter + SKILL.md + scripts/references/assets；建议 draft→少量 eval→反馈改写。不自动从经验提炼。透明文件零服务成本；复用格式前逐目录核许可。 | 本地源码实读 |
| Agent Workflow Memory / AWM | `zorazrw/agent-workflow-memory@8c0ff8cd11d648c8fceb99e4e42f37e3b75381b1`；根 Apache-2.0，mind2web/webarena 未见子 LICENSE | `mind2web/online_induction.py:get_trajectory:18-28,main:31-63`; `offline_induction.py:llm_generate:54-68,save_to_txt:71-77,main:94-101`; `utils/data.py:filter_workflows:73-86`; `memory.py:get_exemplars:15-40`; `workflow/retrieve.py:build_memory:58-78` | 从 web action trajectory 归纳网站 workflow 并写可读 txt；exemplars.json 随机取例，另有 FAISS/OpenAI embedding workflow 相似检索。更新覆盖输出文件，过滤 header/delta 但没有稳健版本/纠错/使用反馈；API失败在主生成路径无统一 retry。Python但 LangChain/OpenAI/FAISS+WebArena评测域，中高成本。领域特化，适合作为经验转 workflow 的对照而非通用记忆。 | sparse local clone 源码实读 |
| OAWM（新增） | `dddaea42073fc9629122cdb798f547c5d6a116e9`；Apache-2.0 | `src/observable_agent_workflow_memory/adapters/sqlite_storage.py:SQLiteStorage.initialize:47,search_memory:515` | workflow raw→candidate→shadow→certified/quarantine/contradiction，EvidenceManifest + invocation-bound PromotionReceipt；值得借晋级凭证/审计层。Python+Typer/LiteLLM，中等。 | 本地源码实读 |
| MemForge（新增） | `16e2f15c5881a38911f64ca81b3dc0b25d6207ec`；MIT | `src/sleep-cycle.ts:phaseProcedureEvolution:1328-1365` | procedure 成功/失败计数与置信度做滞后升降/停用，不产 skill 文件；TS/Postgres 服务成本高，只借反馈/hysteresis。 | 本地源码实读 |
| AgenticMemory（新增） | `9d20fc4af3dea32ea9b2f28e490459cdb63c6e28`；MIT | `agent/amem_agent/memory/extractor.py:extract_events:517`; `context.py:extract_and_store:247,build_memory_context:152` | 结构化 event 含 skill 类型，可跨 provider 传递，但只是提取出的技能事实，不是 procedure package；弱相关。 | 本地源码实读 |

### 裁决与 Atlas 映射

第一 MemOS，强在“证据/准入→受约束生成→验证→候选试用→明确反馈→晋级/归档”的完整软件生命周期；第二 Hermes，强在真实运行期 post-turn review、技能编辑与用户可见治理。独立质量门最强为 SkillOpt heldout replay，但它不代替 MemOS 生命周期。Codex 给渐进文件结构和“重复且省时才创建”，Anthropic 给透明技能包格式；都必须增加成功验证/保护用户修改。

移植清单：`MemOS.evaluateEligibility/decide → core/atlas/evolution/skill_sleep.py:harvest_atlas/run` 增来源等级、episode 支持数、成功锚点与候选理由；`MemOS skill-crystallize + verifier → skill_sleep.py` 生成候选并校验结构/工具证据白名单，失败仅重试一次；`SkillOpt heldout gate → skill_sleep.py:run` 候选先 staging，严格超过 baseline 才可 adopt（本轮上游细节待核）；`MemOS lifecycle/Hermes skill manager → skill UI/registry` 增 trial、用户反馈、归档、可见 diff，用户手改保护；`Codex+Anthropic format → learned skills` 写清 metadata、步骤、工具、示例和 eval，不搬其未经验证 prompt；`Voyager add_new_skill → 候选生成` 只从已验成功 episode 生成，禁止直接将任意工具调用变可执行脚本。

Atlas 当前 skill manager 已有单一索引、多来源和优先级：`core/atlas/skills/__init__.py:29` 定 `SKILLS_DIR`；`SkillManager.register_skill_source:309-321` 注册来源并稳定裁决同名；`scan_skills_sync:355-396` 扫描 `SKILL.md`；`list_skills/skill_count:404-429` 暴露查询；`default_skill_sources:583-637` 接 Atlas、library、可选 Hermes、Claude 用户/项目和插件目录。可把那 3,298 项以只读外部来源接入索引，不将其内容复制成记忆；记忆只存“何时用哪个 skill、结果/反馈如何”，候选经 SkillOpt。当前 checkout 未发现名为 3,298 技能目录的实际外部库存，故库存的归属、许可证、重复率、结构兼容性仍未核。本地 `skills/` 根下目前仅 7 个一级目录，不代表外部总库存。

`skill_sleep.py:43` 收集来源会话，`run:111` 配 SkillOpt cycle；`evolve_memory=False:125` 明确记忆库与技能学习分开。待确认收集源是否包含外部/子代理。

Claude 骨架：支持但加“候选不等于技能”阶段；候选只能经证据门、失败对照、可重复性、用户反馈和 heldout baseline 后进入可用目录。日更 git diff 保留用户手改，不自动覆盖；保留独立 `skills/` 索引而记忆只记录使用效果。

尚未查清：Anthropic 每个 skill 子目录许可、现存 3,298 技能目录的归属/许可/重复率盘点、skill_sleep 的 child-source 覆盖与反馈完整性。新增候选查询：`agent procedural skill evolution feedback lifecycle`；`promotion receipt verified workflow memory`；`agent skill confidence success failure sleep cycle`；`LLM skills from successful and failed trajectories`。

## 多模态事件字段（只研究，不施工）

### 对比表

| 项目 | commit / 许可 | 关键源码:函数:行 | 做法、强弱、移植成本 | 证据 |
|---|---|---|---|---|
| Omni-SimpleMem（SimpleMem子项目） | `Ssabal/SimpleMem@74174a1c0c95d487144a74a77addb2c23f27f783`；root SimpleMem MIT；`OmniSimpleMem/LICENSE` Apache-2.0 | `OmniSimpleMem/omni_memory/core/mau.py:17-24,43-59,91-160`; image/audio/video processors `69-204/53-223/62-167`; `orchestrator.py:348-388,481-523,700-826,1290-1347` | MAU 统一 modality/metadata/raw_pointer/details/region pointers/lazy retrieval；图像、语音、视频派生；反馈 API。重复文本用 session-local Jaccard >.8；无通用修订谱系/全链重试。依赖 torch/transformers/faiss/音视频库，Python移植高。 | 本地源码实读；嵌套许可证已分别核 |
| Screenpipe | `1ebd12af8e0f361ef318af2f4613306213379f5f`；根 `LICENSE.md` 为自定义商业许可，非可直接复制 OSS；商业使用单独许可 | `crates/screenpipe-db/src/types.rs:153-199,227-246`; `db/memories.rs:12,50,93`; `db/feedback.rs:13` | OCR frame/file/offset/text box/app/window/url/device/trigger 与音频 chunk path/offset/engine/speaker/time/diarization；memory 可增改删、反馈按 target/version/actor/device。端侧来源跟踪强但 Rust 捕获堆栈高成本且不可直接移植。 | 本地源码实读 |
| MIRIX | `8cb06a62bbb7c478beb33dd4f2815696a72df482`；Apache-2.0 | `schemas/mirix_message_content.py:33-52`; `schemas/skill_experience.py:60-99`; `auto_dream_manager.py:479-536`; `memory_tools.py:1613,1648-1700` | 多模态消息 link image_id/file_id/cloud URI；SkillExperience 留 session+quote 但无 message offset；sealed-session失败保留 retry，成功 auto-dream 会 prune transcript。可借 quote/session出处与保留策略；pointer schema不统一 modality。 | 本地源码实读 |
| memU | `NevaMind-AI/memU@3ef9aeab4b14bfd5eb106ffe326e04a67501daaa`；Apache-2.0 | `src/memu/database/models.py:19-56`; `app/agentic.py:187-230,393-490`; `embedding/http_client.py:160-189,191-254` | Resource 存 URL/local path/caption/vector/track，但无规范 MIME/modality；multimodal embed client 缺 production call site。普通embedding对429/5xx重试，多模态请求未见重试。服务依赖中高，只借 pointer/caption 模式。 | 本地源码实读 |
| Second-Me | `mindverse/Second-Me@d0e40251d9de61b3340b8d0d7d83150669f1885a`；根 Apache-2.0；vendored `lpm_kernel/L2/gguf-py` 有独立许可 | `lpm_kernel/file_data/document_service.py:61-117`; `processors/image/processor.py:11-28`; `file_data/document.py:10-35`; `models.py:48-71` | OCR/document 有 mime/raw_content/url/summary/insight/status/chunks，但没音频/视频字段或 raw media system；错误置 failed、无自动 retry。可读 source pointer，端到端扩展大。 | 本地源码实读 |
| V-Mem（新增） | `Dingyi-Kang/V-Mem@36916b14dc5241e04acbf5cd0f3c40799bc09550`；根 MIT | `model.py:17-86`; `load_memgallery.py:60-95`; `build.py:80-138`; `retrieve.py:79-98,132-179,210-223` | 文本+图像 lane、round/session 元数据、RRF 后折叠回对话轮；视觉编码失败跳过，无重试；图像保留 URL/id，不负责编辑/反馈。Python中成本中，需 embedding/视觉服务。 | 本地源码实读 |
| TaskMem（新增） | `ByteDance-Seed/TaskMem@dfc20dbda118a08bceae9d83d57dab2f1b0948b2`；Apache-2.0 | `src/main.py:94-190`; `memory/short_term_memory.py:95-152`; `memory/memory_process.py:60-75`; `memory/long_term_memory.py:102-135` | 多模态视频按 clip/时间/speaker/face/VAD 处理，episode per clip；阶段可重跑，episode 生成有 retry；按 clip_id 覆写；没有统一校正谱系/UI反馈。ffmpeg/ASR/人脸/VLM依赖极高。 | 本地源码实读 |
| TeleMem（新增） | `TeleAI-UAGI/telemem@f7724ceb939a9474559992e55ac15085e61a85c1`；Apache-2.0 | `telemem/mem0.py:add_mm:691-796`; `build_database.py:129-239,344-367`; `mm_utils/memory_utils.py:28-68` | 视频分段、时间戳/帧字幕/向量检索；已有 artifact skip 但不核源版本；文本错误可重试，视频分支纠错反馈弱。Python/Mem0与VLM/vector依赖中高。 | 本地源码实读 |

### 裁决与 Atlas 预留字段

字段设计第一选 Omni-SimpleMem 的通用 asset/pointer/region/lazy detail 结构，第二选 Screenpipe 的 capture provenance、时间位置、可编辑 memory 和 versioned feedback（只借字段概念，不复制商业许可代码）。V-Mem 的 modality-specific retrieval lane 与 TaskMem 的 clip/speaker/frame 索引可补充。MIRIX 显示经验 quote 若无 message offset 仍无法精确追原文。当前排名按源码模式匹配，不是 Atlas 端到端测评。

Atlas 已有 `channels/contract.py:34-43` Attachment(kind,url,local_path,filename,mime_type,size,meta)；`api/run_drive.py:2114-2137` 的图像输入为限额的临时 data URL；`run_phases.py:643-649` 将图片描述为 transient；`agent/__init__.py:871-878` 拼 multimodal model input。SessionDB 的 `message_uid` 已可用，附件应以其为父键，不在 content 内嵌 base64。

建议未来的独立 asset/attachment row（仅研究）：`attachment_id`, `message_uid`, `modality`, `mime_type`, `source_kind`, `source_uri`（本地相对/对象地址与外部 URL 分开）, `sha256`, `size_bytes`, `captured_at`, `media_start_ms/end_ms`, `derived_text`（OCR/transcript/caption）, `speaker_ids/person_ids`, `processing_status`, `processor/model/version`, `attempt_count`, `edited_at`, `supersedes_attachment_id`。音视频分段/图像 crop 另以 parent_attachment_id、offset/duration/frame_index/region pointer 关联；原始指针永不由可编辑派生文本替代，哈希用于去重，supersedes 记录纠错。旧记录无附件则留空，不从不可追溯 inline payload 猜造。

Claude 骨架：支持透明且用户可改的文本层，但把媒体本体作为第一类外部资产引用，并保留原始证据、派生文本、处理器/版本、失败重试与修订链；目前视觉/语音/手机仅预留 schema，不采集、不施工。

尚未查清：屏幕/媒体二进制的隐私留存策略与用户授权模型、跨设备 source_uri 稳定性、MIRIX viewer/edit path、Atlas 未来 ASR/OCR provider 选择。新增候选检索词：`multimodal memory agent video image audio memory open source 2025`；`AI agent multimodal memory episodic video images repository`；`long-term memory agent multimodal image video audio open source`。

## 本机官方拆解源码横查（任务书第 1 节）

以下是本机 `D:\_deliverables\官方拆解汇总` 的只读交叉核对，用于避免把 transcript/session 持久化误认成长程语义记忆。官方 artifact 无 Git/许可元数据的产品按其真实来源版本与证据类型报告，不虚构仓库 SHA。

| 产品 | 已核实源码锚点 | 对 C 线结论 | 来源/许可边界 |
|---|---|---|---|
| Claude Code | `ClaudeCode-Official/07-TYPESCRIPT-SOURCE/src/src/entrypoints/sdk/coreSchemas.ts:362-365`; `tools/AgentTool/runAgent.ts:530`; `utils/hooks.ts`; `skills/bundled/updateConfig.ts:145` | M1 有丰富事件 hook；公开 artifact 未证明子代理 memory 自动继承。M8 的 Skills 是可调用文件协议，不是 experience-to-skill 自动学习证据。 | 本机 TypeScript 源码拆解；不是本轮公开 repo clone |
| Codex CLI | `Codex-Official/03-SOURCE/codex-rs/memories/...`；pinned `openai/codex@a45b8ccb016fb74f63a6bc29e701568e387cbe38` | 两阶段 writer、root session 范围、rollout/citation 与 skills 渐进写入见 M2/M6/M8。 | 本机官方拆解及固定 GitHub 源码；本机源码包 `03-SOURCE/LICENSE` Apache-2.0，未见 memories 子树独立许可证 |
| Hermes Desktop 0.21.7 | HEAD `71d34bad1045610252eda02ee79549436896e784`；`agent/memory_provider.py:84-196`; `agent/agent_init.py:1184-1185,1265,1374-1375`; `acp_adapter/provenance.py:32-80`; `acp_adapter/session.py:156-159,308,447`; `agent/background_review.py` docstring/378 | provider 的 prefetch/session/delegation 回调真实接入；初始化区分子代理 memory writes。父子 provenance 只到 session，不是消息 span。post-turn review 会提议改 memory/skill，不等于确定性提炼或已验证晋级。图像/视频输入转换在 `acp_adapter/content.py:_image_parts:134-138,_image_block_to_openai_part:236-246`; `agent/auxiliary_client.py:6508-6512`。 | 真实仓库源；MIT |
| OpenClaw | 官方本机 `OpenClaw-Official-2026.10.3/03-SOURCE@59cb44796b0f1f0daa0e37af8b1495abb45d9bc1`; `extensions/active-memory/index.ts:register:63,before_prompt_build:212,agent_end:604`; M2 `session.ts:24-60`, `transcript.ts:49+` | lifecycle/bounded recall、session→transcript 入口可核；没有持久 message/span 锚点。 | 本机真实源码；MIT。另有本轮 pinned clone SHA `c98311f906972e2a33d6ef3c6ecf027c90256ec6` |
| Codex Desktop artifact `CodexDesktop-Official-26.1007.2314.0` | `07-BEAUTIFIED/FORMATTED/.../chatgpt-subagents-panel-e7913e8a5ec3.js:31-51` | bundle 确认 subagent UI；没有足以证明本地语义 memory hook/source pointer/experience→skill 的 runtime 源码。不能由 UI 推断云端 Memory。 | Electron ASAR beautified JS，无源码仓库/commit/license；仅包内实现级观察 |
| Pi Coding Agent 1.2.0 | HEAD `06a466935536f8c9bcacb2d5efc0fc021be1bdff`；`packages/coding-agent/src/core/agent-session-runtime.ts:143-160,218-345,397`; `agent-session.ts:1292,1881-1907`; `agent.ts:372-373`; images `agent-session.ts:318,2004-2041,2133` | 有 session/fork/compaction 生命周期及图像输入，但未见统一 durable semantic memory provider 或原文 span pointer；正式子代理运行时契约未发现，extension 可自行实现。 | 真实源仓；MIT |
| OpenCode 1.19.0 | HEAD `733b2c627e5aec39cb33cc22373bdce33053ef2c`; `packages/opencode/src/session/message.ts:45-90`; `session/session.ts:224-231,260-262,417,504-521,596-600`; `tool/task.ts:81-170`; `tool/skill.ts:13-60` | 有 durable conversation tree 与 task delegation；MessagePart 是通用 Text/File/SourceUrl，没有专用 image/audio/video 字段；skill 是加载工具。未见语义 memory provider、原文字节区间或经验自动产 skill。 | 真实源仓；MIT |
| ZCode 3.15.3 Windows x64 | `08-BEAUTIFIED/out/host/index.js:63781-63925` (`createMemoryService` 的 load/save/clear/list/read); preference/runtime `:73646,77572,79744`; bindings `:79875`, `chunk-T2GB4I3K.js:3801-3803,6314,6382`; session/subagent `index.js:15585,15620,15652,15661,16331-16388` | 本地 `~/.claude/memory` 与 project memory 文件可 load/save/clear/list/read，受 memory-enabled preference 控制；未证实原文 message/span pointer、session lifecycle hook 或自动经验转 skill。 | 安装包 beautified bundle，无源仓/commit/license；仅反编译代码观察 |

官方产品核查因此支持一个重要边界：在已检查 artifact/source 范围内，Codex Desktop、OpenCode、Pi 的 transcript/session persistence 不能称为语义记忆；ZCode 已证实有本地 memory 文件服务，但没有原文 span 或经验转 skill 证据；Hermes Desktop 有真实跨 session provider lifecycle。公开 Claude Code 仓库不含产品源码，不能以此宣称全实现缺失。

## 需要用户拍板

1. 委派产物：建议完整完成记录统一存储，子代理只按使命收取限额相关记忆；调用方按需取回完整轨迹。
2. 技能晋级：建议 MemOS 的证据准入 + SkillOpt heldout 任务回放作为必要晋级条件，用户手改必须进入受保护版本/diff，不被 nightly rebuild 覆盖。
3. 多模态：采用可编辑派生文本与不可变 raw pointer 分层，媒体字节按用户/设备策略保留；本轮不开始实现采集。

## 整体未查清

- 本轮 D: 可用空间降为 0；部分 checkout 因此不完整。对已知失败 clone 的精确目录清理命令被自动策略拒绝，未绕过。不得声称任务书要求的所有候选均已 clone。
- AMA `tool.py`、Letta pinned shared-block源码、AWM源码/许可、SkillOpt上游SHA与内核、部分 Anthropic skill 子目录许可证仍缺；详见各模块。
- 项目许可和移植成本只是基于本轮看到的 manifest/LICENSE/依赖，不是法律意见或性能测量。没有运行代码或测试（本任务为调研）。

## 新增候选

| 模块 | 新候选 | 搜索词 |
|---|---|---|
| M1 | LangChain AgentMiddleware (`langchain-ai/langchain@c088db971097f0f12c7b8c30d473e8dbde09c823`)、AgentMemory (`b5e00d027bc0f5f6cb7529bc1acfe6688ba105d1`)、open-swe (`b15db46a513d20a330c1a6294921e70a2aaaf977`; 仅看到 `docs/CUSTOMIZATION.md` `@after_agent`，不计完整源码审查) | `site:github.com agent memory lifecycle hooks before_agent after_agent hooks`; `agent memory hooks UserPromptSubmit PostToolUse fail-open SQLite` |
| M2 | bettyguo/agent-memory、pbmagnet4/nlm-memory、openclaw/openclaw | `"agent trajectory" "source span" citation HMAC`; `"get_session" "transcript" memory agent hook`; `"sessionId" "transcript records" agent memory plugin` |
| M6 | open-multi-agent/open-multi-agent、AndrewMoryakov/AgentMemory、AgentEnsemble/agentensemble（pinned Git blob，未完整 checkout） | `agent memory shared context runtime MCP`; `shared memory multi-agent orchestration` |
| M8 | OAWM、MemForge、AgenticMemory | `agent procedural skill evolution feedback lifecycle`; `promotion receipt verified workflow memory`; `agent skill confidence success failure sleep cycle` |
| 多模态 | Omni-SimpleMem、V-Mem、TaskMem、TeleMem | `multimodal memory agent video image audio memory open source 2025`; `AI agent multimodal memory episodic video images repository`; `long-term memory agent multimodal image video audio open source` |

LANE C DONE
